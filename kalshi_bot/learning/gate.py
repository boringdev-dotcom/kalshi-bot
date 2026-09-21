"""Deterministic playbook gate. Runs before Grok. Hard blocks skip the LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from kalshi_bot.decisions import WOULD_FLATTEN, WOULD_SKIP, record_decision
from kalshi_bot.execution import flatten_position
from kalshi_bot.learning.playbook_version import active_rules, current_version_number
from kalshi_bot.limits import cap_usage, get_limits
from kalshi_bot.playbook import evaluate_entry, evaluate_exit, is_1h_total
from kalshi_bot.store import Store


@dataclass
class GateResult:
    skip_llm: bool
    reason: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    blocked: list[dict[str, Any]] = field(default_factory=list)
    allowed: list[dict[str, Any]] = field(default_factory=list)


def _flatten_open(store: Store, game: dict[str, Any], event: dict[str, Any], payload: dict[str, Any], paper: bool) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    event_type = (payload.get("event") or event or {}).get("event_type") or ""
    markets = {m["ticker"]: m for m in payload.get("markets") or []}
    rules = active_rules(store)
    for position in store.positions_for_game(game["id"]):
        if position["count"] <= 0:
            continue
        market = markets.get(position["market_ticker"], {})
        no_mid = None
        if market.get("no_bid") is not None and market.get("no_ask") is not None:
            no_mid = (market["no_bid"] + market["no_ask"]) / 2
        decision = evaluate_exit(
            event_type=event_type,
            rem=market.get("rem"),
            prior_rem=market.get("rem"),
            no_mid=no_mid,
            entry_price=position.get("avg_price"),
            has_position=True,
            strike=market.get("strike"),
            rules=rules,
        )
        if decision.allowed and decision.action == "flatten":
            flatten_px = int(no_mid) if no_mid is not None else None
            result = flatten_position(
                store,
                None,
                game_id=game["id"],
                ticker=position["market_ticker"],
                event_id=event.get("id"),
                reason=decision.reason,
                paper=paper,
                price=flatten_px,
            )
            record_decision(
                store,
                game_id=game["id"],
                event_id=event.get("id"),
                agent="kalshi",
                market_ticker=position["market_ticker"],
                action=WOULD_FLATTEN,
                size=position["count"],
                price=flatten_px,
                rem=market.get("rem"),
                reason=f"gate: {decision.reason}",
                paper=paper,
                game=game,
                market=market,
                state=payload.get("state"),
                playbook_version=current_version_number(store),
                brief_id=(payload.get("brief_id")),
            )
            if result:
                actions.append(result)
    return actions


def apply_gate(
    store: Store,
    game: dict[str, Any],
    event: dict[str, Any],
    payload: dict[str, Any],
    *,
    paper: bool = True,
    day_start: int = 0,
) -> GateResult:
    """Hard-block minute / rem / tier / 1H / caps / stopped / price before any Grok call."""
    rules = active_rules(store)
    limits = get_limits(store)
    usage = cap_usage(store, game["id"], day_start)
    used_match = usage["used_match"]
    used_day = usage["used_today"]
    state = payload.get("state") or {}
    minute = int(state.get("minute") or game.get("minute") or 0)
    phase = state.get("phase") or game.get("phase") or "second_half"
    paused = store.is_paused()
    flatten_actions = _flatten_open(store, game, event, payload, paper)

    if paused:
        record_decision(
            store,
            game_id=game["id"],
            event_id=event.get("id"),
            agent="kalshi",
            action=WOULD_SKIP,
            reason=f"gate: {store.pause_reason() or 'paused'}",
            paper=paper,
            game=game,
            state=state,
            playbook_version=current_version_number(store),
            brief_id=payload.get("brief_id"),
        )
        return GateResult(True, store.pause_reason() or "paused", actions=flatten_actions)

    blocked: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []
    for market in payload.get("markets") or []:
        ticker = market.get("ticker")
        position = store.get_position(ticker) if ticker else None
        if position and position["count"] > 0:
            continue
        decision = evaluate_entry(
            minute=minute,
            rem=float(market["rem"]) if market.get("rem") is not None else 99.0,
            no_ask=market.get("no_ask"),
            no_bid=market.get("no_bid"),
            league=game.get("league"),
            already_stopped=bool(position and position.get("stopped")),
            contracts_this_match=used_match,
            contracts_today=used_day,
            phase=phase,
            strike=market.get("strike"),
            is_1h=is_1h_total(
                ticker=ticker,
                series=market.get("series_ticker"),
                title=market.get("title"),
            ),
            max_match=limits["max_contracts_per_match"],
            max_day=limits["max_contracts_per_day"],
            rules=rules,
        )
        if decision.allowed:
            allowed.append({"market": market, "reason": decision.reason, "size": decision.size})
        else:
            blocked.append({"market": market, "reason": decision.reason})

    if allowed:
        return GateResult(False, "entry window open", actions=flatten_actions, blocked=blocked, allowed=allowed)

    brief_id = payload.get("brief_id")
    version = current_version_number(store)
    for item in blocked:
        market = item["market"]
        record_decision(
            store,
            game_id=game["id"],
            event_id=event.get("id"),
            agent="kalshi",
            market_ticker=market.get("ticker"),
            action=WOULD_SKIP,
            size=0,
            price=market.get("no_ask"),
            rem=market.get("rem"),
            reason=f"gate: {item['reason']}",
            paper=paper,
            game=game,
            market=market,
            state=state,
            playbook_version=version,
            brief_id=brief_id,
        )
    reason = blocked[0]["reason"] if blocked else "no markets"
    return GateResult(True, reason, actions=flatten_actions, blocked=blocked, allowed=allowed)
