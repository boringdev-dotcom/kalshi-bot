"""Sizing, stops, and entry gates seeded from Phase 0 pattern report.

Source: docs/pattern-report.md proposed playbook (2026-09-21).
Buy No only. History's HT / rem≥3 / 95¢ / 2,000-contract habit is
intentionally not copied — that slice lost money.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kalshi_bot.rem import playbook_rem

# Seeded from docs/pattern-report.md "Proposed playbook".
SIDE = "no"
ENTRY_MIN_MINUTE = 60
ENTRY_MAX_MINUTE = 92
ENTRY_MAX_REM = 2
REM_3_OK_STRIKE = 4.5  # rem=3 allowed only on Over >= 4.5 in tier 1
ENTRY_NO_PRICE_MIN = 80
ENTRY_NO_PRICE_MAX = 92
MAX_SPREAD_CENTS = 6
STOP_PRICE_DROP_CENTS = 12
FLATTEN_ON_GOAL = True
FLATTEN_REM_AT = 1
NO_REENTRY_AFTER_STOP = True
MAX_CONTRACTS_PER_MATCH = 150
MAX_CONTRACTS_PER_MATCH_HARD = 250
MAX_CONTRACTS_PER_DAY = 600
ALLOWED_TIERS = (1, 2)
SKIP_1H_TOTALS = True
PAPER_MODE_DEFAULT = True

# Clip size near historical medians (tier 1 p50=103, tier 2 p50=27), under the 150/match cap.
TIER_SIZE = {1: 100, 2: 25}

LEAGUE_TIERS = {
    "premier_league": 1,
    "epl": 1,
    "ucl": 1,
    "champions_league": 1,
    "world_cup": 1,
    "la_liga": 1,
    "serie_a": 1,
    "bundesliga": 1,
    "ligue_1": 1,
    "mls": 2,
    "uel": 2,
    "europa_league": 2,
    "liga_mx": 2,
    "eredivisie": 2,
    "championship": 2,
    "liga_portugal": 2,
    "nwsl": 3,
    "uwcl": 3,
}

PLAYBOOK_NOTES = {
    "source": "docs/pattern-report.md proposed playbook",
    "side": SIDE,
    "entry_min_minute": ENTRY_MIN_MINUTE,
    "entry_max_minute": ENTRY_MAX_MINUTE,
    "entry_max_rem": ENTRY_MAX_REM,
    "rem_3_ok_strike": REM_3_OK_STRIKE,
    "entry_no_price_min": ENTRY_NO_PRICE_MIN,
    "entry_no_price_max": ENTRY_NO_PRICE_MAX,
    "stop_price_drop_cents": STOP_PRICE_DROP_CENTS,
    "flatten_on_goal": FLATTEN_ON_GOAL,
    "flatten_rem_at": FLATTEN_REM_AT,
    "no_reentry_after_stop": NO_REENTRY_AFTER_STOP,
    "max_contracts_per_match": MAX_CONTRACTS_PER_MATCH,
    "max_contracts_per_day": MAX_CONTRACTS_PER_DAY,
    "allowed_tiers": list(ALLOWED_TIERS),
    "skip_1h_totals": SKIP_1H_TOTALS,
    "paper_mode_default": PAPER_MODE_DEFAULT,
    "tier_size": TIER_SIZE,
}


def league_tier(league: Optional[str]) -> int:
    if not league:
        return 3
    key = league.lower().replace(" ", "_")
    return LEAGUE_TIERS.get(key, 3)


def is_1h_total(ticker: Optional[str] = None, series: Optional[str] = None, title: Optional[str] = None) -> bool:
    blob = " ".join(part or "" for part in (ticker, series, title)).upper()
    return "1H" in blob or "FIRST HALF" in blob


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


def _as_int_rem(rem: float, strike: Optional[float] = None) -> int:
    """Accept integer playbook rem or float remaining_goals (strike - goals)."""
    if strike is not None:
        goals = max(0, int(round(float(strike) - float(rem))))
        return playbook_rem(strike, goals)
    if rem == int(rem):
        return int(rem)
    if rem < 0:
        return int(rem)
    return int(rem) + 1


def rem_allowed(rem: float, strike: Optional[float], tier: int) -> bool:
    ival = _as_int_rem(rem, strike)
    if ival <= ENTRY_MAX_REM:
        return True
    if (
        ival == 3
        and strike is not None
        and float(strike) >= REM_3_OK_STRIKE
        and tier == 1
    ):
        return True
    return False


def size_for_tier(tier: int, remaining_match_cap: int, remaining_day_cap: int) -> int:
    if tier not in ALLOWED_TIERS:
        return 0
    raw = TIER_SIZE.get(tier, 0)
    return max(0, min(raw, remaining_match_cap, remaining_day_cap, MAX_CONTRACTS_PER_MATCH_HARD))


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
    strike: Optional[float] = None,
    is_1h: bool = False,
) -> PlaybookDecision:
    if already_stopped and NO_REENTRY_AFTER_STOP:
        return PlaybookDecision(False, "pass", 0, "no re-entry after stop")
    if phase == "full_time":
        return PlaybookDecision(False, "pass", 0, "match is finished")
    if SKIP_1H_TOTALS and is_1h:
        return PlaybookDecision(False, "pass", 0, "1H totals off until more sample")
    if minute < ENTRY_MIN_MINUTE or minute > ENTRY_MAX_MINUTE:
        return PlaybookDecision(
            False, "pass", 0, f"minute {minute} outside {ENTRY_MIN_MINUTE}-{ENTRY_MAX_MINUTE}"
        )
    tier = league_tier(league)
    if tier not in ALLOWED_TIERS:
        return PlaybookDecision(False, "pass", 0, f"tier {tier} not in {ALLOWED_TIERS}")
    if rem < 0:
        return PlaybookDecision(False, "pass", 0, "over already landed")
    if not rem_allowed(rem, strike, tier):
        return PlaybookDecision(False, "pass", 0, f"rem {rem} above playbook max {ENTRY_MAX_REM}")
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
    size = size_for_tier(tier, remaining_match, remaining_day)
    if size <= 0:
        return PlaybookDecision(False, "pass", 0, "match or daily contract cap reached")

    stop_price = max(1, no_ask - STOP_PRICE_DROP_CENTS)
    return PlaybookDecision(
        True,
        "buy_no",
        size,
        (
            f"buy No: min={minute} rem={rem} ask={no_ask}¢ "
            f"tier={tier} size={size}"
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
    strike: Optional[float] = None,
) -> PlaybookDecision:
    if not has_position:
        return PlaybookDecision(False, "hold", 0, "no open position")
    if FLATTEN_ON_GOAL and event_type == "goal":
        return PlaybookDecision(True, "flatten", 0, "flatten on goal")
    if event_type == "full_time":
        return PlaybookDecision(True, "flatten", 0, "flatten at full-time")
    ival = _as_int_rem(rem, strike) if rem is not None else None
    if ival is not None and ival <= FLATTEN_REM_AT:
        return PlaybookDecision(True, "flatten", 0, f"rem {ival} -> {FLATTEN_REM_AT} stop")
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
        "Playbook constraints (seeded from docs/pattern-report.md):\n"
        f"- Buy No only, minute {ENTRY_MIN_MINUTE}-{ENTRY_MAX_MINUTE}, "
        f"rem <= {ENTRY_MAX_REM} (rem=3 only on Over >= {REM_3_OK_STRIKE} tier 1), "
        f"No ask {ENTRY_NO_PRICE_MIN}-{ENTRY_NO_PRICE_MAX}¢.\n"
        f"- Max {MAX_CONTRACTS_PER_MATCH} contracts/match, {MAX_CONTRACTS_PER_DAY}/day. "
        f"Tiers {ALLOWED_TIERS} only; 1H totals off.\n"
        f"- Flatten on goal, rem -> {FLATTEN_REM_AT}, or No mid down {STOP_PRICE_DROP_CENTS}¢.\n"
        "- No re-entry after a stop. Paper mode is the default."
    )
