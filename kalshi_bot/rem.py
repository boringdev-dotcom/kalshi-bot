"""Remaining-goals math for soccer totals."""

from __future__ import annotations

import math


def remaining_goals(strike: float, current_goals: int) -> float:
    """Goals still needed to reach the over strike.

    ``rem = strike - current_goals``. A 2.5 line with 1 goal scored is 1.5.
    Negative rem means the over has already landed.
    """
    if current_goals < 0:
        raise ValueError("current_goals cannot be negative")
    return float(strike) - float(current_goals)


def over_settled(strike: float, current_goals: int) -> bool:
    return remaining_goals(strike, current_goals) < 0


def goals_to_bust_under(strike: float, current_goals: int) -> int:
    """Whole goals still required to push the match over the line."""
    rem = remaining_goals(strike, current_goals)
    if rem < 0:
        return 0
    return int(rem) + 1


def playbook_rem(strike: float, current_goals: int) -> int:
    """Integer rem used by the Phase 0 playbook.

    Ticker suffix N is Over (N - 0.5), so rem = N - goals_so_far.
    Over 3.5 → N = 4. Negative means the over has landed.
    """
    if current_goals < 0:
        raise ValueError("current_goals cannot be negative")
    return int(math.ceil(float(strike))) - int(current_goals)
