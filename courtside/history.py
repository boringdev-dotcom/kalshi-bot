"""The account chart: account value over a time range, with deposits and withdrawals taken out.

Like a brokerage app, a deposit is not a gain. Each point is moved by the money that came in
or went out after it, so the line ends at today's value and the range's change is only what
trading earned or lost. Kalshi stamps a transfer when it is made; the balance check that first
shows it can land a minute either side, so each transfer is matched to that jump in the line.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

MATCH_WINDOW = timedelta(minutes=20)


def _t(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _align(points: list[tuple[datetime, float]], flows: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """Move each transfer to the point where the account first showed it (its matching jump)."""
    used: set[int] = set()
    out = []
    for when, amount in flows:
        best, best_gap = None, None
        for i in range(1, len(points)):
            if i in used or abs(points[i][0] - when) > MATCH_WINDOW:
                continue
            step = points[i][1] - points[i - 1][1]
            if step * amount <= 0 or abs(step) < 0.5 * abs(amount):
                continue
            gap = abs(step - amount)
            if best_gap is None or gap < best_gap:
                best, best_gap = i, gap
        if best is not None:
            used.add(best)
            # Just before that point, so the point itself already counts the money.
            when = points[best][0] - timedelta(microseconds=1)
        out.append((when, amount))
    return out


def adjusted_history(
    rows: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    now: dict[str, Any],
    since: Optional[datetime] = None,
    max_points: int = 300,
) -> dict[str, Any]:
    """`rows` are {ts, equity} snapshots, oldest first (the last one before `since` included);
    `flows` are {ts, amount} transfers in dollars (+ in, - out); `now` is the current {ts, equity}."""
    pts = [(_t(r["ts"]), float(r["equity"])) for r in rows]
    pts.append((_t(now["ts"]), float(now["equity"])))
    if since is not None:
        before = [p for p in pts if p[0] < since]
        pts = ([(since, before[-1][1])] if before else []) + [p for p in pts if p[0] >= since]
    if len(pts) < 2:
        return {"points": [], "start": None, "end": round(float(now["equity"]), 2), "change": 0.0, "change_pct": 0.0, "net_deposits": 0.0}
    start_at = pts[0][0]
    moved = _align(pts, sorted((_t(f["ts"]), float(f["amount"])) for f in flows))
    moved = [(w, a) for w, a in moved if w >= start_at]
    adjusted = []
    for when, value in pts:
        adjusted.append((when, value + sum(a for w, a in moved if w > when)))
    if len(adjusted) > max_points:
        # Keep the last point of each time slice, and always the first and the last.
        span = (adjusted[-1][0] - adjusted[0][0]) / (max_points - 1)
        thin, bucket = [adjusted[0]], None
        for p in adjusted[1:-1]:
            b = int((p[0] - adjusted[0][0]) / span) if span else 0
            if b == bucket:
                thin[-1] = p
            else:
                thin.append(p)
                bucket = b
        thin.append(adjusted[-1])
        adjusted = thin
    start, end = adjusted[0][1], adjusted[-1][1]
    change = end - start
    return {
        "points": [{"ts": w.isoformat(timespec="seconds"), "value": round(v, 2)} for w, v in adjusted],
        "start": round(start, 2),
        "end": round(end, 2),
        "change": round(change, 2),
        "change_pct": round(change / start, 4) if start > 0 else 0.0,
        "net_deposits": round(sum(a for _, a in moved), 2),
    }
