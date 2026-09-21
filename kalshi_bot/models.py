"""Shared dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


PHASES = (
    "upcoming",
    "first_half",
    "half_time",
    "second_half",
    "extra_time",
    "full_time",
    "unknown",
)

EVENT_TYPES = (
    "goal",
    "half_time",
    "second_half_start",
    "red_card",
    "full_time",
)

VERDICTS = ("watch", "real_bet", "pass", "flatten_hint")


@dataclass
class MatchState:
    home_goals: int = 0
    away_goals: int = 0
    minute: int = 0
    phase: str = "upcoming"
    red_cards: int = 0
    source: str = ""

    @property
    def total_goals(self) -> int:
        return self.home_goals + self.away_goals

    def as_dict(self) -> dict[str, Any]:
        return {
            "home_goals": self.home_goals,
            "away_goals": self.away_goals,
            "total_goals": self.total_goals,
            "minute": self.minute,
            "phase": self.phase,
            "red_cards": self.red_cards,
            "source": self.source,
        }


@dataclass
class DetectedEvent:
    event_type: str
    minute: int
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketQuote:
    ticker: str
    strike: float
    rem: float
    no_bid: Optional[int] = None
    no_ask: Optional[int] = None
    no_depth: Optional[int] = None
    yes_bid: Optional[int] = None
    yes_ask: Optional[int] = None
    title: str = ""

    @property
    def no_mid(self) -> Optional[float]:
        if self.no_bid is None or self.no_ask is None:
            return None
        return (self.no_bid + self.no_ask) / 2.0


@dataclass
class PunditVerdict:
    ticker: str
    verdict: str
    size_hint: int
    reason: str
    strike: Optional[float] = None
    rem: Optional[float] = None
