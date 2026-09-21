"""Playbook proposals with replay backtest. Propose-only; hard caps never proposed."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from kalshi_bot.config import Settings
from kalshi_bot.learning.journal import WOULD_PLACE, grade_game
from kalshi_bot.learning.playbook_version import (
    HARD_CAP_KEYS,
    active_rules,
    current_version_number,
    ensure_playbook_v1,
    merge_diff,
    publish_version,
)
from kalshi_bot.playbook import override_playbook
from kalshi_bot.replay import list_recorded_fixtures, load_fixture_file, replay_fixture
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)


class HardCapError(ValueError):
    pass


def assert_no_hard_caps(diff: dict[str, Any]) -> None:
    banned = sorted(k for k in diff if k in HARD_CAP_KEYS)
    if banned:
        raise HardCapError(f"hard caps are never proposed: {banned}")


def _metrics(result: dict[str, Any]) -> dict[str, Any]:
    decisions = [row for row in result.get("decisions") or [] if row.get("agent") == "kalshi"]
    places = [row for row in decisions if row.get("action") == WOULD_PLACE]
    hits = [row for row in places if row.get("outcome") == "won"]
    pnl = int((result.get("pnl") or {}).get("total_cents") or 0)
    realized = [int(row.get("realized_pnl_cents") or 0) for row in places]
    running = peak = dd = 0
    for chunk in realized:
        running += chunk
        peak = max(peak, running)
        dd = min(dd, running - peak)
    return {
        "n_trades": len(places),
        "n_decisions": len(decisions),
        "hit_rate": (len(hits) / len(places)) if places else 0.0,
        "pnl_cents": pnl,
        "drawdown_cents": dd,
        "game_id": (result.get("game") or {}).get("id"),
    }


def backtest_diff(store: Store, diff: dict[str, Any], settings: Optional[Settings] = None) -> dict[str, Any]:
    """Replay the recorded corpus under champion vs proposed rules."""
    assert_no_hard_caps(diff)
    settings = settings or Settings()
    fixtures = list_recorded_fixtures()
    if not fixtures:
        return {"champion": {}, "challenger": {}, "games": []}
    champion_rules = active_rules(store)
    proposed = merge_diff(champion_rules, diff)
    champ_rows: list[dict[str, Any]] = []
    chal_rows: list[dict[str, Any]] = []
    games: list[str] = []
    for item in fixtures:
        fixture = load_fixture_file(__import__("pathlib").Path(item["path"]))
        with override_playbook(champion_rules):
            champ = replay_fixture(store, fixture, settings, learn=False)
            grade_game(store, champ["game"]["id"])
            champ["decisions"] = store.decisions_for_game(champ["game"]["id"])
            champ_rows.append(_metrics(champ))
        with override_playbook(proposed):
            chal = replay_fixture(store, fixture, settings, learn=False)
            grade_game(store, chal["game"]["id"])
            chal["decisions"] = store.decisions_for_game(chal["game"]["id"])
            chal_rows.append(_metrics(chal))
        games.append(item["id"])
    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        trades = sum(r["n_trades"] for r in rows)
        hits = sum(r["hit_rate"] * r["n_trades"] for r in rows)
        return {
            "n_trades": trades,
            "hit_rate": (hits / trades) if trades else 0.0,
            "pnl_cents": sum(r["pnl_cents"] for r in rows),
            "drawdown_cents": min((r["drawdown_cents"] for r in rows), default=0),
            "games": [r.get("game_id") for r in rows],
        }

    return {"champion": aggregate(champ_rows), "challenger": aggregate(chal_rows), "games": games}


def create_proposal(
    store: Store,
    *,
    title: str,
    motivation: str,
    diff: dict[str, Any],
    lesson_id: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    assert_no_hard_caps(diff)
    ensure_playbook_v1(store)
    backtest = backtest_diff(store, diff, settings)
    pid = store.add_proposal(
        {
            "status": "pending",
            "title": title,
            "motivation": motivation,
            "lesson_id": lesson_id,
            "diff": diff,
            "backtest": backtest,
        }
    )
    return store.get_proposal(pid) or {"id": pid, "diff": diff, "backtest": backtest}


def approve_proposal(store: Store, proposal_id: int) -> dict[str, Any]:
    row = store.get_proposal(proposal_id)
    if not row:
        raise KeyError(f"proposal {proposal_id} not found")
    assert_no_hard_caps(row.get("diff") or {})
    version = publish_version(
        store,
        diff=row.get("diff") or {},
        notes=f"approved proposal {proposal_id}: {row.get('title')}",
        parent=current_version_number(store),
    )
    store.update_proposal(proposal_id, status="approved", decided_at=int(time.time()))
    return {"proposal": store.get_proposal(proposal_id), "version": version}


def reject_proposal(store: Store, proposal_id: int) -> dict[str, Any]:
    row = store.get_proposal(proposal_id)
    if not row:
        raise KeyError(f"proposal {proposal_id} not found")
    store.update_proposal(proposal_id, status="rejected", decided_at=int(time.time()))
    return store.get_proposal(proposal_id) or row


def shadow_proposal(store: Store, proposal_id: int) -> dict[str, Any]:
    row = store.get_proposal(proposal_id)
    if not row:
        raise KeyError(f"proposal {proposal_id} not found")
    assert_no_hard_caps(row.get("diff") or {})
    store.update_proposal(proposal_id, status="shadow", decided_at=int(time.time()))
    return store.get_proposal(proposal_id) or row


def run_shadow_proposals(store: Store, settings: Optional[Settings] = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in store.list_proposals(status="shadow"):
        try:
            backtest = backtest_diff(store, row.get("diff") or {}, settings)
        except HardCapError:
            continue
        store.update_proposal(proposal_id=int(row["id"]), backtest=backtest)
        out.append({**row, "backtest": backtest})
    return out


def propose_from_patterns(store: Store, patterns: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn validated lessons / bucket stats into pending proposals. Caps never included."""
    created: list[dict[str, Any]] = []
    pending = store.list_proposals(status="pending")
    active = [row for row in store.list_lessons(status="active")]
    rules = active_rules(store)
    for lesson in active:
        action = (lesson.get("suggested_action") or "").lower()
        diff: dict[str, Any] = {}
        if "minute" in action and "skip" in action and int(rules.get("entry_min_minute") or 60) < 70:
            diff = {"entry_min_minute": 70}
        elif "price" in action and "tighten" in action:
            diff = {"entry_no_price_max": 90}
        elif "rem" in action and "skip" in action:
            diff = {"entry_max_rem": 1}
        if not diff:
            continue
        title = f"Lesson {lesson['id']}: {next(iter(diff))}"
        if any(p.get("title") == title for p in pending):
            continue
        try:
            created.append(
                create_proposal(
                    store,
                    title=title,
                    motivation=f"{lesson.get('condition')} — {lesson.get('observation')}",
                    diff=diff,
                    lesson_id=int(lesson["id"]),
                )
            )
        except HardCapError:
            continue
        except Exception:
            logger.exception("Proposal backtest failed for lesson %s", lesson.get("id"))
    buckets = patterns.get("place_buckets") or {}
    early = [v for k, v in buckets.items() if "|60-75|" in k]
    late = [v for k, v in buckets.items() if "|75-90|" in k]
    if (
        early
        and late
        and sum(b["n"] for b in early) >= 3
        and (sum(b["hit_rate"] * b["n"] for b in late) / max(1, sum(b["n"] for b in late)))
        > (sum(b["hit_rate"] * b["n"] for b in early) / max(1, sum(b["n"] for b in early))) + 0.08
        and int(rules.get("entry_min_minute") or 60) < 70
        and not any("entry_min_minute" in (p.get("diff") or {}) for p in pending)
    ):
        try:
            created.append(
                create_proposal(
                    store,
                    title="Raise entry minute to 70 (late bucket lift)",
                    motivation="Nightly mining: 75-90 hit rate beats 60-75",
                    diff={"entry_min_minute": 70},
                )
            )
        except Exception:
            logger.exception("Minute-window proposal failed")
    return created
