"""Kalshi trader agent: apply playbook and place or flatten."""

from __future__ import annotations

import json
import logging
from typing import Any

from kalshi_bot.agents.grok import GrokClient, extract_json, message_content
from kalshi_bot.agents.tools import KALSHI_TOOLS, ToolContext, dispatch
from kalshi_bot.execution import flatten_position, remaining_caps, submit_buy_no
from kalshi_bot.models import PunditVerdict
from kalshi_bot.playbook import (
    MAX_CONTRACTS_PER_DAY,
    MAX_CONTRACTS_PER_MATCH,
    constraints_text,
    evaluate_entry,
    evaluate_exit,
)
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)

SYSTEM = """You are the Kalshi under-No trader.
You receive a Pundit verdict plus hard playbook constraints.
You may buy No, flatten, or do nothing. Explain every action.
Never exceed playbook size/price/rem/minute caps. Prefer flatten on goal or rem drop.
If trading is paused, do not place orders.
If paper mode is true, tools still journal paper fills — that is correct.
Return JSON: {"notes": "...", "actions": [{"type": "buy_no|flatten|hold", "ticker": "...", "count": 0, "price": 0, "reason": "..."}]}.
"""


def run_kalshi_agent(
    grok: GrokClient,
    store: Store,
    ctx: ToolContext,
    payload: dict[str, Any],
    verdicts: list[PunditVerdict],
) -> list[dict[str, Any]]:
    _apply_hard_stops(store, ctx, payload)

    user = {
        **payload,
        "pundit": [v.__dict__ for v in verdicts],
        "playbook": constraints_text(),
        "paper": ctx.paper,
        "paused": ctx.paused,
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(user)},
    ]
    if not grok.available():
        logger.warning("XAI_API_KEY missing; Kalshi agent using playbook only")
        actions = _playbook_only(store, ctx, payload, verdicts)
        store.set_memory(ctx.game["id"], "kalshi", "playbook-only fallback (no XAI_API_KEY)")
        return actions

    for _ in range(8):
        data = grok.complete(messages, KALSHI_TOOLS, agent="kalshi", game_id=ctx.game["id"])
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        messages.append(message)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            text = message_content(message)
            try:
                parsed = extract_json(text)
            except Exception:
                parsed = {"notes": text, "actions": []}
            store.set_memory(ctx.game["id"], "kalshi", parsed.get("notes") or text)
            store.add_verdict(
                ctx.game["id"],
                "kalshi",
                ctx.event.get("id"),
                None,
                None,
                None,
                parsed.get("notes") or text,
                parsed,
            )
            if not ctx.actions:
                return _playbook_only(store, ctx, payload, verdicts)
            return ctx.actions
        for call in tool_calls:
            fn = call.get("function") or {}
            args = fn.get("arguments") or "{}"
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            result = dispatch(ctx, fn.get("name"), args)
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": result})
    return ctx.actions or _playbook_only(store, ctx, payload, verdicts)


def _apply_hard_stops(store: Store, ctx: ToolContext, payload: dict[str, Any]) -> None:
    event_type = (payload.get("event") or {}).get("event_type") or ""
    markets = {m["ticker"]: m for m in payload.get("markets") or []}
    for position in store.positions_for_game(ctx.game["id"]):
        if position["count"] <= 0:
            continue
        market = markets.get(position["market_ticker"], {})
        prior_rem = None
        if payload.get("prior_state") and market.get("strike") is not None:
            prior_goals = (payload["prior_state"].get("home_goals") or 0) + (
                payload["prior_state"].get("away_goals") or 0
            )
            prior_rem = float(market["strike"]) - prior_goals
        no_mid = None
        if market.get("no_bid") is not None and market.get("no_ask") is not None:
            no_mid = (market["no_bid"] + market["no_ask"]) / 2
        decision = evaluate_exit(
            event_type=event_type,
            rem=market.get("rem"),
            prior_rem=prior_rem,
            no_mid=no_mid,
            entry_price=position.get("avg_price"),
            has_position=True,
        )
        if decision.allowed and decision.action == "flatten":
            flatten_position(
                store,
                ctx.client,
                game_id=ctx.game["id"],
                ticker=position["market_ticker"],
                event_id=ctx.event.get("id"),
                reason=decision.reason,
                paper=ctx.paper,
            )


def _playbook_only(
    store: Store,
    ctx: ToolContext,
    payload: dict[str, Any],
    verdicts: list[PunditVerdict],
) -> list[dict[str, Any]]:
    if ctx.paused:
        return [{"action": "hold", "reason": "paused"}]
    actions: list[dict[str, Any]] = []
    match_left, day_left = remaining_caps(store, ctx.game["id"], ctx.day_start_ts)
    used_match = MAX_CONTRACTS_PER_MATCH - match_left
    used_day = MAX_CONTRACTS_PER_DAY - day_left
    by_ticker = {v.ticker: v for v in verdicts}
    for market in payload.get("markets") or []:
        ticker = market.get("ticker")
        position = store.get_position(ticker) if ticker else None
        verdict = by_ticker.get(ticker)
        if verdict and verdict.verdict == "flatten_hint" and position and position["count"] > 0:
            result = flatten_position(
                store,
                ctx.client,
                game_id=ctx.game["id"],
                ticker=ticker,
                event_id=ctx.event.get("id"),
                reason=verdict.reason,
                paper=ctx.paper,
            )
            if result:
                actions.append(result)
            continue
        if not verdict or verdict.verdict != "real_bet":
            continue
        if position and position.get("stopped"):
            continue
        if position and position["count"] > 0:
            continue
        decision = evaluate_entry(
            minute=int((payload.get("state") or {}).get("minute") or 0),
            rem=float(market.get("rem") if market.get("rem") is not None else 99),
            no_ask=market.get("no_ask"),
            no_bid=market.get("no_bid"),
            league=ctx.game.get("league"),
            already_stopped=bool(position and position.get("stopped")),
            contracts_this_match=used_match,
            contracts_today=used_day,
            phase=(payload.get("state") or {}).get("phase") or "second_half",
        )
        if not decision.allowed:
            continue
        result = submit_buy_no(
            store,
            ctx.client,
            game_id=ctx.game["id"],
            ticker=ticker,
            event_id=ctx.event.get("id"),
            count=decision.size,
            price=int(market["no_ask"]),
            reason=decision.reason,
            paper=ctx.paper,
        )
        used_match += decision.size
        used_day += decision.size
        actions.append(result)
    store.add_verdict(
        ctx.game["id"],
        "kalshi",
        ctx.event.get("id"),
        None,
        None,
        None,
        "playbook application",
        actions,
    )
    return actions
