"""Sizing, stops, and entry gates seeded from Phase 0 pattern report.

Source: docs/pattern-report.md proposed playbook (2026-09-21).
Buy No only. History's HT / rem≥3 / 95¢ / 2,000-contract habit is
intentionally not copied — that slice lost money.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from kalshi_bot.rem import playbook_rem

_tls = threading.local()

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


def default_rules() -> dict[str, Any]:
    return dict(PLAYBOOK_NOTES)


def current_rules() -> dict[str, Any]:
    overlay = getattr(_tls, "rules", None)
    return overlay if overlay is not None else default_rules()


@contextmanager
def override_playbook(rules: Optional[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """Temporarily overlay playbook thresholds (used by proposal backtests)."""
    prev = getattr(_tls, "rules", None)
    merged = default_rules()
    if rules:
        merged.update(rules)
    _tls.rules = merged
    try:
        yield merged
    finally:
        _tls.rules = prev


def _rule(rules: Optional[dict[str, Any]], key: str, default: Any) -> Any:
    src = rules if rules is not None else current_rules()
    if key in src and src[key] is not None:
        return src[key]
    return default


def league_tier(league: Optional[str], rules: Optional[dict[str, Any]] = None) -> int:
    if not league:
        return 3
    key = league.lower().replace(" ", "_")
    tiers = _rule(rules, "league_tiers", LEAGUE_TIERS)
    return int(tiers.get(key, 3)) if isinstance(tiers, dict) else 3


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


def rem_allowed(
    rem: float,
    strike: Optional[float],
    tier: int,
    rules: Optional[dict[str, Any]] = None,
) -> bool:
    ival = _as_int_rem(rem, strike)
    max_rem = int(_rule(rules, "entry_max_rem", ENTRY_MAX_REM))
    if ival <= max_rem:
        return True
    rem3_strike = float(_rule(rules, "rem_3_ok_strike", REM_3_OK_STRIKE))
    if ival == 3 and strike is not None and float(strike) >= rem3_strike and tier == 1:
        return True
    return False


def size_for_tier(
    tier: int,
    remaining_match_cap: int,
    remaining_day_cap: int,
    rules: Optional[dict[str, Any]] = None,
) -> int:
    allowed = tuple(_rule(rules, "allowed_tiers", ALLOWED_TIERS))
    if tier not in allowed:
        return 0
    sizes = _rule(rules, "tier_size", TIER_SIZE)
    if isinstance(sizes, dict):
        coerced = {}
        for key, value in sizes.items():
            try:
                coerced[int(key)] = value
            except (TypeError, ValueError):
                coerced[key] = value
        raw = int(coerced.get(tier, 0))
    else:
        raw = 0
    hard = int(_rule(rules, "max_contracts_per_match_hard", MAX_CONTRACTS_PER_MATCH_HARD))
    return max(0, min(raw, remaining_match_cap, remaining_day_cap, hard))


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
    max_match: Optional[int] = None,
    max_day: Optional[int] = None,
    rules: Optional[dict[str, Any]] = None,
) -> PlaybookDecision:
    no_reentry = bool(_rule(rules, "no_reentry_after_stop", NO_REENTRY_AFTER_STOP))
    if already_stopped and no_reentry:
        return PlaybookDecision(False, "pass", 0, "no re-entry after stop")
    if phase == "full_time":
        return PlaybookDecision(False, "pass", 0, "match is finished")
    skip_1h = bool(_rule(rules, "skip_1h_totals", SKIP_1H_TOTALS))
    if skip_1h and is_1h:
        return PlaybookDecision(False, "pass", 0, "1H totals off until more sample")
    min_min = int(_rule(rules, "entry_min_minute", ENTRY_MIN_MINUTE))
    max_min = int(_rule(rules, "entry_max_minute", ENTRY_MAX_MINUTE))
    if minute < min_min or minute > max_min:
        return PlaybookDecision(False, "pass", 0, f"minute {minute} outside {min_min}-{max_min}")
    tier = league_tier(league, rules)
    allowed = tuple(_rule(rules, "allowed_tiers", ALLOWED_TIERS))
    if tier not in allowed:
        return PlaybookDecision(False, "pass", 0, f"tier {tier} not in {allowed}")
    if rem < 0:
        return PlaybookDecision(False, "pass", 0, "over already landed")
    max_rem = int(_rule(rules, "entry_max_rem", ENTRY_MAX_REM))
    if not rem_allowed(rem, strike, tier, rules):
        return PlaybookDecision(False, "pass", 0, f"rem {rem} above playbook max {max_rem}")
    if no_ask is None:
        return PlaybookDecision(False, "pass", 0, "no ask unavailable")
    px_min = int(_rule(rules, "entry_no_price_min", ENTRY_NO_PRICE_MIN))
    px_max = int(_rule(rules, "entry_no_price_max", ENTRY_NO_PRICE_MAX))
    if no_ask < px_min or no_ask > px_max:
        return PlaybookDecision(
            False,
            "pass",
            0,
            f"No ask {no_ask}¢ outside {px_min}-{px_max}",
        )
    spread = _spread(no_bid, no_ask)
    max_spread = int(_rule(rules, "max_spread_cents", MAX_SPREAD_CENTS))
    if spread is not None and spread > max_spread:
        return PlaybookDecision(False, "pass", 0, f"spread {spread}¢ > {max_spread}¢")

    match_cap = MAX_CONTRACTS_PER_MATCH if max_match is None else int(max_match)
    day_cap = MAX_CONTRACTS_PER_DAY if max_day is None else int(max_day)
    remaining_match = match_cap - contracts_this_match
    remaining_day = day_cap - contracts_today
    size = size_for_tier(tier, remaining_match, remaining_day, rules)
    if size <= 0:
        return PlaybookDecision(False, "pass", 0, "match or daily contract cap reached")

    stop_drop = int(_rule(rules, "stop_price_drop_cents", STOP_PRICE_DROP_CENTS))
    stop_price = max(1, no_ask - stop_drop)
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
    rules: Optional[dict[str, Any]] = None,
) -> PlaybookDecision:
    if not has_position:
        return PlaybookDecision(False, "hold", 0, "no open position")
    if bool(_rule(rules, "flatten_on_goal", FLATTEN_ON_GOAL)) and event_type == "goal":
        return PlaybookDecision(True, "flatten", 0, "flatten on goal")
    if event_type == "full_time":
        return PlaybookDecision(True, "flatten", 0, "flatten at full-time")
    flatten_at = int(_rule(rules, "flatten_rem_at", FLATTEN_REM_AT))
    ival = _as_int_rem(rem, strike) if rem is not None else None
    if ival is not None and ival <= flatten_at:
        return PlaybookDecision(True, "flatten", 0, f"rem {ival} -> {flatten_at} stop")
    if rem is not None and rem < 0:
        return PlaybookDecision(True, "flatten", 0, "over landed; rem negative")
    stop_drop = int(_rule(rules, "stop_price_drop_cents", STOP_PRICE_DROP_CENTS))
    if (
        entry_price is not None
        and no_mid is not None
        and (entry_price - no_mid) >= stop_drop
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
