"""Sizing, stops, and entry gates.

Phase 0 pattern report was not present at
`docs/pattern-report.md`, so these are conservative placeholders.
They bias toward late-game, low-rem, high-priced No (under) entries
and flatten immediately on a goal or rem drop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Conservative placeholders (no historical fill study available).
ENTRY_MIN_MINUTE = 70
ENTRY_MAX_REM = 1.0
ENTRY_NO_PRICE_MIN = 78
ENTRY_NO_PRICE_MAX = 93
MAX_SPREAD_CENTS = 6
STOP_PRICE_DROP_CENTS = 8
FLATTEN_ON_GOAL = True
FLATTEN_ON_REM_DROP = True
NO_REENTRY_AFTER_STOP = True
MAX_CONTRACTS_PER_MATCH = 5
MAX_CONTRACTS_PER_DAY = 15

TIER_SIZE = {1: 3, 2: 2, 3: 1}

LEAGUE_TIERS = {
    "premier_league": 1,
    "epl": 1,
    "ucl": 1,
    "champions_league": 1,
    "la_liga": 1,
    "serie_a": 1,
    "bundesliga": 2,
    "ligue_1": 2,
    "eredivisie": 3,
    "mls": 3,
    "championship": 3,
}

PLAYBOOK_NOTES = {
    "source": "conservative placeholders",
    "reason": "docs/pattern-report.md was missing at rebuild time",
    "entry_min_minute": ENTRY_MIN_MINUTE,
    "entry_max_rem": ENTRY_MAX_REM,
    "entry_no_price_min": ENTRY_NO_PRICE_MIN,
    "entry_no_price_max": ENTRY_NO_PRICE_MAX,
    "stop_price_drop_cents": STOP_PRICE_DROP_CENTS,
    "flatten_on_goal": FLATTEN_ON_GOAL,
    "flatten_on_rem_drop": FLATTEN_ON_REM_DROP,
    "no_reentry_after_stop": NO_REENTRY_AFTER_STOP,
    "max_contracts_per_match": MAX_CONTRACTS_PER_MATCH,
    "max_contracts_per_day": MAX_CONTRACTS_PER_DAY,
    "tier_size": TIER_SIZE,
}


def league_tier(league: Optional[str]) -> int:
    if not league:
        return 3
    key = league.lower().replace(" ", "_")
    return LEAGUE_TIERS.get(key, 3)


@dataclass
class PlaybookDecision:
    allowed: bool
    action: str
    size: int
    reason: str
    stop_price: Optional[int] = None


def _spread(no_bid: Optional[int], no_ask: Optional[int]) -> Optional[int]:
    if no_bid is None or no_ask is None:
        return None
    return int(no_ask) - int(no_bid)


def size_for_tier(tier: int, remaining_match_cap: int, remaining_day_cap: int) -> int:
    raw = TIER_SIZE.get(tier, 1)
    return max(0, min(raw, remaining_match_cap, remaining_day_cap))


def evaluate_entry(
    *,
    minute: int,
    rem: float,
    no_ask: Optional[int],
    no_bid: Optional[int],
    league: Optional[str],
    already_stopped: bool,
    contracts_this_match: int,
    contracts_today: int,
    phase: str = "second_half",
) -> PlaybookDecision:
    if already_stopped and NO_REENTRY_AFTER_STOP:
        return PlaybookDecision(False, "pass", 0, "no re-entry after stop")
    if phase == "full_time":
        return PlaybookDecision(False, "pass", 0, "match is finished")
    if minute < ENTRY_MIN_MINUTE:
        return PlaybookDecision(False, "pass", 0, f"minute {minute} < {ENTRY_MIN_MINUTE}")
    if rem > ENTRY_MAX_REM:
        return PlaybookDecision(False, "pass", 0, f"rem {rem} > {ENTRY_MAX_REM}")
    if rem < 0:
        return PlaybookDecision(False, "pass", 0, "over already landed")
    if no_ask is None:
        return PlaybookDecision(False, "pass", 0, "no ask unavailable")
    if no_ask < ENTRY_NO_PRICE_MIN or no_ask > ENTRY_NO_PRICE_MAX:
        return PlaybookDecision(
            False,
            "pass",
            0,
            f"No ask {no_ask}¢ outside {ENTRY_NO_PRICE_MIN}-{ENTRY_NO_PRICE_MAX}",
        )
    spread = _spread(no_bid, no_ask)
    if spread is not None and spread > MAX_SPREAD_CENTS:
        return PlaybookDecision(False, "pass", 0, f"spread {spread}¢ > {MAX_SPREAD_CENTS}¢")

    remaining_match = MAX_CONTRACTS_PER_MATCH - contracts_this_match
    remaining_day = MAX_CONTRACTS_PER_DAY - contracts_today
    size = size_for_tier(league_tier(league), remaining_match, remaining_day)
    if size <= 0:
        return PlaybookDecision(False, "pass", 0, "match or daily contract cap reached")

    stop_price = max(1, no_ask - STOP_PRICE_DROP_CENTS)
    return PlaybookDecision(
        True,
        "buy_no",
        size,
        (
            f"late-game under: min={minute} rem={rem} ask={no_ask}¢ "
            f"tier={league_tier(league)} size={size}"
        ),
        stop_price=stop_price,
    )


def evaluate_exit(
    *,
    event_type: str,
    rem: Optional[float],
    prior_rem: Optional[float],
    no_mid: Optional[float],
    entry_price: Optional[int],
    has_position: bool,
) -> PlaybookDecision:
    if not has_position:
        return PlaybookDecision(False, "hold", 0, "no open position")
    if FLATTEN_ON_GOAL and event_type == "goal":
        return PlaybookDecision(True, "flatten", 0, "flatten on goal")
    if event_type == "full_time":
        return PlaybookDecision(True, "flatten", 0, "flatten at full-time")
    if FLATTEN_ON_REM_DROP and rem is not None and prior_rem is not None and rem < prior_rem:
        return PlaybookDecision(True, "flatten", 0, f"rem dropped {prior_rem} -> {rem}")
    if rem is not None and rem < 0:
        return PlaybookDecision(True, "flatten", 0, "over landed; rem negative")
    if (
        entry_price is not None
        and no_mid is not None
        and (entry_price - no_mid) >= STOP_PRICE_DROP_CENTS
    ):
        return PlaybookDecision(
            True,
            "flatten",
            0,
            f"No price dropped {entry_price - no_mid:.0f}¢ from entry {entry_price}¢",
        )
    return PlaybookDecision(False, "hold", 0, "stop not hit")


def constraints_text() -> str:
    return (
        "Playbook constraints (conservative placeholders; no Phase 0 pattern report):\n"
        f"- Buy No only after minute {ENTRY_MIN_MINUTE}, rem <= {ENTRY_MAX_REM}, "
        f"No ask in {ENTRY_NO_PRICE_MIN}-{ENTRY_NO_PRICE_MAX}¢, spread <= {MAX_SPREAD_CENTS}¢.\n"
        f"- Max {MAX_CONTRACTS_PER_MATCH} contracts/match, {MAX_CONTRACTS_PER_DAY}/day.\n"
        f"- Size by league tier: {TIER_SIZE}.\n"
        f"- Flatten on goal, rem drop, full-time, or No mid down {STOP_PRICE_DROP_CENTS}¢ from entry.\n"
        "- No re-entry after a stop on that market.\n"
        "- Paper mode is the default until explicitly flipped live."
    )
