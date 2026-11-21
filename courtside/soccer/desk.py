"""The soccer desk: the board, orders by hand, positions, settlement.

Separate from the NBA engine: its own loop, its own positions table and its own
paper bankroll. It follows the site's trading mode (paper or live) and risk cap per
trade, and places live orders through the same Kalshi client.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional

from ..agent.policy import kalshi_fee
from ..config import Config
from ..db import DB
from ..domain import now_iso
from ..kalshi.client import KalshiError
from .domain import LEAGUE_BY_KEY, LEAGUES, Match, SMarket
from .feed import SoccerFeed

if TYPE_CHECKING:
    from ..agent.engine import Engine

log = logging.getLogger(__name__)


SYNC_EVERY_S = 20.0  # how often live positions are checked against what Kalshi says you hold
SYNC_GRACE_S = 30  # leave positions this fresh alone: Kalshi may not list the fill yet


class SoccerTradeError(Exception):
    pass


def implied_line(markets: list[SMarket]) -> Optional[float]:
    """The goal total Kalshi's prices put at 50/50, interpolated between lines."""
    pts = sorted(
        (m.strike, (m.yes_bid + m.yes_ask) / 200.0)
        for m in markets if m.kind == "total" and m.strike is not None and m.yes_bid and m.yes_ask
    )
    for (lo_x, lo_p), (hi_x, hi_p) in zip(pts, pts[1:]):
        if lo_p >= 0.5 >= hi_p and lo_p != hi_p:
            return round(lo_x + (lo_p - 0.5) / (lo_p - hi_p) * (hi_x - lo_x), 2)
    return None


def market_dict(m: SMarket, match: Match) -> dict[str, Any]:
    return {
        "ticker": m.ticker, "segment": m.segment, "kind": m.kind, "outcome": m.outcome, "strike": m.strike,
        "yes_label": m.label("yes", match), "no_label": m.label("no", match),
        "yes_bid": m.yes_bid, "yes_ask": m.yes_ask, "no_bid": m.no_bid, "no_ask": m.no_ask,
        "volume": m.volume, "p_yes": m.p_yes, "result": m.result,
        "edge_yes": round(m.p_yes - m.yes_ask / 100.0, 4) if m.p_yes is not None and m.yes_ask else None,
        "edge_no": round((1 - m.p_yes) - m.no_ask / 100.0, 4) if m.p_yes is not None and m.no_ask else None,
    }


class SoccerDesk:
    def __init__(self, cfg: Config, db: DB, engine: "Engine"):
        self.cfg = cfg
        self.db = db
        self.engine = engine
        self.feed = SoccerFeed(engine.kalshi)
        self.matches: list[Match] = []
        self.by_id: dict[str, Match] = {}
        self.last_tick: Optional[str] = None
        self._last_sync = 0.0

    @property
    def mode(self) -> str:
        return "live" if self.engine.settings["trading_mode"] == "live" else "paper"

    # --------------------------------------------------------------------- loop
    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("soccer tick failed")
            await asyncio.sleep(2.0)

    async def tick(self) -> None:
        self.matches = await self.feed.refresh()
        self.by_id = {m.id: m for m in self.matches}
        self._settle()
        if self.mode == "live" and time.monotonic() - self._last_sync > SYNC_EVERY_S:
            self._last_sync = time.monotonic()
            try:
                await self.sync_with_kalshi()
            except KalshiError as exc:
                log.warning("soccer: Kalshi position sync failed: %s", exc)
        self.last_tick = now_iso()

    async def aclose(self) -> None:
        await self.feed.aclose()

    # ------------------------------------------------------------------- orders
    def _find(self, ticker: str) -> tuple[Match, SMarket]:
        for match in self.matches:
            market = match.market(ticker)
            if market:
                return match, market
        raise SoccerTradeError(f"No soccer market with ticker {ticker}.")

    async def order(self, ticker: str, side: str, contracts: int, price: int) -> dict[str, Any]:
        if side not in ("yes", "no"):
            raise SoccerTradeError("Side must be 'yes' or 'no'.")
        contracts, price = int(contracts), int(price)
        if contracts < 1 or not 1 <= price <= 99:
            raise SoccerTradeError("Pick at least one contract at a price between 1c and 99c.")
        match, market = self._find(ticker)
        if match.state == "final" or match.settles_yes(market) is not None:
            raise SoccerTradeError("That market is already decided.")
        stake = contracts * price / 100.0
        cap = float(self.engine.settings["max_stake_per_trade"])
        if stake > cap + 1e-6:
            raise SoccerTradeError(f"${stake:,.2f} is over your ${cap:,.0f} limit per trade (Settings).")
        mode = self.mode
        if mode == "live":
            if not self.engine.kalshi.can_sign:
                raise SoccerTradeError("Live trading needs Kalshi API keys on the server.")
            try:
                fill = await self.engine.kalshi.place_order(ticker, "over" if side == "yes" else "under", "buy", contracts, price)
            except KalshiError as exc:
                raise SoccerTradeError(str(exc)) from exc
            if fill["filled"] <= 0:
                raise SoccerTradeError(f"Kalshi did not fill any contracts at {price}c.")
            filled, px = fill["filled"], round(fill["price"])
            fees = fill["fees"] or kalshi_fee(filled, px)
        else:
            ask = market.ask(side)
            if ask is None:
                raise SoccerTradeError("No offer on that side right now.")
            if ask > price:
                raise SoccerTradeError(f"The price moved to {ask}c, above your {price}c limit.")
            filled, px, fees = contracts, ask, kalshi_fee(contracts, ask)
        p_yes = market.p_yes
        row = {
            "match_id": match.id, "match_label": match.label, "league": match.league, "ticker": ticker,
            "segment": market.segment, "kind": market.kind, "outcome": market.outcome, "strike": market.strike,
            "side": side, "label": market.label(side, match), "contracts": filled, "entry_price": px,
            "cost": round(filled * px / 100.0 + fees, 2), "fees": fees, "mode": mode, "status": "open",
            "p_entry": None if p_yes is None else round(p_yes if side == "yes" else 1 - p_yes, 4),
            "context": self._context(match), "opened_at": now_iso(),
        }
        row["id"] = self.db.insert("soccer_positions", row)
        return self._position(row)

    async def close(self, position_id: int) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM soccer_positions WHERE id=? AND status='open'", [position_id])
        if row is None:
            raise SoccerTradeError("No open soccer position with that id.")
        match = self.by_id.get(row["match_id"])
        market = match.market(row["ticker"]) if match else None
        bid = market.bid(row["side"]) if market else None
        if bid is None:
            raise SoccerTradeError("No bid to sell into right now.")
        if row["mode"] == "live":
            try:
                fill = await self.engine.kalshi.place_order(row["ticker"], "over" if row["side"] == "yes" else "under", "sell", row["contracts"], bid)
            except KalshiError as exc:
                raise SoccerTradeError(str(exc)) from exc
            if fill["filled"] <= 0:
                raise SoccerTradeError(f"Kalshi did not fill the sell at {bid}c.")
            px = round(fill["price"])
            fees = fill["fees"] or kalshi_fee(fill["filled"], px)
        else:
            px, fees = bid, kalshi_fee(row["contracts"], bid)
        return self._finish(row, px, "sold", fees)

    def _finish(self, row: dict[str, Any], exit_price: int, reason: str, exit_fees: float = 0.0) -> dict[str, Any]:
        pnl = round(row["contracts"] * exit_price / 100.0 - row["cost"] - exit_fees, 2)  # cost includes the entry fee
        fields = {"status": "closed", "exit_price": exit_price, "exit_reason": reason, "pnl": pnl,
                  "fees": round(row["fees"] + exit_fees, 2), "closed_at": now_iso()}
        self.db.update("soccer_positions", row["id"], fields)
        return self._trade({**row, **fields})

    async def sync_with_kalshi(self) -> list[dict[str, Any]]:
        """Close live positions you sold outside Courtside (on Kalshi's own app or site).

        Kalshi holding fewer contracts than the desk thinks means some were sold elsewhere.
        They are closed at the prices of the sell fills Kalshi reports after the position
        opened. Without such fills nothing is touched: a market Kalshi has settled also
        empties the position, and settlement is `_settle`'s job.
        """
        rows = self.db.query("SELECT * FROM soccer_positions WHERE status='open' AND mode='live' ORDER BY id DESC")
        if not rows:
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=SYNC_GRACE_S)).isoformat()
        held = await self.engine.kalshi.positions()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault((row["ticker"], row["side"]), []).append(row)
        closed: list[dict[str, Any]] = []
        for (ticker, side), group in groups.items():
            if any(r["opened_at"] > cutoff for r in group):
                continue
            count = held.get(ticker, 0.0)
            on_kalshi = int(round(max(count, 0) if side == "yes" else max(-count, 0)))
            missing = sum(r["contracts"] for r in group) - on_kalshi
            if missing <= 0:
                continue
            first_open = min(r["opened_at"] for r in group)
            sells = [f for f in await self.engine.kalshi.fills(ticker)
                     if _iso(f["created_time"]) > first_open and not _is_entry(f, group)]
            sold = sum(f["count"] for f in sells)
            if sold + 1e-9 < missing:
                continue  # no sale on record: likely settled, so leave it to settlement
            for row in group:  # newest first, matching how the sells were most likely meant
                if missing <= 0:
                    break
                take = min(row["contracts"], missing)
                px, fees = _fill_price(sells, side, take)
                if take < row["contracts"]:
                    row = self._split(row, take)
                closed.append(self._finish(row, px, "sold_on_kalshi", fees))
                missing -= take
        for trade in closed:
            log.info("soccer: %s %s closed, sold on Kalshi at %sc", trade["match_label"], trade["label"], trade["exit_price"])
        return closed

    def _split(self, row: dict[str, Any], take: int) -> dict[str, Any]:
        """Carve `take` contracts off an open position into a row of their own; returns that row."""
        share = take / row["contracts"]
        part = {k: v for k, v in row.items() if k != "id"}
        part.update(contracts=take, cost=round(row["cost"] * share, 2), fees=round(row["fees"] * share, 2))
        part["id"] = self.db.insert("soccer_positions", part)
        self.db.update("soccer_positions", row["id"], {
            "contracts": row["contracts"] - take,
            "cost": round(row["cost"] - part["cost"], 2),
            "fees": round(row["fees"] - part["fees"], 2),
        })
        return part

    def _settle(self) -> None:
        if not self.by_id:
            return
        for row in self.db.query("SELECT * FROM soccer_positions WHERE status='open'"):
            match = self.by_id.get(row["match_id"])
            if match is None:
                continue
            market = match.market(row["ticker"]) or SMarket(
                ticker=row["ticker"], segment=row["segment"], kind=row["kind"], outcome=row["outcome"], strike=row["strike"]
            )
            yes = match.settles_yes(market)
            if yes is None:
                continue
            won = yes == (row["side"] == "yes")
            self._finish(row, 100 if won else 0, "settled_win" if won else "settled_loss")

    @staticmethod
    def _context(match: Match) -> dict[str, Any]:
        """What the match looked like when the trade was placed."""
        return {
            "minute": match.clock or None, "state": match.state,
            "score": f"{match.home.score}-{match.away.score}",
            "red_cards": {"home": match.home.red_cards, "away": match.away.red_cards},
            "stats": match.stats, "projection": (match.projection or {}).get("match"),
        }

    # ------------------------------------------------------------- read models
    def _position(self, row: dict[str, Any]) -> dict[str, Any]:
        match = self.by_id.get(row["match_id"])
        market = match.market(row["ticker"]) if match else None
        bid = market.bid(row["side"]) if market else None
        mark = bid if bid is not None else row["entry_price"]
        p_yes = market.p_yes if market else None
        value = row["contracts"] * mark / 100.0
        return {
            "id": row["id"], "match_id": row["match_id"], "match_label": row["match_label"], "league": row["league"],
            "ticker": row["ticker"], "segment": row["segment"], "kind": row["kind"], "side": row["side"], "label": row["label"],
            "contracts": row["contracts"], "entry_price": row["entry_price"], "mark_price": mark, "cost": row["cost"],
            "value": round(value, 2), "pnl": round(value - row["cost"], 2),
            "max_profit": round(row["contracts"] - row["cost"], 2),
            "p_win": None if p_yes is None else round(p_yes if row["side"] == "yes" else 1 - p_yes, 4),
            "p_entry": row["p_entry"], "mode": row["mode"], "opened_at": row["opened_at"], "can_sell": bid is not None,
        }

    @staticmethod
    def _trade(row: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "match_id", "match_label", "league", "ticker", "segment", "kind", "side", "label", "contracts",
                "entry_price", "exit_price", "cost", "fees", "pnl", "exit_reason", "mode", "opened_at", "closed_at", "p_entry")
        return {k: row.get(k) for k in keys}

    def positions_api(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM soccer_positions WHERE status='open' AND mode=? ORDER BY id DESC", [self.mode])
        return [self._position(r) for r in rows]

    def trades_api(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM soccer_positions WHERE status='closed' AND mode=? ORDER BY closed_at DESC LIMIT ?", [self.mode, limit])
        return [self._trade(r) for r in rows]

    def account(self) -> dict[str, Any]:
        mode = self.mode
        closed = self.db.one(
            "SELECT COALESCE(SUM(pnl),0) pnl, COALESCE(SUM(pnl>0),0) wins, COALESCE(SUM(pnl<=0),0) losses "
            "FROM soccer_positions WHERE status='closed' AND mode=?", [mode],
        )
        open_rows = self.positions_api()
        exposure = sum(p["cost"] for p in open_rows)
        value = sum(p["value"] for p in open_rows)
        if mode == "live":
            cash = self.engine._live_balance["cash"]
        else:
            cash = self.cfg.paper_starting_cash + closed["pnl"] - exposure
        return {
            "mode": mode, "cash": round(cash, 2), "exposure": round(exposure, 2),
            "open_value": round(value, 2), "pnl_open": round(value - exposure, 2), "pnl_total": round(closed["pnl"], 2),
            "wins": int(closed["wins"]), "losses": int(closed["losses"]), "open_positions": len(open_rows),
            "paper_bankroll": self.cfg.paper_starting_cash,
        }

    def card(self, m: Match) -> dict[str, Any]:
        """One match for the board."""
        winner = {mk.outcome: market_dict(mk, m) for mk in m.markets if mk.segment == "match" and mk.kind == "winner"}
        side = lambda s: {"name": s.name, "short": s.short, "abbr": s.abbr, "color": s.color, "logo": s.logo,  # noqa: E731
                          "score": s.score, "half_score": s.half_score, "red_cards": s.red_cards}
        goals = [e for e in m.events if e["goal"]]
        return {
            "id": m.id, "league": m.league, "league_name": LEAGUE_BY_KEY[m.league].name, "label": m.label,
            "home": side(m.home), "away": side(m.away), "start_time": m.start_time, "state": m.state,
            "period": m.period, "minute": m.minute, "clock": m.clock, "status": m.status, "halftime": m.halftime,
            "winner": winner or None, "total_line": implied_line([x for x in m.markets if x.segment == "match"]),
            "projection": m.projection, "last_goal": goals[-1] if goals else None, "has_markets": bool(m.markets),
        }

    def detail(self, m: Match) -> dict[str, Any]:
        return {
            "match": self.card(m),
            "markets": [market_dict(x, m) for x in m.markets],
            "first_half_line": implied_line([x for x in m.markets if x.segment == "1h"]),
            "events": m.events, "stats": m.stats, "commentary": m.commentary[-80:],
            "prior": {"home_goals": m.lam_home, "away_goals": m.lam_away, "source": m.prior_source},
            "positions": [p for p in self.positions_api() if p["match_id"] == m.id],
            "account": self.account(),
        }

    def board(self) -> dict[str, Any]:
        return {
            "leagues": [{"key": lg.key, "name": lg.name} for lg in LEAGUES],
            "matches": [self.card(m) for m in self.matches],
            "account": self.account(),
            "positions": self.positions_api(),
            "feeds": self.feed.status,
            "updated_at": self.last_tick,
        }

    # ---------------------------------------------------------------- the agent
    def briefing(self, m: Match) -> dict[str, Any]:
        """Everything about one match, for Agent analysis."""
        return {
            "match": f"{m.home.name} (home) vs {m.away.name} (away)", "league": LEAGUE_BY_KEY[m.league].name,
            "state": m.state, "minute": m.clock, "status": m.status, "kickoff": m.start_time,
            "score": {m.home.short: m.home.score, m.away.short: m.away.score},
            "first_half_score": {m.home.short: m.home.half_score, m.away.short: m.away.half_score} if m.home.half_score is not None else None,
            "red_cards": {m.home.short: m.home.red_cards, m.away.short: m.away.red_cards},
            "stats": {k: {m.home.short: v.get("home"), m.away.short: v.get("away")} for k, v in m.stats.items()},
            "events": [f"{e['minute']} {({'home': m.home.short, 'away': m.away.short}).get(e['team'] or '', '')} {e['type']}: {e['text']}" for e in m.events],
            "pre_match_expected_goals": {m.home.short: m.lam_home, m.away.short: m.lam_away, "source": m.prior_source},
            "model_projection": m.projection,
            "kalshi_total_line": implied_line([x for x in m.markets if x.segment == "match"]),
            "kalshi_first_half_total_line": implied_line([x for x in m.markets if x.segment == "1h"]),
            "markets": [
                {"yes": x.label("yes", m), "yes_ask": x.yes_ask, "no": x.label("no", m), "no_ask": x.no_ask,
                 "model_p_yes": x.p_yes, "segment": x.segment, "kind": x.kind}
                for x in m.markets if x.yes_ask or x.no_ask
            ],
            "my_positions_here": [
                {k: p[k] for k in ("label", "contracts", "entry_price", "mark_price", "cost", "pnl", "p_win", "p_entry")}
                for p in self.positions_api() if p["match_id"] == m.id
            ],
            "soccer_record": self.account(),
        }

    def commentary_text(self, m: Match) -> str:
        return "\n".join(f"{c['minute'] or '-'} {c['text']}" for c in m.commentary)

    def find(self, query: str) -> Optional[Match]:
        q = query.lower().strip()
        return self.by_id.get(query) or next(
            (m for m in self.matches if q in m.label.lower() or q in f"{m.home.name} {m.away.name}".lower()), None
        )


def _iso(ts: str) -> str:
    """Kalshi's '...Z' timestamps in the same form as `now_iso()`, so they compare as strings."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ""


def _is_entry(fill: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """A fill from one of the desk's own buys: it lands just before that position's `opened_at`."""
    t = _iso(fill["created_time"])
    for r in rows:
        opened = datetime.fromisoformat(r["opened_at"])
        if (opened - timedelta(seconds=5)).isoformat(timespec="seconds") <= t <= r["opened_at"]:
            return True
    return False


def _fill_price(fills: list[dict[str, Any]], side: str, contracts: int) -> tuple[int, float]:
    """Average price (cents, for `side`) and fees of the most recent `contracts` sold."""
    left, value, fees = float(contracts), 0.0, 0.0
    for f in fills:  # newest first
        if left <= 0:
            break
        n = min(f["count"], left)
        value += n * (f["yes_price"] if side == "yes" else f["no_price"])
        fees += f["fee"] * n / f["count"] if f["count"] else 0.0
        left -= n
    return round(value / contracts), round(fees, 2)
