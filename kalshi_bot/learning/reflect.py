"""Post-game reflection. Runs once at full-time, off the event path."""

from __future__ import annotations

import logging
from typing import Any, Optional

from kalshi_bot.agents.grok import GrokClient, extract_json, message_content
from kalshi_bot.config import Settings
from kalshi_bot.learning.journal import ERROR, LUCK, SKILL, UNLUCKY, grade_game
from kalshi_bot.learning.lessons import add_hypothesis
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)

SYSTEM = """You are reviewing a finished soccer under-No paper session.
Given graded decisions, say what was skill, luck, error, or unlucky.
Return ONLY JSON:
{
  "notes": "short paragraph",
  "decisions": [{"id": 0, "verdict": "skill|luck|error|unlucky", "would_do_differently": "..."}],
  "lessons": [{"condition": "league=x;minute>=70", "observation": "...", "suggested_action": "..."}]
}
Do not propose changing hard caps (loss, per-match, per-day).
Lessons are hypotheses only.
"""


def _fallback_lessons(game: dict[str, Any], graded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    league = game.get("league") or "unknown"
    for row in graded:
        feats = row.get("features") or {}
        grade = row.get("process_grade")
        if grade not in {ERROR, UNLUCKY}:
            continue
        minute = feats.get("minute") or 0
        rem = feats.get("rem")
        condition = f"league={league};minute>={max(0, int(minute) - 5)}"
        if rem is not None:
            condition += f";rem<={rem}"
        if grade == ERROR:
            observation = f"{row.get('action')} graded error; outcome={row.get('outcome')}"
            action = "skip this setup until sample improves" if row.get("action") == "would-place" else "take the playbook entry when it is open"
        else:
            observation = f"{row.get('action')} was process-correct but unlucky; goals_after={row.get('goals_after')}"
            action = "keep the rule; do not chase the late goal"
        lessons.append(
            {
                "condition": condition,
                "observation": observation,
                "suggested_action": action,
            }
        )
    return lessons[:4]


def _fallback_reflection(game: dict[str, Any], graded: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {SKILL: 0, LUCK: 0, ERROR: 0, UNLUCKY: 0}
    for row in graded:
        counts[row.get("process_grade") or SKILL] = counts.get(row.get("process_grade") or SKILL, 0) + 1
    notes = (
        f"{game.get('home_team')} {game.get('home_goals')}-{game.get('away_goals')} {game.get('away_team')}: "
        f"skill={counts[SKILL]} luck={counts[LUCK]} error={counts[ERROR]} unlucky={counts[UNLUCKY]}"
    )
    return {
        "notes": notes,
        "decisions": [
            {
                "id": row.get("id"),
                "verdict": row.get("process_grade") or SKILL,
                "would_do_differently": "follow the graded process; do not override hard caps",
            }
            for row in graded
        ],
        "lessons": _fallback_lessons(game, graded),
        "source": "deterministic",
    }


def _persist_lessons(store: Store, game: dict[str, Any], lessons: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for lesson in lessons:
        lid = add_hypothesis(
            store,
            condition=lesson.get("condition") or f"league={game.get('league')}",
            observation=lesson.get("observation") or "reflection candidate",
            suggested_action=lesson.get("suggested_action") or "review playbook",
            evidence_game=game.get("id"),
            league=game.get("league"),
        )
        ids.append(lid)
    return ids


def reflect_game(
    store: Store,
    game_id: str,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Grade then reflect. Never call this from handle_event."""
    existing = store.reflection_for_game(game_id)
    if existing:
        return existing
    game = store.get_game(game_id) or {"id": game_id}
    graded = grade_game(store, game_id)
    brief = store.latest_brief(game_id)
    payload = _fallback_reflection(game, graded)
    settings = settings or Settings()
    grok = GrokClient(settings, store)
    if grok.available():
        user = {
            "game": {k: game.get(k) for k in ("id", "home_team", "away_team", "league", "home_goals", "away_goals", "minute")},
            "brief": (brief or {}).get("text"),
            "decisions": [
                {
                    "id": row.get("id"),
                    "action": row.get("action"),
                    "reason": row.get("reason"),
                    "outcome": row.get("outcome"),
                    "process_grade": row.get("process_grade"),
                    "realized_pnl_cents": row.get("realized_pnl_cents"),
                    "counterfactual_pnl_cents": row.get("counterfactual_pnl_cents"),
                    "features": row.get("features"),
                }
                for row in graded
            ],
        }
        try:
            data = grok.complete(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": __import__("json").dumps(user)},
                ],
                None,
                agent="reflect",
                game_id=game_id,
            )
            text = message_content((data.get("choices") or [{}])[0].get("message") or {})
            parsed = extract_json(text)
            payload = {
                "notes": parsed.get("notes") or payload["notes"],
                "decisions": parsed.get("decisions") or payload["decisions"],
                "lessons": parsed.get("lessons") or [],
                "source": "grok",
            }
        except Exception:
            logger.exception("Reflection Grok call failed; using deterministic notes")
    lesson_ids = _persist_lessons(store, game, payload.get("lessons") or [])
    payload["lesson_ids"] = lesson_ids
    store.add_reflection(game_id, payload.get("notes") or "", payload)
    return store.reflection_for_game(game_id) or payload
