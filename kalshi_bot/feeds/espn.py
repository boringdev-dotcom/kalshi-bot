"""ESPN public soccer scoreboard."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from kalshi_bot.models import MatchState

logger = logging.getLogger(__name__)

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {"User-Agent": "kalshi-bot/0.2 (read-only soccer watcher)"}

LEAGUE_SLUGS = [
    "eng.1",
    "esp.1",
    "ger.1",
    "ita.1",
    "fra.1",
    "usa.1",
    "uefa.champions",
    "uefa.europa",
    "eng.2",
    "ned.1",
    "mex.1",
]


def _client() -> httpx.Client:
    return httpx.Client(timeout=20.0, headers=HEADERS, follow_redirects=True)


def scoreboard(day: datetime, leagues: Optional[list[str]] = None) -> list[dict[str, Any]]:
    date_str = day.strftime("%Y%m%d")
    out: list[dict[str, Any]] = []
    for slug in leagues or LEAGUE_SLUGS:
        try:
            with _client() as client:
                response = client.get(f"{BASE}/{slug}/scoreboard", params={"dates": date_str})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("ESPN scoreboard %s failed: %s", slug, exc)
            continue
        league_name = ((payload.get("leagues") or [{}])[0]).get("name") or slug
        for event in payload.get("events") or []:
            competition = (event.get("competitions") or [{}])[0]
            competitors = competition.get("competitors") or []
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            out.append(
                {
                    "id": str(event.get("id") or ""),
                    "home": ((home.get("team") or {}).get("displayName") or ""),
                    "away": ((away.get("team") or {}).get("displayName") or ""),
                    "league": league_name,
                    "league_slug": slug,
                    "kickoff_ts": _iso_ts(event.get("date")),
                    "status": ((event.get("status") or {}).get("type") or {}).get("name") or "",
                    "raw": event,
                }
            )
    return out


def event_state(event: dict[str, Any]) -> MatchState:
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    status = event.get("status") or competition.get("status") or {}
    stype = status.get("type") or {}
    minute = _parse_minute(status.get("displayClock") or stype.get("shortDetail"))
    period = int(status.get("period") or 0)
    phase = map_phase(stype.get("name") or stype.get("state"), period)
    reds = _red_cards(competitors)
    return MatchState(
        home_goals=_int(home.get("score")),
        away_goals=_int(away.get("score")),
        minute=minute,
        phase=phase,
        red_cards=reds,
        source="espn",
    )


def fetch_event(event_id: str, league_slug: str = "eng.1") -> Optional[dict[str, Any]]:
    try:
        with _client() as client:
            response = client.get(f"{BASE}/{league_slug}/summary", params={"event": event_id})
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("ESPN summary %s failed: %s", event_id, exc)
        return None


def live_state_from_summary(summary: dict[str, Any]) -> MatchState:
    header = summary.get("header") or {}
    competitions = header.get("competitions") or summary.get("boxscore", {}).get("teams")
    if header.get("competitions"):
        return event_state({"competitions": header.get("competitions"), "status": header.get("status")})
    teams = summary.get("boxscore", {}).get("teams") or []
    home = next((t for t in teams if (t.get("team") or {}).get("homeAway") == "home" or t.get("homeAway") == "home"), {})
    away = next((t for t in teams if t is not home), {})
    return MatchState(
        home_goals=_int((home.get("team") or home).get("score") or home.get("score")),
        away_goals=_int((away.get("team") or away).get("score") or away.get("score")),
        source="espn",
    )


def team_last_results(team_id: Optional[str]) -> list[dict[str, Any]]:
    if not team_id:
        return []
    try:
        with _client() as client:
            response = client.get(
                "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/"
                f"{team_id}/schedule"
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("ESPN team schedule %s failed: %s", team_id, exc)
        return []
    results: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        if not ((event.get("status") or {}).get("type") or {}).get("completed"):
            continue
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})
        results.append(
            {
                "home": ((home.get("team") or {}).get("displayName") or ""),
                "away": ((away.get("team") or {}).get("displayName") or ""),
                "home_goals": _int(home.get("score")),
                "away_goals": _int(away.get("score")),
            }
        )
        if len(results) >= 5:
            break
    return results


def map_phase(name: Any, period: int = 0) -> str:
    text = str(name or "").lower()
    if any(token in text for token in ("final", "full", "status_final")):
        return "full_time"
    if "halftime" in text or "half-time" in text or "status_halftime" in text:
        return "half_time"
    if "pre" in text or "scheduled" in text:
        return "upcoming"
    if period >= 3:
        return "extra_time"
    if period >= 2:
        return "second_half"
    if period == 1:
        return "first_half"
    return "unknown"


def _iso_ts(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_minute(value: Any) -> int:
    if value is None:
        return 0
    text = str(value)
    digits = ""
    for char in text:
        if char.isdigit():
            digits += char
        elif digits:
            break
    return int(digits) if digits else 0


def _red_cards(competitors: list[dict[str, Any]]) -> int:
    count = 0
    for team in competitors:
        for item in team.get("details") or team.get("statistics") or []:
            name = str(item.get("type") or item.get("name") or "").lower()
            if "red" in name:
                count += _int(item.get("value") or 1)
    return count
