"""Persist paper would-place / would-skip / would-flatten rows."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from kalshi_bot.store import Store

WOULD_PLACE = "would-place"
WOULD_SKIP = "would-skip"
WOULD_FLATTEN = "would-flatten"


def record_decision(
    store: Store,
    *,
    game_id: str,
    action: str,
    reason: str,
    agent: str = "kalshi",
    event_id: Optional[int] = None,
    market_ticker: Optional[str] = None,
    size: int = 0,
    price: Optional[int] = None,
    rem: Optional[float] = None,
    paper: bool = True,
) -> int:
    return store.add_decision(
        {
            "game_id": game_id,
            "event_id": event_id,
            "agent": agent,
            "market_ticker": market_ticker,
            "action": action,
            "size": size,
            "price": price,
            "rem": rem,
            "reason": reason,
            "paper": paper,
        }
    )


def pundit_action(verdict: str) -> str:
    if verdict == "real_bet":
        return WOULD_PLACE
    if verdict == "flatten_hint":
        return WOULD_FLATTEN
    return WOULD_SKIP


def persist_pundit_verdicts(
    store: Store,
    game_id: str,
    event_id: Optional[int],
    verdicts: list[Any],
    paper: bool = True,
) -> None:
    for verdict in verdicts:
        ticker = getattr(verdict, "ticker", None) or (verdict.get("ticker") if isinstance(verdict, dict) else None)
        label = getattr(verdict, "verdict", None) or (verdict.get("verdict") if isinstance(verdict, dict) else "pass")
        reason = getattr(verdict, "reason", None) or (verdict.get("reason") if isinstance(verdict, dict) else "")
        size = getattr(verdict, "size_hint", None)
        if size is None and isinstance(verdict, dict):
            size = verdict.get("size_hint") or 0
        rem = getattr(verdict, "rem", None)
        if rem is None and isinstance(verdict, dict):
            rem = verdict.get("rem")
        raw = asdict(verdict) if is_dataclass(verdict) else verdict
        store.add_verdict(game_id, "pundit", event_id, ticker, label, int(size or 0), reason or "", raw)
        record_decision(
            store,
            game_id=game_id,
            event_id=event_id,
            agent="pundit",
            market_ticker=ticker,
            action=pundit_action(label or "pass"),
            size=int(size or 0),
            rem=rem,
            reason=reason or "",
            paper=paper,
        )
