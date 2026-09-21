"""Nightly pattern mining, lesson validation, and Brier calibration."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kalshi_bot.learning.journal import WOULD_PLACE
from kalshi_bot.learning.lessons import validate_lessons
from kalshi_bot.learning.playbook_version import ensure_playbook_v1
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PHASE0_CANDIDATES = [
    REPO_ROOT / "data" / "phase0-out" / "enriched.json",
    Path("/cursor/stores/bc-cb51f061-97d4-4279-b58f-3f609408d29d/internal/phase0-out/enriched.json"),
]


def _minute_bucket(minute: int) -> str:
    if minute < 60:
        return "0-60"
    if minute < 75:
        return "60-75"
    return "75-90"


def _phase0_fills() -> list[dict[str, Any]]:
    for path in PHASE0_CANDIDATES:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Phase 0 read failed %s: %s", path, exc)
            continue
        return [row for row in data.get("fills") or [] if row.get("role") == "buy_no"]
    return []


def mine_patterns(store: Store) -> dict[str, Any]:
    hazard: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    price_cal: list[tuple[float, int]] = []
    buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "hits": 0, "pnl": 0})
    tempo: dict[str, list[float]] = defaultdict(list)

    for row in store.all_decisions():
        if row.get("agent") != "kalshi":
            continue
        feats = row.get("features") or {}
        league = str(feats.get("league") or "unknown")
        minute = int(feats.get("minute") or 0)
        goals_after = int(row.get("goals_after") or 0)
        bucket = _minute_bucket(minute)
        hazard[league][bucket][1] += 1
        if goals_after > 0:
            hazard[league][bucket][0] += 1
        ask = feats.get("no_ask")
        if ask is not None and row.get("settled"):
            implied_under = int(ask) / 100.0
            actual = 1 if row.get("outcome") == "won" and row.get("action") == WOULD_PLACE else 0
            if row.get("action") == WOULD_PLACE:
                price_cal.append((implied_under, actual))
        if row.get("action") == WOULD_PLACE and row.get("settled"):
            key = f"{league}|{bucket}|rem={feats.get('rem')}"
            buckets[key]["n"] += 1
            buckets[key]["hits"] += 1 if row.get("outcome") == "won" else 0
            buckets[key]["pnl"] += int(row.get("realized_pnl_cents") or 0)
        if feats.get("tempo") is not None:
            tempo[league].append(float(feats["tempo"]))

    phase0 = _phase0_fills()
    for fill in phase0:
        league = str(fill.get("league") or "unknown")
        minutes = [int(m) for m in (fill.get("goal_minutes") or []) if float(m) >= 60]
        bucket = "75-90" if any(m >= 75 for m in minutes) else "60-75" if minutes else "0-60"
        hazard[league][bucket][1] += 1
        if minutes:
            hazard[league][bucket][0] += 1
        px = fill.get("no_price")
        if px is not None:
            won = bool(fill.get("won") or fill.get("under_hit"))
            price_cal.append((float(px) if float(px) <= 1 else float(px) / 100.0, 1 if won else 0))

    hazard_rate = {
        league: {bucket: (vals[0] / vals[1] if vals[1] else 0.0) for bucket, vals in buckets.items()}
        for league, buckets in hazard.items()
    }
    bucket_stats = {
        key: {
            "n": int(val["n"]),
            "hit_rate": (val["hits"] / val["n"]) if val["n"] else 0.0,
            "pnl_cents": val["pnl"],
        }
        for key, val in buckets.items()
    }
    tempo_profile = {
        league: round(sum(vals) / len(vals), 3) if vals else 0.0 for league, vals in tempo.items()
    }
    return {
        "hazard": hazard_rate,
        "place_buckets": bucket_stats,
        "tempo": tempo_profile,
        "phase0_fills": len(phase0),
        "price_samples": len(price_cal),
    }


def update_calibration(store: Store) -> list[dict[str, Any]]:
    groups: dict[tuple[str, Optional[str]], list[tuple[float, int]]] = defaultdict(list)
    for row in store.all_decisions():
        if not row.get("settled"):
            continue
        conf = row.get("confidence")
        if conf is None:
            continue
        outcome = 1 if row.get("outcome") == "won" else 0
        league = (row.get("features") or {}).get("league")
        groups[(row.get("agent") or "kalshi", league)].append((float(conf), outcome))
        groups[(row.get("agent") or "kalshi", None)].append((float(conf), outcome))
    out: list[dict[str, Any]] = []
    for (agent, league), rows in groups.items():
        if not rows:
            continue
        brier = sum((p - y) ** 2 for p, y in rows) / len(rows)
        hit = sum(y for _, y in rows) / len(rows)
        store.upsert_calibration(agent, league, len(rows), round(brier, 4), round(hit, 4))
        out.append({"agent": agent, "league": league, "n": len(rows), "brier": round(brier, 4), "hit_rate": round(hit, 4)})
    return out


def run_nightly(store: Store) -> dict[str, Any]:
    """Deterministic nightly job. Never on the event path."""
    ensure_playbook_v1(store)
    patterns = mine_patterns(store)
    lessons = validate_lessons(store)
    calibration = update_calibration(store)
    from kalshi_bot.learning.proposals import propose_from_patterns

    proposals = propose_from_patterns(store, patterns)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    store.set_control("last_mine_date", stamp)
    return {
        "patterns": patterns,
        "lessons": lessons,
        "calibration": calibration,
        "proposals": proposals,
        "mined_on": stamp,
    }


def should_mine_tonight(store: Store, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(tz=timezone.utc)
    if now.hour < 4:
        return False
    return store.get_control("last_mine_date") != now.strftime("%Y-%m-%d")
