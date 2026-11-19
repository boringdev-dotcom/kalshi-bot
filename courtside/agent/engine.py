"""The trading engine: one loop that watches games, trades, and learns.

Each tick:
  1. refresh games (simulator or live feeds) and re-run the totals model
  2. settle positions on finished games and grade early exits
  3. check every open agent position for an exit signal
  4. scan fourth quarters for new entries
  5. push the new picture to the UI

Orders go through `_buy` / `_sell`, the only two places that touch money.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from ..config import Config
from ..db import DB
from ..domain import QUARTER_SECONDS, Game, Rung, now_iso
from ..events import Hub
from ..feeds.live import LiveFeed
from ..feeds.sim import SimFeed
from ..kalshi.client import KalshiClient, KalshiError
from ..model.quarters import implied_margin, implied_quarter_total
from ..model.totals import refresh_game
from .learner import Learner
from .memory import MemoryStore, situation_tags
from .observer import QuarterObserver
from .playbook import Q4_UNDER, Playbook
from .policy import (
    EXIT_PROFILES,
    Candidate,
    Skip,
    exit_signal,
    find_entries,
    kalshi_fee,
    position_p_win,
    size_order,
)

log = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "trading_mode": "paper",
    "data_source": "sim",
    "agent_enabled": True,
    "max_stake_per_trade": 300.0,
    "max_open_positions": 3,
    "max_daily_loss": 150.0,
    "max_total_exposure": 900.0,
    "claude_review": True,
    "sim_speed": 6.0,
}


class TradeError(Exception):
    """A trade the engine refused or could not fill. The message is user-facing."""


class Engine:
    def __init__(self, cfg: Config, db: DB, hub: Hub):
        self.cfg, self.db, self.hub = cfg, db, hub
        self.settings: dict[str, Any] = {**DEFAULT_SETTINGS, **db.get("settings", {})}
        self.playbook = Playbook(db)
        self.learner = Learner(db, env="sim" if self.settings["data_source"] == "sim" else "real")
        self.memory = MemoryStore(db)
        self.observer = QuarterObserver(db)
        self.brain = None  # set by main once the Brain exists (it needs the engine)
        self.kalshi = KalshiClient(cfg.kalshi_api_key_id, cfg.private_key, cfg.trading_host)
        self.games: list[Game] = []
        self.by_id: dict[str, Game] = {}
        self.timelines: dict[str, list[dict[str, Any]]] = {}
        # game id -> quarter ('q1'..'q4') -> points over that quarter's 12 minutes
        self.quarter_timelines: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.feed: SimFeed | LiveFeed = self._make_feed()
        self.ticks = 0
        self.last_tick: Optional[str] = None
        self._last_real = time.monotonic()
        self._last_skip: dict[str, set[str]] = {}
        self._cooldown: set[str] = set()  # games the agent already exited; no re-entry
        self._reviewing: set[str] = set()
        self._vetoed: dict[str, float] = {}
        self._hold_noted: dict[int, str] = {}
        self._marks: dict[int, int] = {}
        self._acted_at = 0.0
        self._live_balance: dict[str, float] = {"cash": 0.0, "portfolio_value": 0.0}
        self._live_balance_at = 0.0
        self._last_state_sig = ""
        self._last_equity_at = 0.0
        self._limit_noted = ""
        self._void_orphans()

    # ------------------------------------------------------------------ setup
    def _make_feed(self) -> SimFeed | LiveFeed:
        self.games, self.by_id = [], {}
        if self.settings["data_source"] == "sim":
            return SimFeed(observer=self._record_timeline)
        return LiveFeed(self.cfg, self.kalshi)

    def _void_orphans(self) -> None:
        """Simulated games do not survive a restart or reset; void positions left on them."""
        for row in self.db.query("SELECT * FROM positions WHERE status='open' AND simulated=1"):
            if row["game_id"] not in self.by_id:
                self.db.update(
                    "positions",
                    row["id"],
                    {"status": "closed", "exit_price": row["entry_price"], "closed_at": now_iso(),
                     "pnl": -row["fees"], "exit_reason": "manual"},
                )

    @property
    def book(self) -> str:
        if self.settings["trading_mode"] == "live":
            return "live"
        return "sim" if self.settings["data_source"] == "sim" else "paper"

    @staticmethod
    def _book_clause(book: str) -> str:
        if book == "live":
            return "mode='live'"
        return f"mode='paper' AND simulated={1 if book == 'sim' else 0}"

    # ------------------------------------------------------------------- loop
    async def run(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except Exception:
                log.exception("engine tick failed")
            interval = 1.0 if self.settings["data_source"] == "sim" else 2.0
            await asyncio.sleep(max(0.05, interval - (time.monotonic() - started)))

    async def tick(self) -> None:
        now = time.monotonic()
        real_dt = min(now - self._last_real, 5.0)
        self._last_real = now
        if isinstance(self.feed, SimFeed):
            self.games = self.feed.step(real_dt * float(self.settings["sim_speed"]))
        else:
            self.games = await self.feed.refresh()
        self.by_id = {g.id: g for g in self.games}
        for game in self.games:
            refresh_game(game)
            self._record_timeline(game)

        self.observer.observe(self.games)  # quarter markets: watched, never traded by the agent
        await self._settle_finished()
        if self.settings["agent_enabled"]:
            await self._manage_exits()
            await self._scan_entries()
        if self.book == "live" and now - self._live_balance_at > 15:
            await self._refresh_live_balance()

        self.ticks += 1
        self.last_tick = now_iso()
        await self.hub.publish("games", [g.to_dict() for g in self.games])
        await self.hub.publish("positions", self.positions_api())
        await self.hub.publish("account", self.account())
        self._publish_state_if_changed()
        if now - self._last_equity_at > 60:
            self._snapshot_equity()

    def _record_timeline(self, game: Game) -> None:
        if game.state == "pre":
            return
        if game.id not in self.by_id or (game.projection is None and game.state != "final"):
            # A practice game being played forward before it joins the slate: nothing else
            # refreshes its model, so do it here or the chart would draw a stale projection.
            refresh_game(game)
        self._record_quarters(game)
        points = self.timelines.setdefault(game.id, [])
        t = round(game.elapsed)
        if points and (t - points[-1]["t"] < 20) and game.state != "final":
            return
        if points and points[-1]["t"] == t:
            return
        proj = game.projection
        mean = proj.mean if proj else float(game.total)
        sd = proj.sd if proj else 0.0
        fd = game.fanduel
        points.append(
            {
                "t": t,
                "total": game.total,
                "projected": round(mean, 1),
                "lo": round(max(game.total, mean - sd), 1),
                "hi": round(mean + sd, 1),
                "line": fd.total_line if fd and (fd.live or game.state == "pre") else game.pregame_total,
            }
        )
        if len(self.timelines) > 40:
            for gid in [g for g in self.timelines if g not in self.by_id and g != game.id][:10]:
                self.timelines.pop(gid, None)
                self.quarter_timelines.pop(gid, None)

    def _record_quarters(self, game: Game) -> None:
        """Per-quarter chart points: the quarter's total and margin, the model's view, and Kalshi's line."""
        books = self.quarter_timelines.setdefault(game.id, {})
        for view in game.quarter_view:
            seg, status = view["segment"], view["status"]
            if status == "upcoming":
                continue
            points = books.setdefault(seg, [])
            if status == "final" and (not points or points[-1]["t"] == QUARTER_SECONDS):
                continue  # finished before we started watching, or already closed out
            t = QUARTER_SECONDS if status == "final" else round(QUARTER_SECONDS - view["seconds_remaining"])
            if points and t - points[-1]["t"] < 10 and status != "final":
                continue
            total = view["home_points"] + view["away_points"]
            margin = view["home_points"] - view["away_points"]
            proj = view["projection"]
            mean, sd = (proj["total_mean"], proj["total_sd"]) if proj else (float(total), 0.0)
            m_mean, m_sd = (proj["margin_mean"], proj["margin_sd"]) if proj else (float(margin), 0.0)
            markets = game.quarter_markets.get(seg, {})
            points.append(
                {
                    "t": t,
                    "total": total,
                    "projected": round(mean, 1),
                    "lo": round(max(total, mean - sd), 1),
                    "hi": round(mean + sd, 1),
                    "line": implied_quarter_total(markets.get("total", [])),
                    "margin": margin,
                    "m_projected": round(m_mean, 1),
                    "m_lo": round(m_mean - m_sd, 1),
                    "m_hi": round(m_mean + m_sd, 1),
                    "m_line": implied_margin(markets.get("spread", []), game.home.abbr),
                }
            )

    # ---------------------------------------------------------------- reading
    def open_rows(self, agent_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM positions WHERE status='open' AND training=0"
        if agent_only:
            sql += " AND opened_by='agent'"
        return self.db.query(sql + " ORDER BY id")

    def _mark(self, row: dict[str, Any]) -> tuple[int, Optional[Game], Optional[Rung]]:
        game = self.by_id.get(row["game_id"])
        rung = game.rung(row["ticker"]) if game else None
        value = game.settle_value(row["segment"], row["kind"], row["team"]) if game else None
        if value is not None:
            return (100 if self._won(row, value) else 0), game, rung
        bid = rung.bid(row["side"]) if rung else None
        if bid is not None:
            self._marks[row["id"]] = bid
        return self._marks.get(row["id"], row["entry_price"]), game, rung

    @staticmethod
    def _won(row: dict[str, Any], value: float) -> bool:
        """Did this position's side win, given the number its market settled on?

        Above the strike the YES side ("over") wins, below it the NO side ("under").
        """
        return (value < row["strike"]) == (row["side"] == "under")

    @staticmethod
    def _label(row: dict[str, Any]) -> str:
        return row.get("label") or f"{'Under' if row['side'] == 'under' else 'Over'} {row['strike']:g}"

    def positions_api(self) -> list[dict[str, Any]]:
        out = []
        for row in self.open_rows():
            mark, game, rung = self._mark(row)
            value = row["contracts"] * mark / 100.0
            out.append(
                {
                    "id": row["id"],
                    "game_id": row["game_id"],
                    "game_label": row["game_label"],
                    "ticker": row["ticker"],
                    "segment": row["segment"],
                    "kind": row["kind"],
                    "team": row["team"],
                    "label": self._label(row),
                    "strike": row["strike"],
                    "side": row["side"],
                    "contracts": row["contracts"],
                    "entry_price": row["entry_price"],
                    "mark_price": mark,
                    "cost": round(row["cost"], 2),
                    "value": round(value, 2),
                    "pnl": round(value - row["cost"], 2),
                    "max_profit": round(row["contracts"] - row["cost"], 2),
                    "p_win": round(position_p_win(row["side"], rung), 4) if rung else row["p_win_entry"],
                    "p_win_entry": row["p_win_entry"],
                    "opened_at": row["opened_at"],
                    "opened_by": row["opened_by"],
                    "mode": row["mode"],
                    "simulated": row["simulated"],
                    "strategy_id": row["strategy_id"],
                    "exit_profile": row["exit_profile"],
                    "risk": {"level": game.risk.level, "flags": game.risk.flags} if game else {"level": "low", "flags": []},
                }
            )
        return out

    @staticmethod
    def trade_api(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "game_id": row["game_id"],
            "game_label": row["game_label"],
            "ticker": row["ticker"],
            "segment": row["segment"],
            "kind": row["kind"],
            "team": row["team"],
            "label": Engine._label(row),
            "strike": row["strike"],
            "side": row["side"],
            "contracts": row["contracts"],
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "cost": round(row["cost"], 2),
            "pnl": round(row["pnl"] or 0.0, 2),
            "opened_at": row["opened_at"],
            "closed_at": row["closed_at"],
            "opened_by": row["opened_by"],
            "mode": row["mode"],
            "simulated": row["simulated"],
            "strategy_id": row["strategy_id"],
            "exit_reason": row["exit_reason"],
            "counterfactual_pnl": None if row["counterfactual_pnl"] is None else round(row["counterfactual_pnl"], 2),
            "exit_verdict": row["exit_verdict"],
            "final_total": row["final_total"],
        }

    def trades_api(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM positions WHERE status='closed' AND training=0 ORDER BY closed_at DESC, id DESC LIMIT ?",
            [limit],
        )
        return [self.trade_api(r) for r in rows]

    def account(self) -> dict[str, Any]:
        book = self.book
        clause = self._book_clause(book)
        closed = self.db.one(
            f"SELECT COALESCE(SUM(pnl),0) pnl, COALESCE(SUM(pnl>0),0) wins, COALESCE(SUM(pnl<=0),0) losses "
            f"FROM positions WHERE status='closed' AND training=0 AND {clause}"
        )
        today = self.db.one(
            f"SELECT COALESCE(SUM(pnl),0) pnl FROM positions WHERE status='closed' AND training=0 AND {clause} "
            "AND date(closed_at, 'localtime') = date('now', 'localtime')"
        )
        open_rows = [r for r in self.open_rows() if self._row_book(r) == book]
        exposure = sum(r["cost"] for r in open_rows)
        value = sum(r["contracts"] * self._mark(r)[0] / 100.0 for r in open_rows)
        if book == "live":
            cash = self._live_balance["cash"]
            equity = cash + (self._live_balance["portfolio_value"] or value)
        else:
            cash = self.cfg.paper_starting_cash + closed["pnl"] - exposure
            equity = cash + value
        return {
            "cash": round(cash, 2),
            "equity": round(equity, 2),
            "exposure": round(exposure, 2),
            "pnl_today": round(today["pnl"] + (value - exposure), 2),
            "pnl_total": round(closed["pnl"], 2),
            "wins": int(closed["wins"]),
            "losses": int(closed["losses"]),
            "open_positions": len(open_rows),
        }

    @staticmethod
    def _row_book(row: dict[str, Any]) -> str:
        if row["mode"] == "live":
            return "live"
        return "sim" if row["simulated"] else "paper"

    def health(self) -> dict[str, Any]:
        return {
            "kalshi_keys": self.cfg.has_kalshi_keys,
            "kalshi_env": self.cfg.env,
            "anthropic": bool(self.brain and self.brain.available),
            "odds_api": self.cfg.has_odds,
            "feeds": self.feed.status,
        }

    def agent_status(self) -> dict[str, Any]:
        open_n = len(self.open_rows(agent_only=True))
        p = self.playbook.params(Q4_UNDER)
        in_window = [
            g for g in self.games
            if g.in_fourth and p["min_minutes_left"] <= g.minutes_left <= p["max_minutes_left"]
        ]
        live = [g for g in self.games if g.state == "live"]
        if not self.settings["agent_enabled"]:
            state, focus = "paused", "Paused. Open positions are not being managed."
        elif time.monotonic() - self._acted_at < 4:
            state, focus = "acting", "Placing an order"
        elif open_n or in_window:
            state = "watching"
            parts = []
            if open_n:
                parts.append(f"managing {open_n} open position{'s' if open_n != 1 else ''}")
            if in_window:
                parts.append("scanning " + ", ".join(g.label for g in in_window[:3]))
            focus = " · ".join(parts)
            focus = focus[0].upper() + focus[1:]
        elif live:
            nxt = min(live, key=lambda g: g.seconds_remaining)
            state, focus = "idle", f"Waiting for a fourth quarter. Closest: {nxt.label}, Q{nxt.period} {nxt.clock}"
        else:
            state, focus = "idle", "No live games right now"
        return {"state": state, "last_tick": self.last_tick, "focus": focus, "ticks": self.ticks}

    def state(self) -> dict[str, Any]:
        return {"settings": self.settings, "health": self.health(), "agent": self.agent_status(), "account": self.account()}

    def _publish_state_if_changed(self) -> None:
        agent = self.agent_status()
        sig = repr((self.settings, agent["state"], agent["focus"], self.health()["feeds"]))
        if sig != self._last_state_sig or self.ticks % 5 == 0:
            self._last_state_sig = sig
            self.hub.emit("state", self.state())

    def _snapshot_equity(self) -> None:
        self._last_equity_at = time.monotonic()
        equity = self.account()["equity"]
        last = self.db.one("SELECT equity FROM equity WHERE book=? ORDER BY id DESC LIMIT 1", [self.book])
        if last is None or abs(last["equity"] - equity) >= 0.01:
            self.db.insert("equity", {"ts": now_iso(), "book": self.book, "equity": equity})

    async def _refresh_live_balance(self) -> None:
        self._live_balance_at = time.monotonic()
        try:
            self._live_balance = await self.kalshi.balance()
        except Exception as exc:
            log.warning("Kalshi balance failed: %s", exc)

    # --------------------------------------------------------------- settings
    async def update_settings(self, patch: dict[str, Any]) -> None:
        new = {**self.settings, **{k: v for k, v in patch.items() if k in DEFAULT_SETTINGS and v is not None}}
        going_live = new["trading_mode"] == "live" and self.settings["trading_mode"] != "live"
        if new["trading_mode"] == "live":
            if not self.cfg.has_kalshi_keys:
                raise TradeError("Live trading needs KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PEM in .env.")
            if new["data_source"] != "live":
                raise TradeError("Live trading only works on live data. Switch the data source to live first.")
        if going_live:
            try:
                self._live_balance = await self.kalshi.balance()
                self._live_balance_at = time.monotonic()
            except Exception as exc:
                raise TradeError(f"Could not reach your Kalshi account, staying in paper mode. {exc}") from exc
            new["agent_enabled"] = False  # arming real money never also starts the agent
            self.hub.toast("warn", "Live trading armed", "The agent is paused. Press start when you want it trading real money.")
        source_changed = new["data_source"] != self.settings["data_source"]
        new["sim_speed"] = min(max(float(new["sim_speed"]), 1.0), 60.0)
        self.settings = new
        self.db.set("settings", new)
        self.learner.env = "sim" if new["data_source"] == "sim" else "real"
        if source_changed:
            await self.feed.aclose()
            self.timelines.clear()
            self.quarter_timelines.clear()
            self._cooldown.clear()
            self._last_skip.clear()
            self.feed = self._make_feed()
            self._void_orphans()
        self.hub.emit("state", self.state())

    async def reset_sim(self) -> None:
        if isinstance(self.feed, SimFeed):
            self.timelines.clear()
            self.quarter_timelines.clear()
            self.games, self.by_id = [], {}
            self.feed.reset()
            self._cooldown.clear()
            self._last_skip.clear()
            self._void_orphans()

    # --------------------------------------------------------------- decisions
    def decide(
        self,
        kind: str,
        headline: str,
        reasoning: str,
        *,
        game: Optional[Game] = None,
        ticker: Optional[str] = None,
        confidence: float = 0.5,
        data: Optional[dict[str, Any]] = None,
        source: str = "rules",
        memory_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        row = {
            "ts": now_iso(),
            "game_id": game.id if game else None,
            "game_label": game.label if game else None,
            "kind": kind,
            "ticker": ticker,
            "headline": headline,
            "reasoning": reasoning,
            "confidence": round(confidence, 3),
            "data": data or {},
            "source": source,
            "memory_ids": memory_ids or [],
        }
        row["id"] = self.db.insert("decisions", row)
        self.hub.emit("decision", row)
        return row

    def _skip(self, game: Game, skip: Skip, source: str = "rules") -> None:
        seen = self._last_skip.setdefault(game.id, set())
        if skip.code in seen:
            return  # say each kind of pass once per game, not every tick
        seen.add(skip.code)
        self.decide("skip", skip.headline, skip.reasoning, game=game, data=skip.data, source=source, confidence=0.6)

    # ----------------------------------------------------------------- orders
    async def _buy(self, rung: Rung, side: str, contracts: int, limit: int, mode: str) -> tuple[int, int, float]:
        """Returns (filled contracts, fill price in cents, fees in dollars)."""
        if mode == "live":
            try:
                fill = await self.kalshi.place_order(rung.ticker, side, "buy", contracts, limit)
            except KalshiError as exc:
                raise TradeError(str(exc)) from exc
            if fill["filled"] <= 0:
                raise TradeError(f"Kalshi did not fill any contracts at {limit}c.")
            price = round(fill["price"])
            return fill["filled"], price, fill["fees"] or kalshi_fee(fill["filled"], price)
        ask = rung.ask(side)
        if ask is None:
            raise TradeError("No offer on that side right now.")
        if ask > limit:
            raise TradeError(f"The ask moved to {ask}c, above your {limit}c limit.")
        return contracts, ask, kalshi_fee(contracts, ask)

    async def _sell(self, row: dict[str, Any], rung: Optional[Rung], limit: Optional[int]) -> tuple[int, int, float]:
        bid = rung.bid(row["side"]) if rung else None
        if bid is None:
            raise TradeError("No bid to sell into right now.")
        price = bid if limit is None else limit
        if row["mode"] == "live":
            try:
                fill = await self.kalshi.place_order(row["ticker"], row["side"], "sell", row["contracts"], price)
            except KalshiError as exc:
                raise TradeError(str(exc)) from exc
            if fill["filled"] <= 0:
                raise TradeError(f"Kalshi did not fill the sell at {price}c.")
            px = round(fill["price"])
            return fill["filled"], px, fill["fees"] or kalshi_fee(fill["filled"], px)
        return row["contracts"], bid, kalshi_fee(row["contracts"], bid)

    async def open_position(
        self,
        game: Game,
        rung: Rung,
        side: str,
        contracts: int,
        limit: int,
        *,
        opened_by: str,
        strategy_id: Optional[str] = None,
        exit_profile: Optional[str] = None,
        arm: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
        memory_ids: Optional[list[int]] = None,
    ) -> dict[str, Any]:
        if contracts <= 0:
            raise TradeError("Order size is zero.")
        if game.state != "live" and game.state != "pre":
            raise TradeError("That game is over.")
        if game.settle_value(rung.segment, rung.kind, rung.team) is not None:
            raise TradeError("That market has already settled.")
        mode = self.settings["trading_mode"]
        if mode == "live" and game.simulated:
            raise TradeError("Cannot send live orders on simulated games.")
        if mode == "paper":
            ask = rung.ask(side) or limit
            needed = contracts * ask / 100.0 + kalshi_fee(contracts, ask)
            if needed > self.account()["cash"] + 1e-6:
                raise TradeError(f"Not enough paper cash: need ${needed:,.2f}.")
        filled, price, fees = await self._buy(rung, side, contracts, limit, mode)
        row_id = self.db.insert(
            "positions",
            {
                "game_id": game.id,
                "game_label": game.label,
                "ticker": rung.ticker,
                "strike": rung.strike,
                "side": side,
                "segment": rung.segment,
                "kind": rung.kind,
                "team": rung.team,
                "label": rung.position_label(side),
                "contracts": filled,
                "entry_price": price,
                "cost": round(filled * price / 100.0 + fees, 2),
                "fees": fees,
                "opened_at": now_iso(),
                "opened_by": opened_by,
                "mode": mode,
                "simulated": game.simulated,
                "strategy_id": strategy_id,
                "exit_profile": exit_profile,
                "arm_key": arm,
                "p_win_entry": round(position_p_win(side, rung), 4),
                "context": context or {},
                "memory_ids": memory_ids or [],
            },
        )
        self._acted_at = time.monotonic()
        position = next(p for p in self.positions_api() if p["id"] == row_id)
        self.hub.emit("positions", self.positions_api())
        self.hub.toast(
            "success",
            f"Bought {game.label} {rung.position_label(side)}",
            f"{filled} contracts at {price}c · ${position['cost']:,.2f} to win ${position['max_profit']:,.2f}"
            + (" · LIVE" if mode == "live" else ""),
        )
        return position

    async def close_position(self, position_id: int, reason: str = "manual", limit: Optional[int] = None) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM positions WHERE id=? AND status='open'", [position_id])
        if row is None:
            raise TradeError("That position is not open.")
        game = self.by_id.get(row["game_id"])
        rung = game.rung(row["ticker"]) if game else None
        filled, price, fees = await self._sell(row, rung, limit)
        if filled < row["contracts"]:
            # Partial fill: keep the remainder open and book the filled slice.
            keep = row["contracts"] - filled
            share = filled / row["contracts"]
            self.db.update("positions", row["id"], {"contracts": keep, "cost": round(row["cost"] * (1 - share), 2), "fees": round(row["fees"] * (1 - share), 2)})
            sold = {k: v for k, v in row.items() if k != "id"}
            sold.update(contracts=filled, cost=round(row["cost"] * share, 2), fees=round(row["fees"] * share, 2))
            row = {**sold, "id": self.db.insert("positions", sold)}
        return self._finish(row, price, reason, exit_fees=fees, game=game)

    def _finish(
        self,
        row: dict[str, Any],
        exit_price: int,
        reason: str,
        *,
        exit_fees: float = 0.0,
        game: Optional[Game] = None,
        value: Optional[float] = None,
    ) -> dict[str, Any]:
        """Book a closed position and feed the result to the learner and memory."""
        proceeds = row["contracts"] * exit_price / 100.0 - exit_fees
        pnl = round(proceeds - row["cost"], 2)
        fields: dict[str, Any] = {
            "status": "closed",
            "exit_price": exit_price,
            "closed_at": now_iso(),
            "pnl": pnl,
            "exit_reason": reason,
            "fees": round(row["fees"] + exit_fees, 2),
        }
        if reason in ("settled_win", "settled_loss") and game is not None:
            fields["final_total"] = value if value is not None else game.total
            fields["counterfactual_pnl"] = pnl
        self.db.update("positions", row["id"], fields)
        row = {**row, **fields}
        self._marks.pop(row["id"], None)
        self._hold_noted.pop(row["id"], None)

        ret = pnl / row["cost"] if row["cost"] else 0.0
        if row["opened_by"] == "agent":
            self.learner.record(
                arm=row["arm_key"],
                exit_profile=row["exit_profile"],
                ret=ret,
                won=reason == "settled_win",
                p_model=row["p_win_entry"],
                price_cents=row["entry_price"],
                simulated=row["simulated"],
            )
            self.memory.reinforce(row["memory_ids"], positive=pnl > 0)
        self._remember_trade(row)
        trade = self.trade_api(row)
        self.hub.emit("trade", trade)
        self.hub.emit("positions", self.positions_api())
        self.hub.emit("account", self.account())
        self._snapshot_equity()
        verb = {"settled_win": "Won", "settled_loss": "Lost", "risk_exit": "Risk exit", "stop_loss": "Stopped out",
                "take_profit": "Took profit", "manual": "Closed"}[reason]
        self.hub.toast("success" if pnl > 0 else "warn", f"{verb}: {row['game_label']} {self._label(row)}", f"{pnl:+,.2f} at {exit_price}c")
        return trade

    # ----------------------------------------------------------------- memory
    def _tags_for(self, row: dict[str, Any]) -> list[str]:
        ctx = row["context"] or {}
        away, _, home = row["game_label"].partition(" @ ")
        pace_gap = (ctx.get("pace") or 0) - (ctx.get("pregame_total") or ctx.get("pace") or 0)
        if not row["arm_key"]:
            tags = ["nba", home.lower(), away.lower(), "manual", row["kind"]]
            return tags + (["quarter", row["segment"]] if row["segment"] != "game" else [])
        return situation_tags(arm=row["arm_key"], home=home, away=away, p_ot=ctx.get("p_ot") or 0.0, pace_gap=pace_gap)

    def _describe(self, row: dict[str, Any]) -> str:
        ctx = row["context"] or {}
        if ctx.get("buffer") is not None:
            where = (
                f"entered Q4 {ctx['clock']} left, total {ctx['total']}, {ctx['margin']}-pt game, "
                f"line {ctx['line']:g}, {ctx['buffer']:g} pts of cushion"
            )
        else:
            where = f"your trade, {ctx['when']}" if ctx.get("when") else "your trade"
        return f"{row['game_label']} {self._label(row)} at {row['entry_price']}c x{row['contracts']} ({where})"

    def _remember_trade(self, row: dict[str, Any]) -> None:
        outcome = {
            "settled_win": "held until it settled and won",
            "settled_loss": "held until it settled and lost",
            "risk_exit": f"sold at {row['exit_price']}c when risk rose",
            "stop_loss": f"stopped out at {row['exit_price']}c",
            "take_profit": f"took profit at {row['exit_price']}c",
            "manual": f"closed by hand at {row['exit_price']}c",
        }[row["exit_reason"]]
        tags = self._tags_for(row)
        episode = self.memory.add(
            "episode",
            f"{self._describe(row)}: {outcome}, {row['pnl']:+,.2f}.",
            tags=tags + [row["exit_reason"]],
            importance=0.35 if row["pnl"] > 0 else 0.6,
            simulated=row["simulated"],
            trade_id=row["id"],
        )
        self.hub.emit("memory", episode)
        if row["exit_reason"] == "settled_loss" and row["opened_by"] == "agent":
            self._lesson(
                row,
                f"Full loss of ${-row['pnl']:,.2f}: {self._describe(row)} finished at {row['final_total']}. "
                f"No exit fired before it broke. Be warier of this spot or tighten the exit.",
                importance=0.9,
            )

    def _lesson(self, row: dict[str, Any], fallback: str, importance: float, claude_only: bool = False) -> None:
        """Store a lesson: Claude's reflection when available, otherwise the plain facts.

        With claude_only the plain facts are not stored on their own.
        """
        tags = self._tags_for(row)
        use_claude = bool(self.brain and self.brain.available) and not row["simulated"]
        if claude_only and not use_claude:
            return

        async def work() -> None:
            text, extra_tags, weight = fallback, [], importance
            if use_claude:
                try:
                    reflection = await self.brain.reflect(row, fallback)
                    text, extra_tags, weight = reflection["lesson"], reflection["tags"], reflection["importance"]
                except Exception as exc:
                    log.warning("reflection failed: %s", exc)
            mem = self.memory.add("lesson", text, tags=tags + extra_tags, importance=weight, simulated=row["simulated"], trade_id=row["id"])
            await self.hub.publish("memory", mem)

        try:
            asyncio.get_running_loop().create_task(work())
        except RuntimeError:
            self.memory.add("lesson", fallback, tags=tags, importance=importance, simulated=row["simulated"], trade_id=row["id"])

    # ------------------------------------------------------------- settlement
    async def _settle_finished(self) -> None:
        """Settle anything whose market has finished: games at the final, quarters when they end."""
        for row in self.open_rows():
            game = self.by_id.get(row["game_id"])
            value = game.settle_value(row["segment"], row["kind"], row["team"]) if game else None
            if value is None:
                continue
            won = self._won(row, value)
            self._finish(row, 100 if won else 0, "settled_win" if won else "settled_loss", game=game, value=value)
        if self.by_id:
            marks = ",".join("?" * len(self.by_id))
            ungraded = self.db.query(
                f"SELECT * FROM positions WHERE status='closed' AND training=0 AND counterfactual_pnl IS NULL AND game_id IN ({marks})",
                list(self.by_id),
            )
            for row in ungraded:
                value = self.by_id[row["game_id"]].settle_value(row["segment"], row["kind"], row["team"])
                if value is not None:
                    self._grade_exit(row, value)
        finals = [g.id for g in self.games if g.state == "final"]
        for gid in finals:
            self._cooldown.discard(gid)
            self._last_skip.pop(gid, None)

    def _grade_exit(self, row: dict[str, Any], final_total: float) -> None:
        """Once the market has settled, compare an early exit with what holding would have paid."""
        would_win = self._won(row, final_total)
        held = round(row["contracts"] * (1.0 if would_win else 0.0) - (row["cost"]), 2)
        verdict = "saved" if row["pnl"] > held else "shaken_out"
        self.db.update("positions", row["id"], {"counterfactual_pnl": held, "exit_verdict": verdict, "final_total": final_total})
        row = {**row, "counterfactual_pnl": held, "exit_verdict": verdict, "final_total": final_total}
        self.hub.emit("trade", self.trade_api(row))
        if row["opened_by"] != "agent" or row["exit_reason"] == "manual":
            return
        self.learner.record_exit_verdict(row["exit_profile"], verdict)
        if would_win:
            self.learner.credit_win(row["arm_key"], row["exit_profile"], row["simulated"])
        self._update_exit_scorecard(row["simulated"])
        # One exit proves little either way (a sound exit at 85% "sells a winner"
        # 85% of the time), so the standing lesson is the running scorecard.
        # Claude, when connected, still gets to reflect on the individual case.
        if verdict == "saved":
            facts = (
                f"Exit avoided a loss: {self._describe(row)}. Sold at {row['exit_price']}c for {row['pnl']:+,.2f}; the "
                f"game finished at {final_total}, so holding would have lost ${-held:,.2f}."
            )
        else:
            facts = (
                f"Exit sold an eventual winner: {self._describe(row)}. Sold at {row['exit_price']}c for {row['pnl']:+,.2f}; "
                f"the game finished at {final_total} and holding would have paid {held:+,.2f}."
            )
        self._lesson(row, facts, importance=0.6, claude_only=True)

    def _update_exit_scorecard(self, simulated: bool) -> None:
        """Keep one running lesson that says, in dollars, whether exiting early is paying."""
        rows = self.db.query(
            "SELECT exit_profile, exit_verdict, pnl, counterfactual_pnl FROM positions WHERE status='closed' AND training=0 "
            "AND opened_by='agent' AND exit_verdict IS NOT NULL AND simulated=?",
            [int(simulated)],
        )
        if not rows:
            return
        saved = [r for r in rows if r["exit_verdict"] == "saved"]
        sold = [r for r in rows if r["exit_verdict"] == "shaken_out"]
        net = sum(r["pnl"] - r["counterfactual_pnl"] for r in rows)
        by_style = []
        for style in EXIT_PROFILES:
            mine = [r for r in rows if r["exit_profile"] == style]
            if mine:
                by_style.append(f"{style} {sum(r['pnl'] - r['counterfactual_pnl'] for r in mine):+,.0f} over {len(mine)}")
        text = (
            f"Exit scorecard ({'simulator' if simulated else 'real markets'}): {len(rows)} early exits so far. "
            f"{len(saved)} avoided a full loss, saving ${sum(r['pnl'] - r['counterfactual_pnl'] for r in saved):,.0f}; "
            f"{len(sold)} sold a position that went on to win, giving up ${-sum(r['pnl'] - r['counterfactual_pnl'] for r in sold):,.0f}. "
            f"Net versus always holding: {net:+,.0f} dollars. By exit style: {'; '.join(by_style)}."
        )
        tags = ["nba", "q4_under", "exits", "scorecard"]
        existing = next(
            (m for m in self.memory.list(kind="lesson", limit=500) if "scorecard" in m["tags"] and m["simulated"] == simulated),
            None,
        )
        if existing:
            mem = self.memory.update(existing["id"], {"text": text})
        else:
            mem = self.memory.add("lesson", text, tags=tags, importance=0.7, simulated=simulated)
        self.hub.emit("memory", mem)

    # ------------------------------------------------------------------ exits
    async def _manage_exits(self) -> None:
        p = self.playbook.params(Q4_UNDER)
        for row in self.open_rows(agent_only=True):
            game = self.by_id.get(row["game_id"])
            rung = game.rung(row["ticker"]) if game else None
            if not game or not rung or game.state != "live":
                continue
            signal = exit_signal(
                side=row["side"], strike=row["strike"], entry_price=row["entry_price"],
                game=game, rung=rung, p=p, profile=row["exit_profile"] or "balanced",
            )
            if signal is None:
                self._note_hold(row, game, rung, p)
                continue
            try:
                trade = await self.close_position(row["id"], reason=signal.reason)
            except TradeError as exc:
                log.warning("exit failed for %s: %s", row["ticker"], exc)
                continue
            self._cooldown.add(game.id)
            self._acted_at = time.monotonic()
            self.decide(
                "exit", signal.headline, signal.reasoning, game=game, ticker=row["ticker"],
                confidence=0.8, data={**signal.data, "pnl": f"{trade['pnl']:+.2f}"}, source="model",
                memory_ids=row["memory_ids"],
            )

    def _note_hold(self, row: dict[str, Any], game: Game, rung: Rung, p: dict[str, float]) -> None:
        """Say something once when a held position's game turns risky but no exit has fired."""
        level = game.risk.level
        if level != "high" or self._hold_noted.get(row["id"]) == level:
            if level == "low":
                self._hold_noted.pop(row["id"], None)
            return
        self._hold_noted[row["id"]] = level
        p_win = position_p_win(row["side"], rung)
        self.decide(
            "hold",
            f"Holding {game.label} {row['side']} {row['strike']:g}, watching closely",
            f"{_sentence('; '.join(game.risk.flags) or 'risk is rising')}. Win chance is still {p_win:.0%} against a "
            f"{p['min_p_win']:g}% floor and the bid is {rung.bid(row['side'])}c versus a {row['entry_price']}c entry, "
            f"so no exit yet.",
            game=game, ticker=row["ticker"], confidence=p_win, source="model",
            data={"win_chance": f"{p_win:.0%}", "bid": f"{rung.bid(row['side'])}c", "risk": level},
        )

    # ---------------------------------------------------------------- entries
    def _limit_block(self, stake: float) -> Optional[tuple[str, str]]:
        """(which limit, message) if a risk limit forbids another entry, else None."""
        acct = self.account()
        s = self.settings
        if acct["open_positions"] >= s["max_open_positions"]:
            return "positions", f"Already at the limit of {s['max_open_positions']} open positions."
        if acct["pnl_today"] <= -abs(s["max_daily_loss"]):
            return "daily_loss", f"Down ${-acct['pnl_today']:,.2f} today, past the ${s['max_daily_loss']:,.0f} daily loss limit. Done for the day."
        if acct["exposure"] + stake > s["max_total_exposure"] + 1e-6:
            return "exposure", f"${acct['exposure']:,.0f} already at risk; another ${stake:,.0f} would pass the ${s['max_total_exposure']:,.0f} exposure cap."
        return None

    async def _scan_entries(self) -> None:
        if not self.playbook.enabled(Q4_UNDER):
            return
        p = self.playbook.params(Q4_UNDER)
        # A quarter bet of yours does not stop the agent making its own full-game play.
        held = {r["game_id"] for r in self.open_rows() if r["segment"] == "game"}
        for game in self.games:
            if game.id in held or game.id in self._reviewing or game.id in self._cooldown:
                continue
            if self.settings["trading_mode"] == "live" and game.simulated:
                continue
            if time.monotonic() < self._vetoed.get(game.id, 0.0):
                continue
            found = find_entries(game, p)
            if found is None:
                continue
            if isinstance(found, Skip):
                self._skip(game, found)
                continue
            plan = self._plan_entry(game, found, p)
            if plan is None:
                continue
            # Claude reviews real-market entries only: no point paying to second-guess invented games.
            if self.settings["claude_review"] and self.brain and self.brain.available and not game.simulated:
                self._reviewing.add(game.id)
                asyncio.get_running_loop().create_task(self._review_then_enter(game.id, plan))
            else:
                await self._enter(game, plan)
                held.add(game.id)

    def _plan_entry(self, game: Game, candidates: list[Candidate], p: dict[str, float]) -> Optional[dict[str, Any]]:
        views = [(c, self.learner.entry_view(c.arm, c.p_model, c.price)) for c in candidates]
        # The playbook sets how much negative model edge is tolerated; the learner
        # gets the same tolerance, so it only vetoes a spot its own results condemn.
        floor = min(0.0, p["min_edge"] / 100.0) - 0.005
        viable = [(c, v) for c, v in views if self.learner.allows(v, floor)]
        if not viable:
            c, v = max(views, key=lambda cv: cv[1]["ev"])
            self._skip(
                game,
                Skip(
                    "learned_avoid",
                    f"Pass on {game.label}: this spot has been losing",
                    f"Under {c.rung.strike:g} at {c.price}c passes the playbook ({c.edge * 100:+.1f}% model edge), but in "
                    f"this situation ({c.arm.replace('|', ', ')}) my own results average {v['mean_return']:+.1%} per trade "
                    f"over {v['n']:.0f} {'simulated' if game.simulated else 'real'} trades. Blended with the model that is {v['ev']:+.1%} expected, so I am staying out.",
                    {"spot": c.arm, "trades": int(v["n"]), "learned_ev": f"{v['ev']:+.1%}"},
                ),
                source="model",
            )
            return None
        cand, view = max(viable, key=lambda cv: self.learner.sample_ev(cv[0].arm, cv[0].p_model, cv[0].price))
        stake = min(p["stake"], float(self.settings["max_stake_per_trade"]))
        if self.book != "live":
            stake = min(stake, self.account()["cash"])
        block = self._limit_block(stake)
        if block:
            which, message = block
            if self._limit_noted != which:  # alert once per limit, not every time the dollar figure moves
                self._limit_noted = which
                self.hub.toast("warn", "Risk limit reached", message)
            self._skip(game, Skip("limit", f"Pass on {game.label}: risk limit", message))
            return None
        self._limit_noted = ""
        contracts, cost, _ = size_order(stake, cand.price)
        if contracts <= 0:
            return None
        proj = game.projection
        pace_gap = (proj.pace - (game.pregame_total or proj.pace)) if proj else 0.0
        tags = situation_tags(arm=cand.arm, home=game.home.abbr, away=game.away.abbr, p_ot=proj.p_ot if proj else 0.0, pace_gap=pace_gap)
        memories = self.memory.recall(tags, text=f"{game.label} fourth quarter under total", k=6)
        return {
            "ticker": cand.rung.ticker, "cand": cand, "view": view, "contracts": contracts, "cost": cost,
            "profile": self.learner.choose_exit_profile(), "memories": memories, "tags": tags,
        }

    async def _review_then_enter(self, game_id: str, plan: dict[str, Any]) -> None:
        try:
            game = self.by_id.get(game_id)
            if game is None:
                return
            verdict = await self.brain.review_entry(game, plan, self.playbook.describe())
            game = self.by_id.get(game_id)
            if game is None or game.state != "live":
                return
            cand: Candidate = plan["cand"]
            if verdict and not verdict["approve"]:
                self._vetoed[game_id] = time.monotonic() + 90
                self.decide(
                    "skip", f"Claude passed on {game.label} under {cand.rung.strike:g}", verdict["reason"],
                    game=game, ticker=plan["ticker"], source="claude", confidence=0.7,
                    data={"price": f"{cand.price}c", "edge": f"{cand.edge * 100:+.1f}%"},
                    memory_ids=[m["id"] for m in plan["memories"]],
                )
                return
            # The market moved while Claude was thinking: re-check the rules before acting.
            fresh = find_entries(game, self.playbook.params(Q4_UNDER))
            still = next((c for c in fresh if c.rung.ticker == plan["ticker"]), None) if isinstance(fresh, list) else None
            if still is None or still.price > cand.price + 1:
                return
            plan["cand"] = still
            if verdict:
                mult = min(max(float(verdict.get("size_multiplier", 1.0)), 0.25), 1.0)
                if mult < 1.0:
                    plan["contracts"] = max(1, int(plan["contracts"] * mult))
                plan["claude_reason"] = verdict["reason"]
            if self._limit_block(plan["cost"]) is None:
                await self._enter(game, plan)
        except Exception:
            log.exception("review/enter failed")
        finally:
            self._reviewing.discard(game_id)

    async def _enter(self, game: Game, plan: dict[str, Any]) -> None:
        cand: Candidate = plan["cand"]
        view = plan["view"]
        memory_ids = [m["id"] for m in plan["memories"]]
        try:
            pos = await self.open_position(
                game, cand.rung, "under", plan["contracts"], cand.price,
                opened_by="agent", strategy_id=Q4_UNDER, exit_profile=plan["profile"],
                arm=cand.arm, context=cand.context, memory_ids=memory_ids,
            )
        except TradeError as exc:
            self._skip(game, Skip("order_failed", f"{game.label}: order not placed", str(exc)))
            return
        self._last_skip.pop(game.id, None)
        p = self.playbook.params(Q4_UNDER)
        prof = EXIT_PROFILES[plan["profile"]]
        record = (
            f"My record in this spot: {view['n']:.0f} {'simulated' if game.simulated else 'real'} trades averaging {view['mean_return']:+.1%}."
            if view["n"] else "No history in this spot yet, so going on the model and your playbook."
        )
        recalled = f" Kept in mind: {_clip(plan['memories'][0]['text'], 170)}" if plan["memories"] else ""
        claude = f" Claude: {plan['claude_reason']}" if plan.get("claude_reason") else ""
        self.decide(
            "enter",
            f"Bought {game.label} under {cand.rung.strike:g} at {pos['entry_price']}c",
            f"The {cand.reference_source} is {cand.reference:g} and the total is {game.total} with {game.q4_clock} left in "
            f"a {game.margin}-pt game. Under {cand.rung.strike:g} gives {cand.buffer:g} points of cushion: "
            f"${pos['cost']:,.2f} to win ${pos['max_profit']:,.2f}. Model says {cand.p_model:.1%} against a "
            f"{pos['entry_price']}% break-even ({cand.edge * 100:+.1f}% edge). {record} "
            f"Exit plan ({prof['label'].lower()}): sell if win chance drops under "
            f"{min(97, p['min_p_win'] + prof['p_shift']):g}% or the bid falls {p['stop_loss'] * prof['stop_mult']:g}c."
            f"{recalled}{claude}",
            game=game, ticker=cand.rung.ticker, confidence=view["p_win"],
            source="claude" if plan.get("claude_reason") else "model", memory_ids=memory_ids,
            data={
                "line": cand.reference, "strike": cand.rung.strike, "cushion": f"{cand.buffer:g} pts",
                "price": f"{pos['entry_price']}c", "model": f"{cand.p_model:.1%}", "edge": f"{cand.edge * 100:+.1f}%",
                "stake": f"${pos['cost']:,.0f}", "to_win": f"${pos['max_profit']:,.2f}", "exit": plan["profile"],
            },
        )

    # ------------------------------------------------------------ manual orders
    async def manual_order(self, ticker: str, side: str, contracts: int, price: int) -> dict[str, Any]:
        if side not in ("under", "over"):
            raise TradeError("Side must be 'under' or 'over'.")
        for game in self.games:
            rung = game.rung(ticker)
            if rung:
                pos = await self.open_position(
                    game, rung, side, int(contracts), int(price), opened_by="user", context=self._manual_context(game, rung, side)
                )
                self.decide(
                    "note", f"You bought {game.label} {pos['label']} at {pos['entry_price']}c",
                    "Your order. The agent does not trade quarter markets; it is recording this one and how it ends."
                    if rung.segment != "game" else "Manual order. The agent will not auto-exit positions you open yourself.",
                    game=game, ticker=ticker, source="rules", confidence=pos["p_win"],
                    data={"contracts": pos["contracts"], "cost": f"${pos['cost']:,.2f}"},
                )
                return pos
        raise TradeError(f"No market with ticker {ticker}.")

    @staticmethod
    def _manual_context(game: Game, rung: Rung, side: str) -> dict[str, Any]:
        """What the game looked like when the user placed a trade, for the agent's memory."""
        ctx: dict[str, Any] = {
            "manual": True, "segment": rung.segment, "kind": rung.kind, "team": rung.team,
            "total": game.total, "margin": game.margin, "period": game.period,
            "model_p": round(position_p_win(side, rung), 4),
        }
        if game.state == "pre":
            ctx["when"] = "before tip-off"
        elif rung.segment == "game":
            ctx["when"] = f"Q{game.period} {game.clock}, total {game.total}" if game.period <= 4 else f"OT, total {game.total}"
        else:
            q = int(rung.segment[1])
            home_pts, away_pts = game.quarter_points(q)
            ctx["quarter_points"] = home_pts + away_pts
            ctx["when"] = (
                f"{game.clock} left in Q{q} with {home_pts + away_pts} scored in the quarter"
                if game.quarter_status(q) == "live" else f"before Q{q} started"
            )
        return ctx

    def learning_state(self) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT p_win_entry, strike, side, final_total, pnl, cost, exit_verdict, simulated, training "
            "FROM positions WHERE status='closed' AND segment='game'"
        )
        real = [r for r in rows if not r["training"]]
        buckets = [(0.0, 0.85, "<85%"), (0.85, 0.90, "85-90%"), (0.90, 0.93, "90-93%"), (0.93, 0.96, "93-96%"), (0.96, 1.01, "96%+")]
        calibration = []
        for lo, hi, name in buckets:
            hits = [r for r in rows if r["final_total"] is not None and lo <= r["p_win_entry"] < hi]
            if hits:
                wins = sum(1 for r in hits if (r["final_total"] < r["strike"]) == (r["side"] == "under"))
                calibration.append({
                    "bucket": name, "n": len(hits),
                    "predicted": round(sum(r["p_win_entry"] for r in hits) / len(hits), 4),
                    "actual": round(wins / len(hits), 4),
                })
        wins = [r["pnl"] for r in real if r["pnl"] > 0]
        losses = [r["pnl"] for r in real if r["pnl"] <= 0]
        curve = self.db.query("SELECT ts, equity, book FROM equity WHERE book=? ORDER BY id DESC LIMIT 500", [self.book])
        return {
            "quarters": self.observer.summary(simulated=self.settings["data_source"] == "sim"),
            "arms": self.learner.arms(),
            "exit_arms": self.learner.exit_arms(),
            "calibration": calibration,
            "equity_curve": [{"ts": c["ts"], "equity": c["equity"], "simulated": c["book"] == "sim"} for c in reversed(curve)],
            "totals": {
                "trades": len(real),
                "win_rate": round(len(wins) / len(real), 4) if real else 0.0,
                "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
                "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
                "expectancy": round(sum(r["pnl"] for r in real) / len(real), 2) if real else 0.0,
                "exits_saved": sum(1 for r in real if r["exit_verdict"] == "saved"),
                "exits_shaken": sum(1 for r in real if r["exit_verdict"] == "shaken_out"),
                "sim_episodes": int(self.db.get("sim_episodes", 0)),
            },
        }

    async def aclose(self) -> None:
        await self.feed.aclose()
        await self.kalshi.aclose()


def _sentence(text: str) -> str:
    """Start with a capital without lowering anything else (team codes stay upper case)."""
    return text[:1].upper() + text[1:]


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
