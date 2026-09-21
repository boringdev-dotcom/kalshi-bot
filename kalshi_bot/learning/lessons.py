"""Lesson hypotheses: promote, demote, decay. Never applied until data-validated."""

from __future__ import annotations

import time
from typing import Any, Optional

from kalshi_bot.store import Store

MIN_SUPPORT = 3
MIN_LIFT = 0.05
DECAY = 0.85
STALE_SEC = 14 * 24 * 3600


def parse_condition(condition: str) -> list[tuple[str, str, str]]:
    clauses: list[tuple[str, str, str]] = []
    for chunk in (condition or "").split(";"):
        part = chunk.strip()
        if not part:
            continue
        for op in (">=", "<=", "!=", "=", ">", "<"):
            if op in part:
                key, value = part.split(op, 1)
                clauses.append((key.strip(), op, value.strip()))
                break
    return clauses


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def matches_condition(condition: str, features: Optional[dict[str, Any]]) -> bool:
    feats = features or {}
    clauses = parse_condition(condition)
    if not clauses:
        return False
    for key, op, raw in clauses:
        left = feats.get(key)
        right = _coerce(raw)
        if left is None:
            return False
        if isinstance(right, (int, float)):
            try:
                left = float(left)
            except (TypeError, ValueError):
                return False
        if op == "=" and left != right:
            return False
        if op == "!=" and left == right:
            return False
        if op == ">" and not (left > right):
            return False
        if op == "<" and not (left < right):
            return False
        if op == ">=" and not (left >= right):
            return False
        if op == "<=" and not (left <= right):
            return False
    return True


def add_hypothesis(
    store: Store,
    *,
    condition: str,
    observation: str,
    suggested_action: str,
    evidence_game: Optional[str] = None,
    league: Optional[str] = None,
) -> int:
    existing = [
        row
        for row in store.list_lessons()
        if row["condition"] == condition and row["suggested_action"] == suggested_action
    ]
    if existing:
        row = existing[0]
        store.update_lesson(
            int(row["id"]),
            support_count=int(row.get("support_count") or 1) + 1,
            evidence_game=evidence_game or row.get("evidence_game"),
        )
        return int(row["id"])
    return store.add_lesson(
        {
            "condition": condition,
            "observation": observation,
            "suggested_action": suggested_action,
            "status": "hypothesis",
            "confidence": 0,
            "support_count": 1,
            "evidence_game": evidence_game,
            "league": league,
        }
    )


def _lift_for_lesson(store: Store, lesson: dict[str, Any]) -> tuple[int, float, float]:
    decisions = [row for row in store.all_decisions() if row.get("agent") == "kalshi" and row.get("settled")]
    matched = [row for row in decisions if matches_condition(lesson["condition"], row.get("features"))]
    if not matched:
        return 0, 0.0, 0.0
    def hit(row: dict[str, Any]) -> bool:
        return row.get("outcome") == "won"

    match_rate = sum(1 for row in matched if hit(row)) / len(matched)
    base_rate = (sum(1 for row in decisions if hit(row)) / len(decisions)) if decisions else 0.0
    return len(matched), match_rate, match_rate - base_rate


def validate_lessons(store: Store) -> list[dict[str, Any]]:
    now = int(time.time())
    out: list[dict[str, Any]] = []
    for lesson in store.list_lessons():
        support, rate, lift = _lift_for_lesson(store, lesson)
        status = lesson.get("status") or "hypothesis"
        confidence = float(lesson.get("confidence") or 0)
        last = lesson.get("last_validated_at")
        if support >= MIN_SUPPORT and (lift >= MIN_LIFT or rate >= 0.6):
            status = "active"
            confidence = min(1.0, max(0.35, 0.2 + max(lift, 0) + support / 20 + (0.2 if rate >= 0.6 else 0)))
        elif status == "active" and (support < MIN_SUPPORT or lift < 0):
            status = "demoted"
            confidence = max(0.0, confidence * DECAY)
        elif status == "hypothesis" and support >= MIN_SUPPORT and lift < 0:
            status = "retired"
            confidence = 0.0
        elif last and now - int(last) > STALE_SEC:
            confidence = round(confidence * DECAY, 4)
            if confidence < 0.1 and status == "active":
                status = "demoted"
        store.update_lesson(
            int(lesson["id"]),
            status=status,
            confidence=confidence,
            support_count=max(int(lesson.get("support_count") or 1), support),
            last_validated_at=now,
        )
        out.append(
            {
                **lesson,
                "status": status,
                "confidence": confidence,
                "support_count": max(int(lesson.get("support_count") or 1), support),
                "hit_rate": rate,
                "lift": lift,
            }
        )
    return out


def active_lessons_for(store: Store, *, league: Optional[str] = None, tier: Optional[int] = None) -> list[dict[str, Any]]:
    rows = [row for row in store.list_lessons(status="active")]
    picked: list[dict[str, Any]] = []
    for row in rows:
        if league and row.get("league") and row["league"] != league:
            if f"league={league}" not in (row.get("condition") or ""):
                continue
        if tier is not None and f"tier={tier}" in (row.get("condition") or ""):
            picked.append(row)
            continue
        picked.append(row)
    return picked[:6]
