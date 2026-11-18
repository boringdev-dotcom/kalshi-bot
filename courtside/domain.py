"""Core data shapes shared by feeds, the model, the agent and the API.

These mirror frontend/src/types.ts. Prices are integer cents, money is dollars.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

REG_SECONDS = 2880
QUARTER_SECONDS = 720
OT_SECONDS = 300


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SEGMENTS = ("q1", "q2", "q3", "q4")


@dataclass
class Team:
    abbr: str
    name: str
    score: int = 0
    color: str = "8b9cff"
    # Points by period: [Q1, Q2, Q3, Q4, OT...]. The current period is a running count.
    quarters: list[int] = field(default_factory=list)

    def quarter(self, q: int) -> int:
        return self.quarters[q - 1] if 0 < q <= len(self.quarters) else 0

    def add_points(self, points: int, period: int) -> None:
        """Score during `period`, keeping the by-quarter line in step with the total."""
        self.score += points
        while len(self.quarters) < period:
            self.quarters.append(0)
        if period >= 1:
            self.quarters[period - 1] += points


@dataclass
class Projection:
    mean: float
    sd: float
    p_ot: float
    pace: float


@dataclass
class FanDuelOdds:
    total_line: Optional[float] = None
    over_price: Optional[int] = None
    under_price: Optional[int] = None
    spread: Optional[float] = None
    home_ml: Optional[int] = None
    away_ml: Optional[int] = None
    live: bool = False
    source: str = "fanduel"
    updated_at: str = field(default_factory=now_iso)


@dataclass
class Rung:
    """One Kalshi YES/NO market.

    total  - YES = over the strike, NO = under.
    spread - YES = `team` wins the segment by more than the strike, NO = they do not.

    The price and probability fields keep the totals vocabulary: "over" is
    always the YES side and "under" always the NO side.
    """

    ticker: str
    strike: float
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None
    p_under: float = 0.5
    edge_under: Optional[float] = None
    edge_over: Optional[float] = None
    volume: float = 0.0
    result: str = ""  # "yes" | "no" once settled on the exchange
    segment: str = "game"  # game | q1 | q2 | q3 | q4
    kind: str = "total"  # total | spread
    team: Optional[str] = None  # spread only: the team YES backs
    other_team: Optional[str] = None  # spread only: their opponent

    def label(self, side: str) -> str:
        """Short name for one side, e.g. "Under 58.5", "HOU -3.5", "IND +3.5"."""
        if self.kind == "spread":
            return f"{self.team} -{self.strike:g}" if side == "over" else f"{self.other_team or 'Opp'} +{self.strike:g}"
        return f"{'Over' if side == 'over' else 'Under'} {self.strike:g}"

    def position_label(self, side: str) -> str:
        prefix = "" if self.segment == "game" else self.segment.upper() + " "
        return prefix + self.label(side)

    def ask(self, side: str) -> Optional[int]:
        return self.no_ask if side == "under" else self.yes_ask

    def bid(self, side: str) -> Optional[int]:
        return self.no_bid if side == "under" else self.yes_bid


@dataclass
class Risk:
    level: str = "low"
    flags: list[str] = field(default_factory=list)


@dataclass
class Game:
    id: str
    home: Team
    away: Team
    state: str = "pre"  # pre | live | final
    period: int = 0
    clock: str = "12:00"
    clock_seconds: float = 720.0
    start_time: str = field(default_factory=now_iso)
    event_ticker: Optional[str] = None
    pregame_total: Optional[float] = None
    projection: Optional[Projection] = None
    fanduel: Optional[FanDuelOdds] = None
    ladder: list[Rung] = field(default_factory=list)
    # Quarter markets by segment: {"q1": {"total": [...], "spread": [...]}, ...}
    quarter_markets: dict[str, dict[str, list[Rung]]] = field(default_factory=dict)
    quarter_view: list[dict[str, Any]] = field(default_factory=list)  # filled by the model each tick
    risk: Risk = field(default_factory=Risk)
    simulated: bool = False

    @property
    def label(self) -> str:
        return f"{self.away.abbr} @ {self.home.abbr}"

    @property
    def total(self) -> int:
        return self.home.score + self.away.score

    @property
    def margin(self) -> int:
        return abs(self.home.score - self.away.score)

    @property
    def seconds_remaining(self) -> float:
        """Regulation seconds left. 0 once regulation is over."""
        if self.state == "final" or self.period > 4:
            return 0.0
        if self.state == "pre" or self.period < 1:
            return float(REG_SECONDS)
        return (4 - self.period) * QUARTER_SECONDS + self.clock_seconds

    @property
    def elapsed(self) -> float:
        """Game seconds played, including overtime."""
        if self.state == "pre":
            return 0.0
        if self.period <= 4:
            return REG_SECONDS - self.seconds_remaining
        played_ot = (self.period - 5) * OT_SECONDS + (OT_SECONDS - self.clock_seconds)
        return REG_SECONDS + played_ot

    @property
    def minutes_left(self) -> float:
        return self.seconds_remaining / 60.0

    @property
    def at_q3_end(self) -> bool:
        """The break between the third and fourth quarters."""
        return self.state == "live" and self.period == 3 and self.clock_seconds <= 0

    @property
    def in_fourth(self) -> bool:
        """Fourth-quarter territory for the Q4 play: from the Q3 horn onward."""
        return self.state == "live" and (self.period == 4 or self.at_q3_end)

    @property
    def q4_clock(self) -> str:
        """Time left in the fourth as text. The break after Q3 reads as a full 12:00."""
        return "12:00" if self.at_q3_end else self.clock

    def all_rungs(self):
        yield from self.ladder
        for kinds in self.quarter_markets.values():
            for rungs in kinds.values():
                yield from rungs

    def rung(self, ticker: str) -> Optional[Rung]:
        for r in self.all_rungs():
            if r.ticker == ticker:
                return r
        return None

    # -- quarters -------------------------------------------------------------
    def quarter_status(self, q: int) -> str:
        """upcoming | live | final. A quarter is final once the next period has begun."""
        if self.state == "final" or (self.state == "live" and self.period > q):
            return "final"
        if self.state == "live" and self.period == q:
            return "live"
        return "upcoming"

    def quarter_seconds_left(self, q: int) -> float:
        status = self.quarter_status(q)
        if status == "final":
            return 0.0
        return max(self.clock_seconds, 0.0) if status == "live" else float(QUARTER_SECONDS)

    def quarter_points(self, q: int) -> tuple[int, int]:
        """(home, away) points in quarter q. Derives the running quarter when the feed has no line for it."""
        if self.quarter_status(q) == "upcoming":
            return 0, 0
        out = []
        for team in (self.home, self.away):
            if len(team.quarters) >= q:
                out.append(team.quarters[q - 1])
            elif self.period == q:
                out.append(max(team.score - sum(team.quarters[: q - 1]), 0))
            else:
                out.append(0)
        return out[0], out[1]

    def settle_value(self, segment: str, kind: str, team: Optional[str]) -> Optional[float]:
        """The number a market settles on, or None while it is still open.

        Totals settle on points scored; spreads on the backed team's margin.
        Quarter markets settle when their quarter ends; Q4 excludes overtime.
        """
        if segment == "game":
            if self.state != "final":
                return None
            home, away = self.home.score, self.away.score
        else:
            q = int(segment[1])
            if self.quarter_status(q) != "final":
                return None
            home, away = self.quarter_points(q)
        if kind == "total":
            return float(home + away)
        return float(home - away) if team == self.home.abbr else float(away - home)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("clock_seconds")
        d.pop("quarter_markets")  # heavy: served with the game detail, not on every tick
        d["quarters"] = d.pop("quarter_view")
        d["ladder"] = [rung_dict(r) for r in self.ladder]
        d.update(
            label=self.label,
            total=self.total,
            margin=self.margin,
            seconds_remaining=round(self.seconds_remaining),
        )
        return d


def rung_dict(r: Rung) -> dict[str, Any]:
    d = asdict(r)
    d.pop("result")
    d.pop("other_team")
    d["yes_label"], d["no_label"] = r.label("over"), r.label("under")
    return d


def fmt_clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"0:{int(seconds):02d}"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
