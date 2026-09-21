"""Pre-match last-5 form, over/under rate, and league tier."""

from __future__ import annotations

from typing import Any, Optional

from kalshi_bot.playbook import league_tier

from . import espn, fotmob


def summarize_results(results: list[dict[str, Any]], team_name: str) -> dict[str, Any]:
    goals_for = 0
    goals_against = 0
    overs = 0
    rows: list[dict[str, Any]] = []
    for match in results:
        home = match.get("home") or ""
        is_home = home.lower() in team_name.lower() or team_name.lower() in home.lower()
        gf = match.get("home_goals", 0) if is_home else match.get("away_goals", 0)
        ga = match.get("away_goals", 0) if is_home else match.get("home_goals", 0)
        total = (match.get("home_goals") or 0) + (match.get("away_goals") or 0)
        goals_for += gf
        goals_against += ga
        if total > 2.5:
            overs += 1
        rows.append({**match, "gf": gf, "ga": ga, "total": total})
    n = max(len(results), 1)
    return {
        "last5": rows,
        "played": len(results),
        "goals_for": goals_for,
        "goals_against": goals_against,
        "gf_avg": round(goals_for / n, 2),
        "ga_avg": round(goals_against / n, 2),
        "over_25_rate": round(overs / n, 2) if results else None,
    }


def build_prematch(
    home_team: str,
    away_team: str,
    league: Optional[str],
    fotmob_home_id: Optional[str] = None,
    fotmob_away_id: Optional[str] = None,
    espn_home_id: Optional[str] = None,
    espn_away_id: Optional[str] = None,
) -> dict[str, Any]:
    home_results = fotmob.last_results_from_team(fotmob_home_id) or espn.team_last_results(espn_home_id)
    away_results = fotmob.last_results_from_team(fotmob_away_id) or espn.team_last_results(espn_away_id)
    home_stats = summarize_results(home_results, home_team)
    away_stats = summarize_results(away_results, away_team)
    combined = home_results + away_results
    overs = sum(1 for m in combined if (m.get("home_goals") or 0) + (m.get("away_goals") or 0) > 2.5)
    return {
        "league": league,
        "league_tier": league_tier(league),
        "home": home_stats,
        "away": away_stats,
        "combined_over_25_rate": round(overs / len(combined), 2) if combined else None,
        "source": "fotmob/espn last-5 (best effort)",
    }
