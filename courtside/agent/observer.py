"""The shadow book: learning about quarter markets without trading them.

The agent does not place orders on quarter totals or spreads. It watches. At
two moments in every quarter it writes down what each market could have been
bought for and what the model thought it was worth:

    open - in the first three minutes of the quarter
    mid  - with about six minutes left

When the quarter ends it marks which side won. Over many quarters that adds
up to a plain answer to "if you had bought this kind of contract at this kind
of price, what happened?", for the market's prices and the model's opinions
alike. It is the evidence to read before ever letting the agent trade these.

Simulated quarters are recorded too, kept apart, and capped so a sandbox left
running does not fill the disk.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..db import DB
from ..domain import SEGMENTS, Game, now_iso

OPEN_WINDOW = (540, 720)  # seconds left in the quarter
MID_WINDOW = (240, 360)
PRICE_RANGE = (3, 97)
BUCKETS = [(3, 20, "3-20"), (20, 40, "20-40"), (40, 60, "40-60"), (60, 80, "60-80"), (80, 98, "80-97")]
SIM_KEEP = 30000


class QuarterObserver:
    def __init__(self, db: DB):
        self.db = db
        self._seen: set[tuple[str, str, str]] = set()
        self._settled: set[tuple[str, str]] = set()
        self._since_prune = 0

    def observe(self, games: list[Game]) -> None:
        for game in games:
            for q, segment in enumerate(SEGMENTS, start=1):
                status = game.quarter_status(q)
                if status == "live":
                    secs = game.quarter_seconds_left(q)
                    for checkpoint, (lo, hi) in (("open", OPEN_WINDOW), ("mid", MID_WINDOW)):
                        if lo <= secs <= hi and (game.id, segment, checkpoint) not in self._seen:
                            if self._record(game, segment, checkpoint):
                                self._seen.add((game.id, segment, checkpoint))
                elif status == "final" and (game.id, segment) not in self._settled:
                    self._settle(game, segment)
                    self._settled.add((game.id, segment))
        if self._since_prune > 2000:
            self._prune()

    def _record(self, game: Game, segment: str, checkpoint: str) -> bool:
        """Write down every tradable market in one quarter. False if there was nothing to record yet."""
        lo, hi = PRICE_RANGE
        wrote = False
        for rungs in game.quarter_markets.get(segment, {}).values():
            for r in rungs:
                if r.yes_ask is None or r.no_ask is None or not (lo <= r.yes_ask <= hi and lo <= r.no_ask <= hi):
                    continue
                self.db.execute(
                    "INSERT OR IGNORE INTO observations(game_id, game_label, simulated, segment, kind, ticker, team, strike, "
                    "checkpoint, yes_ask, no_ask, p_yes, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [game.id, game.label, int(game.simulated), segment, r.kind, r.ticker, r.team, r.strike,
                     checkpoint, r.yes_ask, r.no_ask, round(1 - r.p_under, 4), now_iso()],
                )
                wrote = True
                self._since_prune += 1
        return wrote

    def _settle(self, game: Game, segment: str) -> None:
        rows = self.db.query(
            "SELECT id, kind, team, strike FROM observations WHERE game_id=? AND segment=? AND outcome_yes IS NULL",
            [game.id, segment],
        )
        for row in rows:
            value = game.settle_value(segment, row["kind"], row["team"])
            if value is not None:
                self.db.execute("UPDATE observations SET outcome_yes=? WHERE id=?", [int(value > row["strike"]), row["id"]])

    def _prune(self) -> None:
        self._since_prune = 0
        self.db.execute(
            "DELETE FROM observations WHERE simulated=1 AND id <= "
            "(SELECT id FROM observations WHERE simulated=1 ORDER BY id DESC LIMIT 1 OFFSET ?)",
            [SIM_KEEP],
        )

    def summary(self, simulated: bool) -> dict[str, Any]:
        sim = int(simulated)
        counts = self.db.one(
            "SELECT COUNT(*) n, COALESCE(SUM(outcome_yes IS NOT NULL), 0) settled, COUNT(DISTINCT game_id) games "
            "FROM observations WHERE simulated=?",
            [sim],
        )
        rows = self.db.query(
            "SELECT segment, kind, checkpoint, yes_ask, no_ask, p_yes, outcome_yes FROM observations "
            "WHERE simulated=? AND outcome_yes IS NOT NULL ORDER BY id DESC LIMIT 60000",
            [sim],
        )
        agg: dict[tuple, list[float]] = defaultdict(lambda: [0, 0.0, 0.0, 0.0, 0.0])  # n, price, wins, model, return
        for r in rows:
            for side, price, won, model in (
                ("over", r["yes_ask"], r["outcome_yes"], r["p_yes"]),
                ("under", r["no_ask"], 1 - r["outcome_yes"], 1 - r["p_yes"]),
            ):
                bucket = next((name for lo, hi, name in BUCKETS if lo <= price < hi), None)
                if bucket is None:
                    continue
                p = price / 100.0
                cost = p + 0.07 * p * (1 - p)  # ask plus Kalshi's taker fee
                cell = agg[(r["segment"], r["kind"], r["checkpoint"], side, bucket)]
                cell[0] += 1
                cell[1] += price
                cell[2] += won
                cell[3] += model
                cell[4] += (won - cost) / cost
        order = {name: i for i, (_, _, name) in enumerate(BUCKETS)}
        cells = [
            {"segment": seg, "kind": kind, "checkpoint": cp, "side": side, "bucket": bucket, "n": int(c[0]),
             "price": round(c[1] / c[0], 1), "win_rate": round(c[2] / c[0], 4), "model": round(c[3] / c[0], 4),
             "ret": round(c[4] / c[0], 4)}
            for (seg, kind, cp, side, bucket), c in agg.items()
        ]
        cells.sort(key=lambda c: (c["segment"], c["kind"], c["checkpoint"], c["side"], order[c["bucket"]]))
        mine = self.db.query(
            "SELECT segment, kind, COUNT(*) n, COALESCE(SUM(pnl > 0), 0) wins, ROUND(COALESCE(SUM(pnl), 0), 2) pnl "
            "FROM positions WHERE status='closed' AND training=0 AND opened_by='user' AND segment != 'game' AND simulated=? "
            "GROUP BY segment, kind ORDER BY segment, kind",
            [sim],
        )
        return {
            "observations": counts["n"],
            "settled": int(counts["settled"]),
            "games": counts["games"],
            "cells": cells,
            "your_trades": mine,
        }
