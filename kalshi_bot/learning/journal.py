"""Feature snapshots, full-time outcomes, counterfactual P&L, and process grades."""

from __future__ import annotations

import time
from typing import Any, Optional

from kalshi_bot.playbook import evaluate_entry, is_1h_total, league_tier
from kalshi_bot.store import Store

WOULD_PLACE = "would-place"
WOULD_SKIP = "would-skip"
WOULD_FLATTEN = "would-flatten"

SKILL = "skill"
LUCK = "luck"
ERROR = "error"
UNLUCKY = "unlucky"


def snapshot_features(
    game: Optional[dict[str, Any]] = None,
    market: Optional[dict[str, Any]] = None,
    state: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    game = game or {}
    market = market or {}
    state = state or {}
    home = int(state.get("home_goals") if state.get("home_goals") is not None else game.get("home_goals") or 0)
    away = int(state.get("away_goals") if state.get("away_goals") is not None else game.get("away_goals") or 0)
    minute = int(state.get("minute") if state.get("minute") is not None else game.get("minute") or 0)
    rem = market.get("rem")
    tempo = round((home + away) / max(minute, 1) * 90, 3)
    return {
        "league": game.get("league"),
        "tier": game.get("league_tier") or league_tier(game.get("league")),
        "strike": market.get("strike"),
        "score": f"{home}-{away}",
        "home_goals": home,
        "away_goals": away,
        "total_goals": home + away,
        "minute": minute,
        "rem": rem,
        "tempo": tempo,
        "red_cards": int(state.get("red_cards") if state.get("red_cards") is not None else game.get("red_cards") or 0),
        "no_ask": market.get("no_ask"),
        "no_bid": market.get("no_bid"),
        "no_depth": market.get("no_depth"),
        "phase": state.get("phase") or game.get("phase"),
        "is_1h": is_1h_total(
            ticker=market.get("ticker"),
            series=market.get("series_ticker"),
            title=market.get("title"),
        ),
        **(extra or {}),
    }


def no_won(strike: Optional[float], final_goals: int) -> Optional[bool]:
    if strike is None:
        return None
    return float(final_goals) <= float(strike)


def settlement_pnl_cents(price: Optional[int], size: int, won: bool) -> int:
    px = int(price or 0)
    qty = max(0, int(size))
    if qty <= 0:
        return 0
    if won:
        return (100 - px) * qty
    return -px * qty


def process_grade(*, placed: bool, should_place: bool, won: Optional[bool], flatten: bool = False) -> str:
    """Separate process from outcome: skill / luck / error / unlucky."""
    if flatten:
        return SKILL
    if won is None:
        return SKILL if placed == should_place else ERROR
    good_process = placed == should_place
    good_outcome = won if placed else (not won)
    if good_process and good_outcome:
        return SKILL
    if good_process and not good_outcome:
        return UNLUCKY
    if (not good_process) and good_outcome:
        return LUCK
    return ERROR


def playbook_would_allow(features: Optional[dict[str, Any]], game: Optional[dict[str, Any]] = None) -> bool:
    feats = features or {}
    rem = feats.get("rem")
    if rem is None:
        return False
    decision = evaluate_entry(
        minute=int(feats.get("minute") or 0),
        rem=float(rem),
        no_ask=feats.get("no_ask"),
        no_bid=feats.get("no_bid"),
        league=feats.get("league") or (game or {}).get("league"),
        already_stopped=bool(feats.get("already_stopped")),
        contracts_this_match=int(feats.get("contracts_this_match") or 0),
        contracts_today=int(feats.get("contracts_today") or 0),
        phase=str(feats.get("phase") or "second_half"),
        strike=feats.get("strike"),
        is_1h=bool(feats.get("is_1h")),
    )
    return bool(decision.allowed)


def _decision_minute(row: dict[str, Any], events: list[dict[str, Any]]) -> int:
    feats = row.get("features") or {}
    if feats.get("minute") is not None:
        return int(feats["minute"])
    event_id = row.get("event_id")
    for event in events:
        if event.get("id") == event_id:
            return int(event.get("minute") or 0)
    return 0


def _goals_after(events: list[dict[str, Any]], minute: int) -> int:
    return sum(1 for event in events if event.get("event_type") == "goal" and int(event.get("minute") or 0) > minute)


def _flatten_after(decisions: list[dict[str, Any]], row: dict[str, Any]) -> Optional[dict[str, Any]]:
    ticker = row.get("market_ticker")
    if not ticker:
        return None
    for later in decisions:
        if later.get("id") <= row.get("id"):
            continue
        if later.get("market_ticker") == ticker and later.get("action") == WOULD_FLATTEN:
            return later
    return None


def attach_outcomes(store: Store, game_id: str) -> list[dict[str, Any]]:
    """Attach settlement, realized / counterfactual P&L, and goal-after counts."""
    game = store.get_game(game_id) or {}
    events = store.events_for_game(game_id)
    decisions = store.decisions_for_game(game_id)
    final_goals = int(game.get("home_goals") or 0) + int(game.get("away_goals") or 0)
    now = int(time.time())
    updated: list[dict[str, Any]] = []
    for row in decisions:
        feats = row.get("features") or {}
        market = store.get_market(row["market_ticker"]) if row.get("market_ticker") else None
        strike = feats.get("strike")
        if strike is None and market:
            strike = market.get("strike")
        minute = _decision_minute(row, events)
        goals_after = _goals_after(events, minute)
        won = no_won(strike, final_goals)
        action = row.get("action")
        price = row.get("price")
        size = int(row.get("size") or 0)
        realized = 0
        counterfactual = 0
        outcome = "unknown"
        flatten = _flatten_after(decisions, row)
        if action == WOULD_PLACE:
            qty = size or 1
            if flatten and flatten.get("price") is not None and price is not None:
                realized = (int(flatten["price"]) - int(price)) * qty
            elif won is not None:
                realized = settlement_pnl_cents(price, qty, won)
            counterfactual = 0
            outcome = "won" if realized > 0 else "lost" if realized < 0 else "flat"
        elif action == WOULD_SKIP:
            qty = size or 1
            realized = 0
            if won is not None and price is not None:
                counterfactual = settlement_pnl_cents(price, qty, won)
            # Skip "won" when placing would have lost.
            if won is False:
                outcome = "won"
            elif won is True:
                outcome = "lost"
            else:
                outcome = "unknown"
        elif action == WOULD_FLATTEN:
            if price is not None and size:
                # Flatten P&L is vs entry; leave 0 if we cannot pair.
                realized = 0
            outcome = "flat"
        store.update_decision(
            int(row["id"]),
            outcome=outcome,
            realized_pnl_cents=int(realized),
            counterfactual_pnl_cents=int(counterfactual),
            goals_after=goals_after,
            settled=1,
            graded_at=now,
        )
        row = {
            **row,
            "outcome": outcome,
            "realized_pnl_cents": int(realized),
            "counterfactual_pnl_cents": int(counterfactual),
            "goals_after": goals_after,
            "settled": 1,
            "graded_at": now,
            "no_won": won,
        }
        updated.append(row)
    return updated


def grade_decision(row: dict[str, Any], game: Optional[dict[str, Any]] = None) -> str:
    action = row.get("action")
    if action == WOULD_FLATTEN:
        return SKILL
    feats = row.get("features") or {}
    should = playbook_would_allow(feats, game)
    placed = action == WOULD_PLACE
    won = row.get("no_won")
    if won is None:
        strike = feats.get("strike")
        final = int((game or {}).get("home_goals") or 0) + int((game or {}).get("away_goals") or 0)
        won = no_won(strike, final)
    return process_grade(placed=placed, should_place=should, won=won, flatten=False)


def grade_game(store: Store, game_id: str) -> list[dict[str, Any]]:
    """Full-time grading. Must run off the event path."""
    game = store.get_game(game_id) or {}
    rows = attach_outcomes(store, game_id)
    graded: list[dict[str, Any]] = []
    for row in rows:
        label = grade_decision(row, game)
        store.update_decision(int(row["id"]), process_grade=label)
        row["process_grade"] = label
        graded.append(row)
    return graded
