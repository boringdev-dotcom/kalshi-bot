"""What the agent knows about a soccer match beyond the score: lineups, players, form, the table,
head-to-head, and which team has been on top lately.

Everything comes from ESPN's match summary. The goals model sees none of it (only the score,
the minute, red cards and the pre-match odds), which is why the agent gets it.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .domain import Match

# Player stats worth the agent's attention, by ESPN name -> short name. Zeros are left out.
PLAYER_STATS = {
    "totalGoals": "goals", "goalAssists": "assists", "totalShots": "shots", "shotsOnTarget": "on_target",
    "foulsCommitted": "fouls", "foulsSuffered": "fouled", "yellowCards": "yellow", "redCards": "red",
    "saves": "saves", "goalsConceded": "conceded", "ownGoals": "own_goals",
}

WINDOW = 15  # minutes in the "lately" window


def _side_of(m: Match, team: dict[str, Any] | str | None) -> Optional[str]:
    """'home' / 'away' for an ESPN team (dict with an id, or a display name)."""
    if isinstance(team, dict):
        tid = str(team.get("id") or "")
        if tid and tid == m.home.id:
            return "home"
        if tid and tid == m.away.id:
            return "away"
        team = team.get("displayName") or team.get("name") or ""
    return _side_by_name(m, team or "")


def _side_by_name(m: Match, name: str) -> Optional[str]:
    n = name.strip().lower()
    if not n:
        return None
    for key, side in (("home", m.home), ("away", m.away)):
        if n in {side.name.lower(), side.short.lower(), side.abbr.lower()}:
            return key
    return None


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def apply_context(m: Match, data: dict[str, Any]) -> None:
    """Read lineups, player stats, form, the table and head-to-head from a match summary."""
    lineups: dict[str, Any] = {}
    players: dict[str, list[dict[str, Any]]] = {}
    for r in data.get("rosters") or []:
        side = _side_of(m, r.get("team")) or r.get("homeAway")
        if side not in ("home", "away"):
            continue
        roster = r.get("roster") or []
        if not roster:
            continue
        starters, came_on, went_off, rows = [], [], [], []
        for p in roster:
            name = (p.get("athlete") or {}).get("displayName") or "?"
            pos = ((p.get("position") or {}).get("abbreviation")) or ""
            if p.get("starter"):
                starters.append(f"{name} ({pos})" if pos else name)
            if p.get("subbedIn"):
                came_on.append(name)
            if p.get("subbedOut"):
                went_off.append(name)
            if not (p.get("starter") or p.get("subbedIn")):
                continue
            stats = {}
            for st in p.get("stats") or []:
                short = PLAYER_STATS.get(st.get("name"))
                value = _num(st.get("displayValue") if st.get("displayValue") is not None else st.get("value"))
                if short and value:
                    stats[short] = int(value) if value.is_integer() else value
            if stats or p.get("subbedIn") or p.get("subbedOut"):
                row = {"name": name, "pos": pos}
                if p.get("subbedIn"):
                    row["came_on"] = True
                if p.get("subbedOut"):
                    row["went_off"] = True
                rows.append(row | stats)
        lineups[side] = {"formation": r.get("formation") or None, "starting_xi": starters, "came_on": came_on, "went_off": went_off}
        players[side] = rows
    if lineups:
        m.lineups = lineups
        m.players = players

    form: dict[str, list[str]] = {}
    for block in data.get("lastFiveGames") or []:
        side = _side_of(m, block.get("team"))
        team_id = str((block.get("team") or {}).get("id") or "")
        if side is None:
            continue
        rows = []
        for e in sorted(block.get("events") or [], key=lambda e: e.get("gameDate") or "", reverse=True):  # newest first
            home = str(e.get("homeTeamId") or "") == team_id
            mine, theirs = (e.get("homeTeamScore"), e.get("awayTeamScore")) if home else (e.get("awayTeamScore"), e.get("homeTeamScore"))
            opp = (e.get("opponent") or {}).get("displayName") or "?"
            rows.append(f"{e.get('gameResult') or '?'} {mine}-{theirs} {'vs' if home else 'at'} {opp} "
                        f"({e.get('leagueName') or e.get('competitionName') or ''}, {(e.get('gameDate') or '')[:10]})")
        form[side] = rows
    if form:
        m.form = form

    table: dict[str, Any] = {}
    for group in (data.get("standings") or {}).get("groups") or []:
        entries = (group.get("standings") or {}).get("entries") or []
        for ent in entries:
            side = None
            if str(ent.get("id") or "") in (m.home.id, m.away.id):
                side = "home" if str(ent.get("id")) == m.home.id else "away"
            side = side or _side_of(m, ent.get("team"))
            if side is None:
                continue
            s = {st.get("name"): st.get("displayValue") for st in ent.get("stats") or []}
            table[side] = {"position": s.get("rank"), "of": len(entries), "played": s.get("gamesPlayed"),
                           "won": s.get("wins"), "drawn": s.get("ties"), "lost": s.get("losses"),
                           "goal_difference": s.get("pointDifferential"), "points": s.get("points")}
    if table:
        m.table = table

    for series in data.get("seasonseries") or []:
        if series.get("type") != "head-to-head":
            continue
        games = []
        for e in series.get("events") or []:
            cs = {c.get("homeAway"): c for c in e.get("competitors") or []}
            h, a = cs.get("home") or {}, cs.get("away") or {}
            games.append(f"{(e.get('date') or '')[:10]} {(h.get('team') or {}).get('abbreviation', '?')} {h.get('score', '?')}"
                         f"-{a.get('score', '?')} {(a.get('team') or {}).get('abbreviation', '?')}")
        m.head_to_head = {"summary": series.get("summary"), "games": games}
        break


# --------------------------------------------------------------- run of play

_TEAM = re.compile(r"\(([^()]+)\)")


def _line_minute(display: str, match_period: int) -> Optional[float]:
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    if not nums:
        return None
    if nums[0] == 45 and len(nums) > 1 and match_period >= 2:
        return 45.0  # first-half stoppage time, seen from the second half
    return float(sum(nums[:2]))


def _tally(m: Match, text: str) -> Optional[tuple[str, dict[str, int]]]:
    """(side, counts) for one commentary line, or None if it is not a countable action."""
    t = text.strip()
    low = t.lower()
    teams = _TEAM.findall(t)
    first = _side_by_name(m, teams[0]) if teams else None
    if low.startswith("goal!"):
        return (first, {"shots": 1, "on_target": 1, "goals": 1}) if first else None
    if low.startswith("attempt"):
        if not first:
            return None
        return first, {"shots": 1, "on_target": 1 if low.startswith("attempt saved") else 0}
    if low.startswith("corner,"):
        side = _side_by_name(m, t.split(",", 1)[1].split(".")[0])
        return (side, {"corners": 1}) if side else None
    if low.startswith("foul by"):
        return (first, {"fouls": 1}) if first else None
    if "is shown the yellow card" in low or "is shown the red card" in low:
        return (first, {"cards": 1}) if first else None
    if low.startswith("offside,"):
        side = _side_by_name(m, t.split(",", 1)[1].split(".")[0])
        return (side, {"offsides": 1}) if side else None
    return None


def run_of_play(m: Match, window: int = WINDOW) -> Optional[dict[str, Any]]:
    """Who has been on top lately: shots, shots on target, corners, fouls and cards in the last
    `window` minutes against the `window` before, counted from the commentary."""
    if m.state != "live" or not m.commentary or m.minute < 5:
        return None
    now = m.minute
    blank = lambda: {"shots": 0, "on_target": 0, "corners": 0, "fouls": 0, "cards": 0, "offsides": 0, "goals": 0}  # noqa: E731
    recent = {"home": blank(), "away": blank()}
    before = {"home": blank(), "away": blank()}
    for c in m.commentary:
        minute = _line_minute(c.get("minute") or "", m.period)
        hit = _tally(m, c.get("text") or "")
        if minute is None or hit is None:
            continue
        side, counts = hit
        bucket = recent if minute > now - window else before if minute > now - 2 * window else None
        if bucket is None:
            continue
        for k, v in counts.items():
            bucket[side][k] += v
    name = {"home": m.home.short, "away": m.away.short}
    lo = max(0, int(now - window))
    return {
        "window": f"{lo}'-{int(now)}'",
        "last_window": {name[s]: recent[s] for s in ("home", "away")},
        "window_before": {name[s]: before[s] for s in ("home", "away")} if now >= window + 5 else None,
        "source": "counted from the commentary lines; a rough guide, not official stats",
    }
