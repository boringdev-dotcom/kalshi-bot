"""Match Kalshi soccer totals to FotMob/ESPN fixtures."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from . import espn, fotmob

NOISE = {
    "fc",
    "cf",
    "afc",
    "sc",
    "united",
    "city",
    "town",
    "hotspur",
    "wanderers",
    "athletic",
    "club",
    "de",
    "the",
    "and",
}


def normalize(name: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = [tok for tok in text.split() if tok not in NOISE]
    return " ".join(tokens) or text.strip()


def token_set(name: str) -> set[str]:
    return {tok for tok in normalize(name).split() if len(tok) > 1}


def name_score(left: str, right: str) -> float:
    a, b = token_set(left), token_set(right)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    if normalize(left) == normalize(right):
        return 1.0
    if normalize(left) in normalize(right) or normalize(right) in normalize(left):
        return 0.9
    return overlap / max(len(a), len(b))


def pair_score(home_a: str, away_a: str, home_b: str, away_b: str) -> float:
    straight = (name_score(home_a, home_b) + name_score(away_a, away_b)) / 2
    swapped = (name_score(home_a, away_b) + name_score(away_a, home_b)) / 2
    return max(straight, swapped)


def parse_teams_from_title(title: str) -> tuple[str, str]:
    for sep in (" vs. ", " vs ", " v ", " @ ", " - "):
        if sep in title.lower() or sep in title:
            parts = re.split(re.escape(sep), title, maxsplit=1, flags=re.I)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
    return title.strip(), ""


def match_fixture(
    home: str,
    away: str,
    kickoff_ts: Optional[int],
    fixtures: list[dict[str, Any]],
    window_sec: int = 90 * 60,
) -> Optional[dict[str, Any]]:
    best: Optional[dict[str, Any]] = None
    best_score = 0.0
    for fixture in fixtures:
        score = pair_score(home, away, fixture.get("home") or "", fixture.get("away") or "")
        fk = fixture.get("kickoff_ts")
        if kickoff_ts and fk:
            delta = abs(int(fk) - int(kickoff_ts))
            if delta > window_sec:
                continue
            score += max(0.0, 0.25 - (delta / window_sec) * 0.25)
        if score > best_score:
            best_score = score
            best = fixture
    if best and best_score >= 0.55:
        best = dict(best)
        best["match_score"] = best_score
        return best
    return None


def gather_fixtures(kickoff_ts: Optional[int]) -> list[dict[str, Any]]:
    days = []
    if kickoff_ts:
        center = datetime.fromtimestamp(kickoff_ts, tz=timezone.utc)
        days = [center]
    else:
        days = [datetime.now(tz=timezone.utc)]
    fixtures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for day in days:
        for item in fotmob.matches_for_date(day) + espn.scoreboard(day):
            key = (item.get("home") or "", item.get("away") or "", str(item.get("kickoff_ts")))
            if key in seen:
                continue
            seen.add(key)
            fixtures.append(item)
    return fixtures
