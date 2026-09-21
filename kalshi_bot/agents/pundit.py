"""Pundit agent: watch / real_bet / pass / flatten_hint. Read-only tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from kalshi_bot.agents.grok import GrokClient, extract_json, message_content
from kalshi_bot.agents.tools import PUNDIT_TOOLS, ToolContext, dispatch
from kalshi_bot.models import PunditVerdict
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)

SYSTEM = """You are Soccer Pundit for Kalshi under-No totals.
You score each board watch / real_bet / pass / flatten_hint from tempo, rem, and league tier.
Rules:
- Read-only. Never invent stats. If a tool returns missing data, say so.
- Under-No means buying No on an over-X.5 goals market (betting the under).
- rem = strike - current total goals. Low rem late in a quiet game favors No.
- Return ONLY JSON: {"notes": "...", "markets": [{"ticker": "...", "verdict": "watch|real_bet|pass|flatten_hint", "size_hint": 0, "reason": "..."}]}.
- size_hint is a suggested contract count, 0 if not real_bet.
"""


def run_pundit(
    grok: GrokClient,
    store: Store,
    ctx: ToolContext,
    payload: dict[str, Any],
) -> list[PunditVerdict]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload)},
    ]
    if not grok.available():
        logger.warning("XAI_API_KEY missing; Pundit skipped")
        return _heuristic(payload)

    for _ in range(8):
        data = grok.complete(messages, PUNDIT_TOOLS, agent="pundit", game_id=ctx.game["id"])
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        messages.append(message)
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            text = message_content(message)
            try:
                parsed = extract_json(text)
            except Exception:
                logger.exception("Pundit JSON parse failed: %s", text[:400])
                return _heuristic(payload)
            notes = parsed.get("notes") or text
            store.set_memory(ctx.game["id"], "pundit", notes)
            verdicts = []
            for item in parsed.get("markets") or []:
                verdict = PunditVerdict(
                    ticker=item.get("ticker") or "",
                    verdict=item.get("verdict") or "pass",
                    size_hint=int(item.get("size_hint") or 0),
                    reason=item.get("reason") or "",
                    strike=item.get("strike"),
                    rem=item.get("rem"),
                )
                verdicts.append(verdict)
                store.add_verdict(
                    ctx.game["id"],
                    "pundit",
                    ctx.event.get("id"),
                    verdict.ticker,
                    verdict.verdict,
                    verdict.size_hint,
                    verdict.reason,
                    item,
                )
            return verdicts
        for call in tool_calls:
            fn = call.get("function") or {}
            args = fn.get("arguments") or "{}"
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            result = dispatch(ctx, fn.get("name"), args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": result,
                }
            )
    return _heuristic(payload)


def _heuristic(payload: dict[str, Any]) -> list[PunditVerdict]:
    """Fallback when Grok is unavailable. Still event-triggered, no extra API cost."""
    verdicts = []
    minute = int((payload.get("state") or {}).get("minute") or 0)
    for market in payload.get("markets") or []:
        rem = market.get("rem")
        ask = market.get("no_ask")
        verdict = "pass"
        reason = "heuristic fallback (no XAI_API_KEY)"
        if rem is not None and rem < 0:
            verdict = "flatten_hint"
            reason = "over landed"
        elif minute >= 60 and rem is not None and rem <= 2 and ask and 80 <= ask <= 92:
            verdict = "real_bet"
            reason = f"late quiet board rem={rem} ask={ask}"
        elif minute >= 55 and rem is not None and rem <= 2.5:
            verdict = "watch"
            reason = f"approaching window rem={rem}"
        verdicts.append(
            PunditVerdict(
                ticker=market.get("ticker") or "",
                verdict=verdict,
                size_hint=1 if verdict == "real_bet" else 0,
                reason=reason,
                strike=market.get("strike"),
                rem=rem,
            )
        )
    return verdicts
