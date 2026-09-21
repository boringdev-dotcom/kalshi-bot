"""FotMob unofficial HTTP feed."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from kalshi_bot.models import MatchState

logger = logging.getLogger(__name__)

BASE = "https://www.fotmob.com/api"
HEADERS = {
    "User-Agent": "kalshi-bot/0.2 (read-only soccer watcher)",
    "Accept": "application/json",
}


def _client() -> httpx.Client:
    return httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True)


def matches_for_date(day: datetime) -> list[dict[str, Any]]:
    date_str = day.strftime("%Y%m%d")
    try:
        with _client() as client:
            response = client.get(f"{BASE}/matches", params={"date": date_str})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("FotMob matches fetch failed: %s", exc)
        return []
    return _flatten_matches(payload)


def match_details(match_id: str) -> Optional[dict[str, Any]]:
    try:
        with _client() as client:
            response = client.get(f"{BASE}/matchDetails", params={"matchId": match_id})
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("FotMob matchDetails %s failed: %s", match_id, exc)
        return None


def _flatten_matches(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    leagues = payload.get("leagues") or payload.get("matches") or []
    if isinstance(leagues, dict):
        leagues = leagues.get("leagues") or []
    for league in leagues:
        league_name = league.get("name") or league.get("primaryId") or ""
        for match in league.get("matches") or []:
            home = _team_name(match.get("home") or match.get("homeTeam") or {})
            away = _team_name(match.get("away") or match.get("awayTeam") or {})
            kickoff = _kickoff_ts(match)
            out.append(
                {
                    "id": str(match.get("id") or match.get("matchId") or ""),
                    "home": home,
                    "away": away,
                    "league": league_name,
                    "kickoff_ts": kickoff,
                    "status": (match.get("status") or {}).get("reason")
                    or (match.get("status") or {}).get("label")
                    or "",
                    "raw": match,
                }
            )
    return out


def _team_name(team: dict[str, Any]) -> str:
    return team.get("name") or team.get("shortName") or team.get("id") or ""


def _kickoff_ts(match: dict[str, Any]) -> Optional[int]:
    for key in ("timeTS", "startTime", "utcTime", "status.utcTime"):
        if "." in key:
            status = match.get("status") or {}
            value = status.get("utcTime")
        else:
            value = match.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return int(value if value > 1_000_000_000_000 else value)
        if isinstance(value, str):
            try:
                cleaned = value.replace("Z", "+00:00")
                return int(datetime.fromisoformat(cleaned).timestamp())
            except ValueError:
                continue
    return None


def live_state(details: dict[str, Any]) -> MatchState:
    header = details.get("header") or {}
    general = details.get("general") or {}
    status = header.get("status") or general.get("status") or {}
    teams = header.get("teams") or []
    home_goals = 0
    away_goals = 0
    if len(teams) >= 2:
        home_goals = _score(teams[0])
        away_goals = _score(teams[1])
    else:
        home_goals = int((header.get("homeTeam") or {}).get("score") or 0)
        away_goals = int((header.get("awayTeam") or {}).get("score") or 0)

    minute = _parse_minute(status.get("liveTime") or status.get("reason") or status.get("scoreStr"))
    if minute == 0:
        minute = _parse_minute(general.get("matchTime") or status.get("min"))
    phase = map_phase(status.get("reason") or status.get("label") or general.get("started"))
    reds = _red_cards(details)
    return MatchState(
        home_goals=home_goals,
        away_goals=away_goals,
        minute=minute,
        phase=phase,
        red_cards=reds,
        source="fotmob",
    )


def _score(team: dict[str, Any]) -> int:
    value = team.get("score")
    if isinstance(value, dict):
        value = value.get("current") or value.get("fulltime")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_minute(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else 0


def map_phase(label: Any) -> str:
    text = str(label or "").lower()
    if any(token in text for token in ("ft", "full", "finished", "ended")):
        return "full_time"
    if "ht" in text or "half time" in text or "halftime" in text:
        return "half_time"
    if "2nd" in text or "second" in text:
        return "second_half"
    if "1st" in text or "first" in text:
        return "first_half"
    if "extra" in text:
        return "extra_time"
    if text in {"true", "1"}:
        return "first_half"
    return "unknown"


def _red_cards(details: dict[str, Any]) -> int:
    count = 0
    content = details.get("content") or {}
    events = content.get("matchFacts") or content.get("events") or {}
    incidents = events.get("events") if isinstance(events, dict) else events
    if isinstance(incidents, list):
        for item in incidents:
            etype = str(item.get("type") or item.get("typeId") or "").lower()
            if "red" in etype:
                count += 1
    return count


def last_results_from_team(team_id: Optional[str]) -> list[dict[str, Any]]:
    if not team_id:
        return []
    try:
        with _client() as client:
            response = client.get(f"{BASE}/teams", params={"id": team_id})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("FotMob team %s failed: %s", team_id, exc)
        return []
    fixtures = (
        ((payload.get("fixtures") or {}).get("allMatches"))
        or ((payload.get("overview") or {}).get("recentMatches"))
        or []
    )
    results: list[dict[str, Any]] = []
    for match in fixtures:
        status = str((match.get("status") or {}).get("reason") or "").lower()
        if "ft" not in status and "full" not in status:
            continue
        results.append(
            {
                "home": _team_name(match.get("home") or {}),
                "away": _team_name(match.get("away") or {}),
                "home_goals": _score(match.get("home") or {}),
                "away_goals": _score(match.get("away") or {}),
            }
        )
        if len(results) >= 5:
            break
    return results
