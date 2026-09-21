"""Kickoff / half-time memory brief. Compiled by the watcher, no LLM."""

from __future__ import annotations

from typing import Any, Optional

from kalshi_bot.learning.lessons import active_lessons_for
from kalshi_bot.learning.playbook_version import active_rules, current_version_number, ensure_playbook_v1
from kalshi_bot.playbook import league_tier
from kalshi_bot.store import Store

# Seed late-goal hazard from Phase 0 pattern notes (league, minute bucket).
SEED_HAZARD = {
    "premier_league": {"60-75": 0.18, "75-90": 0.22},
    "la_liga": {"60-75": 0.16, "75-90": 0.20},
    "serie_a": {"60-75": 0.14, "75-90": 0.16},
    "bundesliga": {"60-75": 0.20, "75-90": 0.24},
    "ligue_1": {"60-75": 0.15, "75-90": 0.19},
    "mls": {"60-75": 0.17, "75-90": 0.21},
    "default": {"60-75": 0.16, "75-90": 0.20},
}

MAX_TOKENS = 2000


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _closest_games(store: Store, game: dict[str, Any], limit: int = 3) -> list[str]:
    league = game.get("league")
    lines: list[str] = []
    for other in store.finished_games():
        if other["id"] == game.get("id"):
            continue
        if league and other.get("league") != league:
            continue
        lines.append(
            f"{other.get('home_team')} {other.get('home_goals')}-{other.get('away_goals')} "
            f"{other.get('away_team')} ({other.get('league')})"
        )
        if len(lines) >= limit:
            break
    return lines


def _calibration_note(store: Store, agent: str, league: Optional[str]) -> str:
    rows = store.list_calibration()
    match = next((r for r in rows if r["agent"] == agent and r.get("league") == league), None)
    if match is None:
        match = next((r for r in rows if r["agent"] == agent and not r.get("league")), None)
    if not match:
        return "no calibration yet"
    return f"n={match['n']} brier={match['brier']:.3f} hit={match.get('hit_rate')}"


def compile_brief(
    store: Store,
    game: dict[str, Any],
    *,
    phase: Optional[str] = None,
) -> dict[str, Any]:
    """Deterministic brief. Target under 2k tokens. Never calls an LLM."""
    ensure_playbook_v1(store)
    version = current_version_number(store)
    rules = active_rules(store)
    league = game.get("league") or "unknown"
    tier = game.get("league_tier") or league_tier(league)
    hazard = SEED_HAZARD.get(str(league).lower().replace(" ", "_"), SEED_HAZARD["default"])
    lessons = active_lessons_for(store, league=league, tier=int(tier) if tier else None)
    past = _closest_games(store, game)
    prematch = game.get("prematch") or {}
    lines = [
        f"MEMORY BRIEF {game.get('home_team')} vs {game.get('away_team')}",
        f"league={league} tier={tier} phase={phase or game.get('phase')} playbook_v={version}",
        f"hazard 60-75={hazard.get('60-75')} 75-90={hazard.get('75-90')}",
        (
            f"playbook min={rules.get('entry_min_minute')}-{rules.get('entry_max_minute')} "
            f"rem<={rules.get('entry_max_rem')} No {rules.get('entry_no_price_min')}-"
            f"{rules.get('entry_no_price_max')}c"
        ),
        f"prematch over25={prematch.get('combined_over_25_rate')} tier={prematch.get('league_tier')}",
        f"kalshi calibration: {_calibration_note(store, 'kalshi', league)}",
        f"pundit calibration: {_calibration_note(store, 'pundit', league)}",
        "active lessons:",
    ]
    if lessons:
        for lesson in lessons:
            lines.append(
                f"- [{lesson.get('confidence'):.2f}] {lesson['condition']} -> "
                f"{lesson['observation']} => {lesson['suggested_action']}"
            )
    else:
        lines.append("- none validated yet (hypotheses are ignored)")
    lines.append("closest finished games:")
    if past:
        lines.extend(f"- {row}" for row in past)
    else:
        lines.append("- none in journal")
    text = "\n".join(lines)
    if estimate_tokens(text) > MAX_TOKENS:
        text = text[: MAX_TOKENS * 4]
    brief_id = store.add_brief(
        {
            "game_id": game["id"],
            "phase": phase or game.get("phase") or "kickoff",
            "playbook_version": version,
            "text": text,
            "token_estimate": estimate_tokens(text),
        }
    )
    return {
        "id": brief_id,
        "game_id": game["id"],
        "phase": phase or game.get("phase") or "kickoff",
        "playbook_version": version,
        "text": text,
        "token_estimate": estimate_tokens(text),
    }


def latest_brief(store: Store, game_id: str) -> Optional[dict[str, Any]]:
    return store.latest_brief(game_id)
