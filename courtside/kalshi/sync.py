"""Finding live positions you sold outside Courtside, on Kalshi's own app or site.

Each desk (NBA, soccer) keeps its own positions; this only works out which of them Kalshi no
longer holds because they were sold, and at what price. The desk then books them itself.

Kalshi holding fewer contracts than a desk thinks means some were sold elsewhere. They are
priced from the sell fills Kalshi reports after the position opened. Without such fills nothing
is touched: a market Kalshi has settled also empties the position, and settlement is the desk's
job.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .client import DUST, KalshiClient

SYNC_EVERY_S = 20.0  # how often live positions are checked against what Kalshi says you hold
SYNC_GRACE_S = 30  # leave positions this fresh alone: Kalshi may not list the fill yet
ENTRY_WINDOW_S = 15  # a buy's fills land up to this long before its position is recorded (retries)


async def outside_sales(kalshi: KalshiClient, rows: list[dict[str, Any]], yes_side: str) -> list[tuple[dict[str, Any], float, float, float]]:
    """(row, contracts sold, average price in cents for its side, fees) for each open live position,
    newest first, that Kalshi shows was sold elsewhere. `yes_side` is the desk's name for YES."""
    if not rows:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=SYNC_GRACE_S)).isoformat()
    held = await kalshi.positions()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda r: r["id"], reverse=True):
        groups.setdefault((row["ticker"], row["side"]), []).append(row)
    out: list[tuple[dict[str, Any], float, float, float]] = []
    for (ticker, side), group in groups.items():
        if any(r["opened_at"] > cutoff for r in group):
            continue
        yes = side == yes_side
        count = held.get(ticker, 0.0)
        on_kalshi = round(max(count, 0) if yes else max(-count, 0), 2)
        missing = round(sum(r["contracts"] for r in group) - on_kalshi, 2)
        if missing <= DUST:
            continue
        first_open = min(r["opened_at"] for r in group)
        sells = [f for f in await kalshi.fills(ticker) if iso(f["created_time"]) > first_open and not is_entry(f, group)]
        if sum(f["count"] for f in sells) + 1e-9 < missing:
            continue  # no sale on record: likely settled, so leave it to settlement
        for row in group:  # newest first, matching how the sells were most likely meant
            if missing <= DUST:
                break
            take = round(min(row["contracts"], missing), 2)
            px, fees = fill_price(sells, yes, take)
            out.append((row, take, px, fees))
            missing = round(missing - take, 2)
    return out


def iso(ts: str) -> str:
    """Kalshi's '...Z' timestamps in the same form as `now_iso()`, so they compare as strings."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ""


def is_entry(fill: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    """A fill from one of the desk's own buys: it lands just before that position's `opened_at`."""
    t = iso(fill["created_time"])
    for r in rows:
        opened = datetime.fromisoformat(r["opened_at"])
        if (opened - timedelta(seconds=ENTRY_WINDOW_S)).isoformat(timespec="seconds") <= t <= r["opened_at"]:
            return True
    return False


def fill_price(fills: list[dict[str, Any]], yes: bool, contracts: float) -> tuple[float, float]:
    """Average price (cents, for the side held) and fees of the most recent `contracts` sold."""
    left, value, fees = float(contracts), 0.0, 0.0
    for f in fills:  # newest first
        if left <= DUST:
            break
        n = min(f["count"], left)
        value += n * (f["yes_price"] if yes else f["no_price"])
        fees += f["fee"] * n / f["count"] if f["count"] else 0.0
        left -= n
    return round(value / contracts, 2), round(fees, 2)
