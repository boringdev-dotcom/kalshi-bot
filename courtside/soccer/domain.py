"""Leagues, matches and Kalshi soccer markets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class League:
    key: str
    name: str
    espn: str  # ESPN's league code
    kalshi: str  # Kalshi series prefix
    avg_goals: float  # league scoring level, a fallback when there are no odds


LEAGUES = [
    League("epl", "Premier League", "eng.1", "KXEPL", 2.85),
    League("laliga", "LaLiga", "esp.1", "KXLALIGA", 2.6),
    League("seriea", "Serie A", "ita.1", "KXSERIEA", 2.65),
    League("bundesliga", "Bundesliga", "ger.1", "KXBUNDESLIGA", 3.1),
    League("ligue1", "Ligue 1", "fra.1", "KXLIGUE1", 2.75),
]
LEAGUE_BY_KEY = {lg.key: lg for lg in LEAGUES}

# Kalshi series per league: (suffix, segment, kind). Segment "match" is the full 90 minutes
# plus stoppage time (no extra time in league play); "1h" is the first half.
SERIES = [
    ("GAME", "match", "winner"),
    ("TOTAL", "match", "total"),
    ("SPREAD", "match", "spread"),
    ("1H", "1h", "winner"),
    ("1HTOTAL", "1h", "total"),
    ("1HSPREAD", "1h", "spread"),
]


@dataclass
class Side:
    id: str
    abbr: str
    name: str
    short: str
    color: str = "8b9cff"
    logo: str = ""
    score: int = 0
    half_score: Optional[int] = None  # goals in the first half, once known
    red_cards: int = 0
    code: str = ""  # Kalshi's code for the team, once matched


@dataclass
class SMarket:
    """One Kalshi soccer market. YES is the outcome in its title; NO is everything else."""

    ticker: str
    segment: str  # match | 1h
    kind: str  # winner | total | spread
    outcome: Optional[str]  # home | away | tie (winner, spread); None for totals
    strike: Optional[float]  # goal line for totals and spreads
    title: str = ""
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None
    volume: float = 0.0
    result: str = ""
    p_yes: Optional[float] = None  # the model's probability of YES

    def ask(self, side: str) -> Optional[int]:
        return self.yes_ask if side == "yes" else self.no_ask

    def bid(self, side: str) -> Optional[int]:
        return self.yes_bid if side == "yes" else self.no_bid

    def label(self, side: str, match: "Match") -> str:
        """Plain words for one side of this market, e.g. 'Arsenal to win' or 'Under 2.5 goals'."""
        team = {"home": match.home.short, "away": match.away.short}.get(self.outcome or "", "")
        half = "1st half: " if self.segment == "1h" else ""
        yes = side == "yes"
        if self.kind == "winner":
            if self.outcome == "tie":
                text = "Draw" if yes else "Not a draw"
            else:
                text = f"{team} to win" if yes else f"{team} not to win"
        elif self.kind == "total":
            text = f"{'Over' if yes else 'Under'} {self.strike:g} goals"
        else:
            need = int((self.strike or 0) + 0.5)
            text = f"{team} by {need}+" if yes else f"{team} not by {need}+"
        return half + text


@dataclass
class Match:
    id: str  # "soccer-<ESPN event id>"
    league: str
    home: Side
    away: Side
    start_time: str
    state: str = "pre"  # pre | live | final
    period: int = 0  # 1, 2; 0 before kickoff
    minute: float = 0.0  # match minute, e.g. 67.5
    clock: str = ""  # ESPN's display, e.g. "67'" or "45'+2'"
    status: str = ""  # e.g. "Halftime", "Second Half", "Full Time"
    halftime: bool = False
    event_suffix: Optional[str] = None  # Kalshi's, e.g. "26NOV21MCIFUL"
    odds: Optional[dict[str, Any]] = None  # pre-match bookmaker odds, devigged
    lam_home: Optional[float] = None  # pre-match expected goals
    lam_away: Optional[float] = None
    prior_source: str = ""
    markets: list[SMarket] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # goals, cards, subs
    stats: dict[str, dict[str, float]] = field(default_factory=dict)  # by stat name: {home, away}
    commentary: list[dict[str, Any]] = field(default_factory=list)
    projection: Optional[dict[str, Any]] = None
    summary_final: bool = False  # the summary has been read after full time

    @property
    def label(self) -> str:
        return f"{self.home.short} vs {self.away.short}"

    @property
    def first_half_over(self) -> bool:
        return self.state == "final" or self.halftime or self.period >= 2

    def market(self, ticker: str) -> Optional[SMarket]:
        return next((m for m in self.markets if m.ticker == ticker), None)

    def segment_score(self, segment: str) -> tuple[int, int]:
        if segment == "1h":
            if self.period <= 1 and not self.halftime and self.state != "final":
                return self.home.score, self.away.score
            if self.home.half_score is not None and self.away.half_score is not None:
                return self.home.half_score, self.away.half_score
            return self.home.score, self.away.score  # best guess until the summary says
        return self.home.score, self.away.score

    def segment_done(self, segment: str) -> bool:
        if segment == "1h":
            return self.first_half_over and (self.home.half_score is not None or self.state == "final")
        return self.state == "final"

    def settles_yes(self, m: SMarket) -> Optional[bool]:
        """Whether a market's YES won, once its segment is over. None while it is still open."""
        if m.result in ("yes", "no"):
            return m.result == "yes"
        if not self.segment_done(m.segment):
            return None
        h, a = self.segment_score(m.segment)
        return outcome_yes(m, h, a)


def outcome_yes(m: SMarket, home: int, away: int) -> bool:
    if m.kind == "winner":
        return {"home": home > away, "away": away > home, "tie": home == away}[m.outcome or "tie"]
    if m.kind == "total":
        return home + away > (m.strike or 0)
    margin = home - away if m.outcome == "home" else away - home
    return margin > (m.strike or 0)
