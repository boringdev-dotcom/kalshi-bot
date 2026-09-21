"""Watcher process: discovery, prematch, 15s pollers, event fan-out."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Optional

from kalshi_bot.agents.orchestrator import handle_event
from kalshi_bot.config import Settings
from kalshi_bot.feeds.prematch import build_prematch
from kalshi_bot.kalshi.rest import KalshiClient
from kalshi_bot.kalshi.ws import stream_tickers
from kalshi_bot.models import MatchState
from kalshi_bot.notify.telegram import TelegramNotifier, build_notifier, poll_commands
from kalshi_bot.playbook import evaluate_exit
from kalshi_bot.execution import flatten_position
from kalshi_bot.store import Store
from kalshi_bot.watcher.detector import detect_events
from kalshi_bot.watcher.discovery import discover
from kalshi_bot.watcher.poller import fetch_live_state, refresh_quotes

logger = logging.getLogger(__name__)


class Watcher:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self.client: Optional[KalshiClient] = None
        if settings.kalshi_api_key_id and settings.kalshi_private_key_pem:
            self.client = KalshiClient(
                settings.kalshi_api_key_id,
                settings.kalshi_private_key_pem,
                settings.api_base_url(),
            )
        self.notifier: TelegramNotifier = build_notifier(settings)
        self.stop_event = asyncio.Event()
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._last_state: dict[str, MatchState] = {}
        self._last_discovery = 0.0

    def request_stop(self) -> None:
        self.stop_event.set()
        for task in self._poll_tasks.values():
            task.cancel()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except NotImplementedError:
                pass
        if self.store.get_control("paper_mode") is None:
            self.store.set_paper(self.settings.paper_mode)
        if self.store.get_control("trading_paused") is None:
            self.store.set_paused(self.settings.trading_paused)

        self.notifier.send("Kalshi soccer watcher started (paper default, event-triggered agents).")
        last_prematch = 0.0
        last_telegram = 0.0
        while not self.stop_event.is_set():
            now = time.time()
            if now - self._last_discovery >= self.settings.discovery_interval_sec:
                await asyncio.to_thread(self._discover)
                self._last_discovery = now
            if now - last_prematch >= 60:
                await asyncio.to_thread(self._prematch)
                last_prematch = now
            self._ensure_pollers()
            if now - last_telegram >= 5:
                await asyncio.to_thread(poll_commands, self.notifier, self.store, self.settings)
                last_telegram = now
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
        logger.info("Watcher stopped")

    def _discover(self) -> None:
        if not self.client:
            logger.warning("Kalshi credentials missing; discovery skipped")
            return
        try:
            found = discover(self.store, self.client, self.settings.watch_horizon_hours)
            logger.info("Discovery saved %s games", len(found))
        except Exception:
            logger.exception("Discovery failed")

    def _prematch(self) -> None:
        now = int(time.time())
        lead = self.settings.prematch_lead_sec
        for game in self.store.upcoming_games(now, self.settings.watch_horizon_hours):
            if game.get("prematch"):
                continue
            kickoff = game.get("kickoff_ts") or 0
            if kickoff - now > lead or kickoff < now - 60:
                continue
            stats = build_prematch(game["home_team"], game["away_team"], game.get("league"))
            self.store.set_prematch(game["id"], stats)
            self.store.update_game_state(game["id"], league_tier=stats.get("league_tier"))
            logger.info("Prematch stored for %s", game["id"])

    def _ensure_pollers(self) -> None:
        now = int(time.time())
        live_or_due = [
            game
            for game in self.store.upcoming_games(now, self.settings.watch_horizon_hours)
            if game.get("status") != "finished" and (game.get("kickoff_ts") or 0) <= now + 30
        ]
        live_or_due.extend(self.store.live_games())
        seen = set()
        for game in live_or_due:
            gid = game["id"]
            if gid in seen:
                continue
            seen.add(gid)
            if gid not in self._poll_tasks or self._poll_tasks[gid].done():
                self._poll_tasks[gid] = asyncio.create_task(self._poll_game(gid), name=f"poll-{gid}")

    async def _poll_game(self, game_id: str) -> None:
        logger.info("Poller start %s", game_id)
        while not self.stop_event.is_set():
            game = self.store.get_game(game_id)
            if not game:
                return
            if game.get("status") == "finished":
                return
            try:
                await asyncio.to_thread(self._tick_game, game)
            except Exception:
                logger.exception("Poll tick failed for %s", game_id)
            game = self.store.get_game(game_id)
            if game and game.get("phase") == "full_time":
                self.store.update_game_state(game_id, status="finished")
                return
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.settings.poll_interval_sec)
            except asyncio.TimeoutError:
                pass

    def _tick_game(self, game: dict) -> None:
        state = fetch_live_state(game)
        if state is None:
            if game.get("status") == "live":
                logger.debug("No live feed for %s", game["id"])
            elif (game.get("kickoff_ts") or 0) <= int(time.time()):
                self.store.update_game_state(game["id"], status="live")
            return
        previous = self._last_state.get(game["id"])
        quotes = refresh_quotes(self.store, self.client, game, state)
        self.store.update_game_state(
            game["id"],
            home_goals=state.home_goals,
            away_goals=state.away_goals,
            minute=state.minute,
            phase=state.phase,
            red_cards=state.red_cards,
            status="finished" if state.phase == "full_time" else "live",
        )
        events = detect_events(previous, state)
        self._last_state[game["id"]] = state
        if not events:
            self._price_stops(game, quotes)
            return
        fresh = self.store.get_game(game["id"]) or game
        for event in events:
            event_id = self.store.add_event(game["id"], event.event_type, event.minute, event.payload)
            payload = {
                "game_id": game["id"],
                "event": {"id": event_id, "event_type": event.event_type, "minute": event.minute, **event.payload},
                "state": state.as_dict(),
                "prior_state": previous.as_dict() if previous else None,
                "markets": quotes,
                "prematch": fresh.get("prematch"),
                "positions": self.store.positions_for_game(game["id"]),
                "pundit_memory": self.store.get_memory(game["id"], "pundit"),
                "kalshi_memory": self.store.get_memory(game["id"], "kalshi"),
            }
            summary = (
                f"{event.event_type.upper()} {fresh['home_team']} {state.home_goals}-"
                f"{state.away_goals} {fresh['away_team']} {state.minute}'"
            )
            self.notifier.send(summary)
            handle_event(
                self.settings,
                self.store,
                self.client,
                fresh,
                payload["event"],
                payload,
                notify=self.notifier.send,
            )

    def _price_stops(self, game: dict, quotes: list[dict]) -> None:
        """Price-only stop check. No LLM."""
        by_ticker = {q["ticker"]: q for q in quotes}
        for position in self.store.positions_for_game(game["id"]):
            if position["count"] <= 0:
                continue
            market = by_ticker.get(position["market_ticker"])
            if not market:
                continue
            no_mid = None
            if market.get("no_bid") is not None and market.get("no_ask") is not None:
                no_mid = (market["no_bid"] + market["no_ask"]) / 2
            decision = evaluate_exit(
                event_type="price",
                rem=market.get("rem"),
                prior_rem=market.get("rem"),
                no_mid=no_mid,
                entry_price=position.get("avg_price"),
                has_position=True,
            )
            if decision.allowed:
                flatten_position(
                    self.store,
                    self.client,
                    game_id=game["id"],
                    ticker=position["market_ticker"],
                    event_id=None,
                    reason=decision.reason,
                    paper=self.store.is_paper(),
                )
                self.notifier.send(f"STOP {position['market_ticker']}: {decision.reason}")

    async def run_held_ws(self) -> None:
        if not self.client:
            return
        tickers = [p["market_ticker"] for p in self.store.open_positions()]
        if not tickers:
            return

        async def on_ticker(ticker: str, data: dict) -> None:
            market = self.store.get_market(ticker)
            if not market:
                return
            yes_bid = data.get("yes_bid")
            yes_ask = data.get("yes_ask")
            no_bid = data.get("no_bid")
            no_ask = data.get("no_ask")
            if no_ask is None and yes_bid is not None:
                no_ask = 100 - int(yes_bid)
            if no_bid is None and yes_ask is not None:
                no_bid = 100 - int(yes_ask)
            self.store.upsert_market({**market, "no_bid": no_bid, "no_ask": no_ask, "yes_bid": yes_bid, "yes_ask": yes_ask})

        await stream_tickers(
            self.settings.ws_url(),
            self.settings.kalshi_api_key_id or "",
            self.settings.kalshi_private_key_pem or "",
            tickers,
            on_ticker,
            stop_event=self.stop_event,
        )


async def run_worker(settings: Settings) -> None:
    store = Store(settings.sqlite_path)
    watcher = Watcher(settings, store)
    try:
        await watcher.run()
    finally:
        store.close()
