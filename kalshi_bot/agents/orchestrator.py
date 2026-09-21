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
    """Run both agents once. No long-lived loops."""
    grok = GrokClient(settings, store)
    paper = store.is_paper()
    paused = store.is_paused()
    ctx_pundit = ToolContext(store, client, game, event_row, "pundit", paper, paused, day_start_ts())
    verdicts = run_pundit(grok, store, ctx_pundit, payload)
    if notify:
        lines = [f"Pundit {game['home_team']} vs {game['away_team']} ({event_row.get('event_type')})"]
        for verdict in verdicts:
            lines.append(f"• {verdict.ticker}: {verdict.verdict} — {verdict.reason}")
        notify("\n".join(lines))

    ctx_kalshi = ToolContext(store, client, game, event_row, "kalshi", paper, paused, day_start_ts())
    actions = run_kalshi_agent(grok, store, ctx_kalshi, payload, verdicts)
    if notify and actions:
        bits = [f"Kalshi actions ({'paper' if paper else 'live'}):"]
        for action in actions:
            bits.append(f"• {action.get('action') or action.get('type')} {action.get('market_ticker') or action.get('ticker')} {action.get('reason') or action.get('status')}")
        notify("\n".join(bits))
    return {"verdicts": [v.__dict__ for v in verdicts], "actions": actions}
