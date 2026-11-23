"""Watching bets the owner placed themselves.

Claude makes the call: it reads the game and says sell or hold. This module decides when it is
worth asking (first look, the game turning, the win chance sliding, the numbers raising an
alarm, or simply time passing, sooner the more worried it was last time) and keeps its last read
for the app. The fixed rule in policy.watch_signal only steps in when Claude cannot be reached.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Optional

MIN_GAP_S = 45.0  # never ask about the same bet more often than this
EVERY_S = {"low": 420.0, "medium": 180.0, "high": 60.0}  # look again sooner the more worried the last read was
SLIDE = 0.10  # a fall in win chance this big since the last look is worth a fresh one
CONSISTENCY_CENTS = 10  # a "sell" whose own win estimate is worth this much more than the bid is not a sell


@dataclass
class WatchState:
    reviewed_at: float = -1e9  # time.monotonic() of the last look
    p_at_review: Optional[float] = None
    signature: str = ""
    every: float = EVERY_S["medium"]
    task: Optional[asyncio.Task] = None
    note: Optional[dict[str, Any]] = None  # Claude's last read, shown on the bet
    failed: bool = False  # the last look got no answer, so the fixed rule is on duty


class BetWatcher:
    def __init__(self) -> None:
        self.states: dict[int, WatchState] = {}

    def why_now(self, bet_id: int, *, p_now: Optional[float], signature: str, alarm: bool, now: float) -> Optional[str]:
        """Why Claude should look at this bet now, or None if it is not time."""
        st = self.states.setdefault(bet_id, WatchState())
        if st.task is not None and not st.task.done():
            return None
        since = now - st.reviewed_at
        if since < MIN_GAP_S:
            return None
        if st.reviewed_at < 0:
            return "First look: the owner just asked you to watch this bet."
        reasons = []
        if alarm:
            reasons.append("Alarm: the price and the model have both moved hard against this bet.")
        if signature != st.signature:
            reasons.append(f"The game changed: now {signature} (was {st.signature}).")
        if p_now is not None and st.p_at_review is not None and st.p_at_review - p_now >= SLIDE:
            reasons.append(f"The model's win chance slid from {st.p_at_review:.0%} to {p_now:.0%} since your last look.")
        if reasons:
            return " ".join(reasons)
        return "Routine check." if since >= st.every else None

    def start(self, bet_id: int, job: Awaitable[Any], *, p_now: Optional[float], signature: str, now: float) -> None:
        st = self.states.setdefault(bet_id, WatchState())
        st.reviewed_at, st.p_at_review, st.signature = now, p_now, signature
        st.task = asyncio.ensure_future(job)

    def record(self, bet_id: int, verdict: Optional[dict[str, Any]], at: str) -> None:
        st = self.states.setdefault(bet_id, WatchState())
        if verdict is None:
            st.failed = True
            return
        st.failed = False
        st.every = EVERY_S.get(verdict["concern"], EVERY_S["medium"])
        st.note = {"action": verdict["action"], "reason": verdict["reason"], "concern": verdict["concern"],
                   "win_chance": verdict["win_chance"], "at": at}

    def failed(self, bet_id: int) -> bool:
        st = self.states.get(bet_id)
        return bool(st and st.failed)

    def note(self, bet_id: int) -> Optional[dict[str, Any]]:
        st = self.states.get(bet_id)
        return st.note if st else None

    def forget(self, bet_id: int) -> None:
        self.states.pop(bet_id, None)


def checked(verdict: dict[str, Any], bid: Optional[int]) -> dict[str, Any]:
    """Hold a "sell" that its own numbers argue against: Claude rates the bet well above the bid."""
    if verdict["action"] == "sell" and (bid is None or verdict["win_chance"] * 100 >= bid + CONSISTENCY_CENTS):
        worth = f"{verdict['win_chance']:.0%}"
        return {**verdict, "action": "hold", "concern": "high",
                "reason": f"{verdict['reason']} (Held anyway: it rates the bet at {worth}, worth more than the "
                          f"{'missing' if bid is None else f'{bid}c'} bid.)"}
    return verdict
