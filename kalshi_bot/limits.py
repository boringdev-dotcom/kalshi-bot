"""Editable contract and loss caps. Paper-first; auto-pause on loss."""

from __future__ import annotations

from typing import Any, Optional

from kalshi_bot.playbook import MAX_CONTRACTS_PER_DAY, MAX_CONTRACTS_PER_MATCH
from kalshi_bot.store import Store

DEFAULT_MAX_MATCH = MAX_CONTRACTS_PER_MATCH
DEFAULT_MAX_DAY = MAX_CONTRACTS_PER_DAY
DEFAULT_MAX_DAILY_LOSS_CENTS = 2500  # $25


def _int_control(store: Store, key: str, default: int) -> int:
    raw = store.get_control(key)
    if raw is None or raw == "":
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def get_limits(store: Store) -> dict[str, int]:
    return {
        "max_contracts_per_match": _int_control(store, "max_contracts_per_match", DEFAULT_MAX_MATCH),
        "max_contracts_per_day": _int_control(store, "max_contracts_per_day", DEFAULT_MAX_DAY),
        "max_daily_loss_cents": _int_control(store, "max_daily_loss_cents", DEFAULT_MAX_DAILY_LOSS_CENTS),
    }


def ensure_default_limits(store: Store) -> dict[str, int]:
    limits = get_limits(store)
    if store.get_control("max_contracts_per_match") is None:
        store.set_control("max_contracts_per_match", str(limits["max_contracts_per_match"]))
    if store.get_control("max_contracts_per_day") is None:
        store.set_control("max_contracts_per_day", str(limits["max_contracts_per_day"]))
    if store.get_control("max_daily_loss_cents") is None:
        store.set_control("max_daily_loss_cents", str(limits["max_daily_loss_cents"]))
    return get_limits(store)


def set_limits(
    store: Store,
    *,
    max_contracts_per_match: Optional[int] = None,
    max_contracts_per_day: Optional[int] = None,
    max_daily_loss_cents: Optional[int] = None,
) -> dict[str, int]:
    if max_contracts_per_match is not None:
        store.set_control("max_contracts_per_match", str(max(1, int(max_contracts_per_match))))
    if max_contracts_per_day is not None:
        store.set_control("max_contracts_per_day", str(max(1, int(max_contracts_per_day))))
    if max_daily_loss_cents is not None:
        store.set_control("max_daily_loss_cents", str(max(0, int(max_daily_loss_cents))))
    return get_limits(store)


def _mark_price(position: dict[str, Any], market: Optional[dict[str, Any]]) -> int:
    if market:
        if market.get("no_bid") is not None:
            return int(market["no_bid"])
        if market.get("no_ask") is not None:
            return int(market["no_ask"])
    return int(position.get("avg_price") or 0)


def _settle_no(strike: Optional[float], goals: int, avg_price: int, count: int) -> int:
    """P&L in cents for a held-to-settlement No. Under wins when goals <= strike."""
    if strike is None:
        return 0
    if float(goals) > float(strike):
        return -int(avg_price) * int(count)
    return (100 - int(avg_price)) * int(count)


def session_pnl(store: Store, day_start_ts: int) -> dict[str, Any]:
    """Realized + unrealized P&L in cents for today's paper (and live) activity."""
    orders = store.orders_today(day_start_ts)
    realized = 0
    lots: dict[str, list[dict[str, Any]]] = {}
    for order in sorted(orders, key=lambda o: o.get("id") or 0):
        ticker = order.get("market_ticker")
        if not ticker:
            continue
        if order["action"] == "buy_no":
            lots.setdefault(ticker, []).append(
                {"count": int(order["count"]), "price": int(order.get("price") or 0)}
            )
        elif order["action"] == "flatten":
            remaining = int(order["count"])
            exit_px = int(order.get("price") or 0)
            bucket = lots.setdefault(ticker, [])
            while remaining > 0 and bucket:
                lot = bucket[0]
                take = min(remaining, lot["count"])
                realized += (exit_px - lot["price"]) * take
                lot["count"] -= take
                remaining -= take
                if lot["count"] <= 0:
                    bucket.pop(0)

    unrealized = 0
    open_detail = []
    for position in store.open_positions():
        if position["count"] <= 0:
            continue
        market = store.get_market(position["market_ticker"])
        mark = _mark_price(position, market)
        avg = int(position.get("avg_price") or mark)
        count = int(position["count"])
        game = store.get_game(position["game_id"]) or {}
        if game.get("status") in {"finished", "replay"} and game.get("phase") == "full_time":
            goals = int(game.get("home_goals") or 0) + int(game.get("away_goals") or 0)
            strike = (market or {}).get("strike")
            chunk = _settle_no(strike, goals, avg, count)
            realized += chunk
            continue
        chunk = (mark - avg) * count
        unrealized += chunk
        open_detail.append(
            {
                "ticker": position["market_ticker"],
                "count": count,
                "avg_price": avg,
                "mark": mark,
                "pnl_cents": chunk,
            }
        )

    total = realized + unrealized
    return {
        "realized_cents": realized,
        "unrealized_cents": unrealized,
        "total_cents": total,
        "open": open_detail,
    }


def enforce_loss_cap(store: Store, day_start_ts: int) -> dict[str, Any]:
    limits = get_limits(store)
    pnl = session_pnl(store, day_start_ts)
    cap = limits["max_daily_loss_cents"]
    breached = pnl["total_cents"] <= -cap
    if breached:
        store.set_paused(True)
        dollars = cap / 100.0
        store.set_pause_reason(f"daily loss cap (${dollars:.2f})")
    return {
        **pnl,
        "cap_cents": cap,
        "breached": breached,
        "paused": store.is_paused(),
        "pause_reason": store.pause_reason(),
    }


def cap_usage(store: Store, game_id: str, day_start_ts: int) -> dict[str, Any]:
    from kalshi_bot.execution import contracts_used

    limits = get_limits(store)
    used_match, used_day = contracts_used(store, game_id, day_start_ts)
    return {
        "per_match": limits["max_contracts_per_match"],
        "per_day": limits["max_contracts_per_day"],
        "used_match": used_match,
        "used_today": used_day,
        "remaining_match": limits["max_contracts_per_match"] - used_match,
        "remaining_day": limits["max_contracts_per_day"] - used_day,
        "max_daily_loss_cents": limits["max_daily_loss_cents"],
    }
