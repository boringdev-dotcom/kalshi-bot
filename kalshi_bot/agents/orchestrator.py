"""One-shot Pundit then Kalshi invocation per material event."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from kalshi_bot.agents.grok import GrokClient
from kalshi_bot.agents.kalshi_agent import run_kalshi_agent
from kalshi_bot.agents.pundit import run_pundit
from kalshi_bot.agents.tools import ToolContext
from kalshi_bot.config import Settings
from kalshi_bot.kalshi.rest import KalshiClient
from kalshi_bot.learning.brief import latest_brief
from kalshi_bot.learning.gate import apply_gate
from kalshi_bot.learning.playbook_version import current_version_number, ensure_playbook_v1
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)

NotifyFn = Callable[[str], None]


def day_start_ts(now: Optional[int] = None) -> int:
    moment = datetime.fromtimestamp(now or int(datetime.now(tz=timezone.utc).timestamp()), tz=timezone.utc)
    start = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)
    return int(start.timestamp())


def handle_event(
    settings: Settings,
    store: Store,
    client: Optional[KalshiClient],
    game: dict[str, Any],
    event_row: dict[str, Any],
    payload: dict[str, Any],
    notify: Optional[NotifyFn] = None,
) -> dict[str, Any]:
    """Run both agents once. Learning never runs here; only the precompiled brief and gate."""
    ensure_playbook_v1(store)
    paper = store.is_paper()
    paused = store.is_paused()
    start = day_start_ts()
    payload = dict(payload)
    brief = latest_brief(store, game["id"])
    if brief:
        payload["memory_brief"] = brief.get("text") or ""
        payload["brief_id"] = brief.get("id")
        payload["playbook_version"] = brief.get("playbook_version") or current_version_number(store)
    else:
        payload["playbook_version"] = current_version_number(store)
    gated = apply_gate(store, game, event_row, payload, paper=paper, day_start=start)
    if gated.skip_llm:
        logger.info("Playbook gate skipped LLM for %s: %s", game.get("id"), gated.reason)
        return {"verdicts": [], "actions": gated.actions, "gated": True, "gate_reason": gated.reason}

    grok = GrokClient(settings, store)
    ctx_pundit = ToolContext(store, client, game, event_row, "pundit", paper, paused, start)
    verdicts = run_pundit(grok, store, ctx_pundit, payload)
    if notify:
        lines = [f"Pundit {game['home_team']} vs {game['away_team']} ({event_row.get('event_type')})"]
        for verdict in verdicts:
            lines.append(f"• {verdict.ticker}: {verdict.verdict} — {verdict.reason}")
        notify("\n".join(lines))

    ctx_kalshi = ToolContext(store, client, game, event_row, "kalshi", paper, paused, start)
    actions = run_kalshi_agent(grok, store, ctx_kalshi, payload, verdicts)
    if notify and actions:
        bits = [f"Kalshi actions ({'paper' if paper else 'live'}):"]
        for action in actions:
            bits.append(f"• {action.get('action') or action.get('type')} {action.get('market_ticker') or action.get('ticker')} {action.get('reason') or action.get('status')}")
        notify("\n".join(bits))
    return {"verdicts": [v.__dict__ for v in verdicts], "actions": actions}
