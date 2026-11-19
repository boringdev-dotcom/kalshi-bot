"""What is happening on the floor: who is playing, fouls, hot hands, runs, scoring bursts.

Real games and practice games both produce a `Snapshot` (players, fouls, scoring
plays). One set of rules, `build_context`, turns a snapshot into plain sentences
("notes") that the game page shows, that get saved with every trade, and that the
agent and Claude read.

A note's `lean` says which way it pushes the number of points scored: "up", "down",
or None when there is no clear direction. Only patterns with a well-known effect get a
lean (the bonus means free throws; a scoring burst or drought is what it is). The rest
are left for the learner to judge from results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..domain import OT_SECONDS, QUARTER_SECONDS, Game, now_iso

ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"

# Plain names for each pattern key, shared with the learning view.
PATTERN_LABELS = {
    "bonus_early": "A team in the bonus early in Q4",
    "bonus": "A team in the bonus",
    "foul_trouble": "A player in foul trouble",
    "hot_hand": "A player shooting hot",
    "run": "A big run",
    "scoring_hot": "Scoring speeding up",
    "scoring_cold": "Scoring slowing down",
    "bench_in": "Bench players in",
    "ejection": "A player ejected",
}

SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}


@dataclass
class PlayerLine:
    id: str
    name: str
    team: str
    starter: bool
    on_court: bool = False
    minutes: float = 0.0
    points: int = 0
    fgm: int = 0
    fga: int = 0
    tpm: int = 0
    tpa: int = 0
    ftm: int = 0
    fta: int = 0
    fouls: int = 0
    plus_minus: int = 0

    @property
    def short(self) -> str:
        parts = self.name.split()
        if len(parts) >= 2 and parts[-1].lower() in SUFFIXES:
            return parts[-2]
        return parts[-1] if parts else self.name


@dataclass
class Snapshot:
    players: list[PlayerLine]
    # Fouls that count toward the team limit: (team, period, seconds left in the period).
    fouls: list[tuple[str, int, float]] = field(default_factory=list)
    # Scoring plays: (game seconds elapsed, team, points).
    scoring: list[tuple[float, str, int]] = field(default_factory=list)
    # Players listed out before the game: (team, name).
    out: list[tuple[str, str]] = field(default_factory=list)
    ejected: list[str] = field(default_factory=list)
    source: str = "espn"


def elapsed_at(period: int, clock: float) -> float:
    """Game seconds elapsed at a given period and clock (overtimes are 5 minutes)."""
    if period <= 4:
        return (period - 1) * QUARTER_SECONDS + (QUARTER_SECONDS - clock)
    return 4 * QUARTER_SECONDS + (period - 5) * OT_SECONDS + (OT_SECONDS - clock)


def _clock_text(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


def _period_name(period: int) -> str:
    return f"Q{period}" if period <= 4 else ("OT" if period == 5 else f"{period - 4}OT")


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# ---------------------------------------------------------------------------- rules
def build_context(game: Game, snap: Snapshot) -> dict[str, Any]:
    """Turn a snapshot into the patterns shown on the game page and saved with trades."""
    teams = {game.home.abbr: "home", game.away.abbr: "away"}
    other = {game.home.abbr: game.away.abbr, game.away.abbr: game.home.abbr}
    live = game.state == "live"
    period, clock = game.period, game.clock_seconds
    now = game.elapsed
    notes: list[dict[str, Any]] = []

    def note(key: str, text: str, lean: Optional[str] = None, team: Optional[str] = None, weight: int = 1) -> None:
        notes.append({"key": key, "text": text, "lean": lean, "team": team, "weight": weight})

    # Team fouls this period and whether the next foul sends the other team to the line.
    limit = 4 if period <= 4 else 3
    team_rows = []
    for abbr in (game.away.abbr, game.home.abbr):
        this_period = [f for f in snap.fouls if f[0] == abbr and f[1] == period]
        late = [f for f in this_period if f[2] <= 120]
        penalty = live and (len(this_period) >= limit or (clock <= 120 and len(late) >= 1))
        on = [p for p in snap.players if p.team == abbr and p.on_court]
        last5 = sum(pts for t, team, pts in snap.scoring if team == abbr and now - 300 <= t <= now)
        team_rows.append({
            "abbr": abbr,
            "side": teams[abbr],
            "fouls": len(this_period),
            "penalty": penalty,
            "on_court": [p.id for p in on],
            "starters_on": sum(1 for p in on if p.starter),
            "last5": last5,
        })
        if penalty and clock > 25:
            shooter = other[abbr]
            early = period == 4 and clock > 240
            note(
                "bonus_early" if early else "bonus",
                f"{shooter} is in the bonus with {_clock_text(clock)} left in {_period_name(period)}. "
                f"Every {abbr} foul now means free throws.",
                lean="up",
                team=shooter,
                weight=3 if early else 2,
            )

    if live:
        # Foul trouble: a sixth foul ends a player's night; early fouls send starters to the bench.
        for p in snap.players:
            if p.fouls >= 6:
                continue
            if p.fouls == 5:
                where = "" if p.on_court else ", sitting for now"
                note("foul_trouble", f"{p.name} ({p.team}) has 5 fouls, one away from fouling out{where}.", team=p.team, weight=3)
            elif period <= 3 and p.fouls >= period + 1 and (p.starter or p.minutes >= 12):
                when = "in the first half" if period <= 2 else f"with {_clock_text(clock)} left in Q3"
                note("foul_trouble", f"{p.name} ({p.team}) has {p.fouls} fouls {when}.", team=p.team, weight=2)

        # Hot hands: on pace for a big night (36+ over 48 minutes) and shooting well, or a pile of threes.
        played = max(now, 300.0)
        hot = [
            p for p in snap.players
            if (p.points >= 12 and p.points / played * 2880 >= 36 and (p.fga == 0 or p.fgm / p.fga >= 0.5))
            or p.tpm >= 5
        ]
        for p in sorted(hot, key=lambda x: -x.points)[:2]:
            threes = f", {p.tpm} threes" if p.tpm >= 3 else ""
            court = "" if p.on_court else " (on the bench right now)"
            note("hot_hand", f"{p.name} ({p.team}) has {p.points} on {p.fgm} of {p.fga} shooting{threes}{court}.", team=p.team)

        # Runs: the biggest lopsided stretch of scoring that runs up to now, within 5 minutes.
        run = _best_run(snap.scoring, now, set(teams))
        if run:
            team, a, b, secs = run
            note("run", f"{team} is on a {a}-{b} run over the last {_clock_text(secs)}.", team=team, weight=2)

        # Scoring pace over the last 5 minutes against this game's own pace.
        if now >= 600:
            recent = sum(r["last5"] for r in team_rows)
            usual = game.total / now * 300
            if usual > 0 and recent >= usual * 1.3 and recent - usual >= 6:
                note("scoring_hot", f"{recent} points in the last 5 minutes, faster than this game's usual {usual:.0f}.", lean="up", weight=2)
            elif usual > 0 and recent <= usual * 0.7 and usual - recent >= 6:
                note("scoring_cold", f"Only {recent} points in the last 5 minutes, slower than this game's usual {usual:.0f}.", lean="down", weight=2)

        # Benches in: late in lopsided games coaches rest their starters.
        if period >= 4:
            benched = [r["abbr"] for r in team_rows if r["on_court"] and r["starters_on"] <= 1]
            if len(benched) == 2:
                note("bench_in", "Both teams have their benches in.", weight=1)
            elif benched:
                note("bench_in", f"{benched[0]} has its bench in.", team=benched[0], weight=1)

    for name in snap.ejected:
        note("ejection", f"{name} was ejected.", weight=2)

    notes.sort(key=lambda n: -n["weight"])
    out_by_team: dict[str, list[str]] = {}
    for team, name in snap.out:
        out_by_team.setdefault(team, []).append(name)
    return {
        "source": snap.source,
        "updated_at": now_iso(),
        "period": period,
        "teams": team_rows,
        "notes": notes,
        "out": [{"team": t, "names": n} for t, n in out_by_team.items()],
        "players": [{**asdict(p), "short": p.short} for p in snap.players],
    }


def _best_run(scoring: list[tuple[float, str, int]], now: float, teams: set[str]) -> Optional[tuple[str, int, int, float]]:
    """The most lopsided stretch of scoring ending at the latest basket, within 5 minutes."""
    recent = [s for s in scoring if now - 300 <= s[0] <= now and s[1] in teams]
    if not recent:
        return None
    best: Optional[tuple[str, int, int, float]] = None
    pts: dict[str, int] = {t: 0 for t in teams}
    for t, team, p in reversed(recent):
        pts[team] += p
        for leader in teams:
            trail = next(x for x in teams if x != leader)
            a, b = pts[leader], pts[trail]
            # A run is lopsided: 10-0, 12-4, 14-6. Not 22-12 over five minutes.
            if a >= 10 and a - b >= 8 and b <= a * 0.45 and (best is None or a - b > best[1] - best[2]):
                best = (leader, a, b, max(now - t, 60.0))
    return best


def pattern_keys(game: Game) -> list[str]:
    """The pattern keys showing for a game right now, for memory tags and trade records."""
    ctx = game.context or {}
    return sorted({n["key"] for n in ctx.get("notes", [])})


def pattern_texts(game: Game, limit: int = 6) -> list[str]:
    ctx = game.context or {}
    return [n["text"] for n in ctx.get("notes", [])[:limit]]


# ---------------------------------------------------------------------------- ESPN
FOUL_EXCLUDE = ("offensive", "technical", "double")


def parse_espn(data: dict[str, Any], fix_abbr: dict[str, str]) -> Snapshot:
    """ESPN's game summary -> Snapshot. Who is on the floor: the starters, then every substitution."""
    fix = lambda a: fix_abbr.get(a, a)  # noqa: E731
    players: list[PlayerLine] = []
    by_id: dict[str, PlayerLine] = {}
    for side in (data.get("boxscore") or {}).get("players") or []:
        abbr = fix((side.get("team") or {}).get("abbreviation", ""))
        stats = (side.get("statistics") or [{}])[0]
        names = stats.get("names") or []
        for a in stats.get("athletes") or []:
            if a.get("didNotPlay"):
                continue
            ath = a.get("athlete") or {}
            vals = dict(zip(names, a.get("stats") or []))
            if not vals:
                continue
            p = PlayerLine(id=str(ath.get("id", "")), name=ath.get("displayName", "?"), team=abbr, starter=bool(a.get("starter")))
            p.minutes = _num(vals.get("MIN"))
            p.points = int(_num(vals.get("PTS")))
            p.fgm, p.fga = _pair(vals.get("FG"))
            p.tpm, p.tpa = _pair(vals.get("3PT"))
            p.ftm, p.fta = _pair(vals.get("FT"))
            p.fouls = int(_num(vals.get("PF")))
            p.plus_minus = int(_num(vals.get("+/-")))
            players.append(p)
            by_id[p.id] = p

    team_ids = {
        str((t.get("team") or {}).get("id")): fix((t.get("team") or {}).get("abbreviation", ""))
        for t in (data.get("boxscore") or {}).get("teams") or []
    }
    snap = Snapshot(players=players)
    on: dict[str, set[str]] = {}
    for p in players:
        if p.starter:
            on.setdefault(p.team, set()).add(p.id)
    for play in data.get("plays") or []:
        kind = ((play.get("type") or {}).get("text") or "")
        text = play.get("text") or ""
        period = int((play.get("period") or {}).get("number") or 0)
        clock = _clock(((play.get("clock") or {}).get("displayValue")) or "0")
        team = team_ids.get(str((play.get("team") or {}).get("id")))
        parts = [str((x.get("athlete") or {}).get("id")) for x in play.get("participants") or []]
        if kind == "Substitution" and len(parts) >= 2:
            entering, leaving = by_id.get(parts[0]), by_id.get(parts[1])
            if entering and leaving:
                on.setdefault(entering.team, set()).discard(leaving.id)
                on[entering.team].add(entering.id)
        elif "Foul" in kind and team and not any(x in kind.lower() for x in FOUL_EXCLUDE):
            snap.fouls.append((team, period, clock))
        if play.get("scoringPlay") and team:
            snap.scoring.append((elapsed_at(period, clock), team, int(play.get("scoreValue") or 0)))
        if "ejected" in text.lower() and parts and parts[0] in by_id:
            snap.ejected.append(by_id[parts[0]].name)

    # (ESPN's "active" flag is not who is on the floor, so substitutions are the only source.)
    for ids in on.values():
        for pid in ids:
            if pid in by_id:
                by_id[pid].on_court = True

    for team in data.get("injuries") or []:
        abbr = fix((team.get("team") or {}).get("abbreviation", ""))
        for inj in team.get("injuries") or []:
            if (inj.get("status") or "").lower() == "out":
                snap.out.append((abbr, (inj.get("athlete") or {}).get("displayName", "?")))
    return snap


def _num(v: Any) -> float:
    try:
        return float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return 0.0


def _pair(v: Any) -> tuple[int, int]:
    try:
        made, att = str(v).split("-")
        return int(made), int(att)
    except (TypeError, ValueError):
        return 0, 0


def _clock(display: str) -> float:
    try:
        if ":" in display:
            m, s = display.split(":")
            return int(m) * 60 + float(s)
        return float(display)
    except ValueError:
        return 0.0
