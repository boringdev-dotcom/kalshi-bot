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


@dataclass
class Team:
    abbr: str
    name: str
    score: int = 0
    color: str = "8b9cff"


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

    def rung(self, ticker: str) -> Optional[Rung]:
        for r in self.ladder:
            if r.ticker == ticker:
                return r
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("clock_seconds")
        for r in d["ladder"]:
            r.pop("result")
        d.update(
            label=self.label,
            total=self.total,
            margin=self.margin,
            seconds_remaining=round(self.seconds_remaining),
        )
        return d


def fmt_clock(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"0:{int(seconds):02d}"
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
