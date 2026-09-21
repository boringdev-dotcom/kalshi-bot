"""Idempotent order execution with paper mode default."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kalshi_bot.kalshi.rest import KalshiClient
from kalshi_bot.playbook import MAX_CONTRACTS_PER_DAY, MAX_CONTRACTS_PER_MATCH
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)


def idempotency_key(game_id: str, ticker: str, event_id: Optional[int], action: str) -> str:
    return f"{game_id}:{ticker}:{event_id or 0}:{action}"


def contracts_used(store: Store, game_id: str, day_start_ts: int) -> tuple[int, int]:
    match_count = sum(
        row["count"]
        for row in store.orders_for_game(game_id)
        if row["action"] == "buy_no" and row["status"] in {"submitted", "resting", "filled", "paper"}
    )
    day_count = sum(
        row["count"]
        for row in store.orders_today(day_start_ts)
        if row["action"] == "buy_no" and row["status"] in {"submitted", "resting", "filled", "paper"}
    )
    return match_count, day_count


def remaining_caps(store: Store, game_id: str, day_start_ts: int) -> tuple[int, int]:
    used_match, used_day = contracts_used(store, game_id, day_start_ts)
    return MAX_CONTRACTS_PER_MATCH - used_match, MAX_CONTRACTS_PER_DAY - used_day


def submit_buy_no(
    store: Store,
    client: Optional[KalshiClient],
    *,
    game_id: str,
    ticker: str,
    event_id: Optional[int],
    count: int,
    price: int,
    reason: str,
    paper: bool,
) -> dict[str, Any]:
    key = idempotency_key(game_id, ticker, event_id, "buy_no")
    existing = store.find_order(key)
    if existing:
        logger.info("Idempotent skip buy_no %s", key)
        return existing

    order = {
        "idempotency_key": key,
        "game_id": game_id,
        "market_ticker": ticker,
        "event_id": event_id,
        "side": "no",
        "action": "buy_no",
        "count": count,
        "price": price,
        "paper": paper,
        "status": "paper" if paper else "submitted",
        "reason": reason,
    }
    kalshi_id = None
    if not paper:
        if client is None:
            raise RuntimeError("Live mode requires a Kalshi client")
        result = client.create_order(
            ticker=ticker,
            side="no",
            action="buy",
            count=count,
            price=price,
            client_order_id=key.replace(":", "-")[:64],
        )
        kalshi_id = (result.get("order") or result).get("order_id")
        order["kalshi_order_id"] = kalshi_id
        order["status"] = "submitted"
    store.add_order(order)
    position = store.get_position(ticker) or {
        "market_ticker": ticker,
        "game_id": game_id,
        "side": "no",
        "count": 0,
        "avg_price": price,
        "paper": paper,
        "stopped": False,
    }
    prev = position["count"]
    new_count = prev + count
    prev_avg = position.get("avg_price") or price
    position["count"] = new_count
    position["avg_price"] = int(round(((prev_avg * prev) + (price * count)) / new_count))
    position["paper"] = paper
    store.upsert_position(position)
    logger.info("buy_no %s %sx @ %s¢ paper=%s order=%s", ticker, count, price, paper, kalshi_id)
    return store.find_order(key) or order


def flatten_position(
    store: Store,
    client: Optional[KalshiClient],
    *,
    game_id: str,
    ticker: str,
    event_id: Optional[int],
    reason: str,
    paper: bool,
    mark_stopped: bool = True,
) -> Optional[dict[str, Any]]:
    key = idempotency_key(game_id, ticker, event_id, "flatten")
    existing = store.find_order(key)
    if existing:
        return existing
    position = store.get_position(ticker)
    if not position or position["count"] <= 0:
        return None

    count = position["count"]
    price = max(1, 100 - (position.get("avg_price") or 50))
    order = {
        "idempotency_key": key,
        "game_id": game_id,
        "market_ticker": ticker,
        "event_id": event_id,
        "side": "no",
        "action": "flatten",
        "count": count,
        "price": price,
        "paper": paper,
        "status": "paper" if paper else "submitted",
        "reason": reason,
    }
    if not paper:
        if client is None:
            raise RuntimeError("Live mode requires a Kalshi client")
        result = client.create_order(
            ticker=ticker,
            side="no",
            action="sell",
            count=count,
            price=price,
            client_order_id=key.replace(":", "-")[:64],
        )
        order["kalshi_order_id"] = (result.get("order") or result).get("order_id")
    store.add_order(order)
    store.upsert_position(
        {
            "market_ticker": ticker,
            "game_id": game_id,
            "side": "no",
            "count": 0,
            "avg_price": position.get("avg_price"),
            "paper": paper,
            "stopped": mark_stopped,
        }
    )
    logger.info("flatten %s %sx reason=%s paper=%s", ticker, count, reason, paper)
    return store.find_order(key) or order
