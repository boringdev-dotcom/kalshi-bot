"""Diff MatchState snapshots into material events."""

from __future__ import annotations

from typing import Optional

from kalshi_bot.models import DetectedEvent, MatchState


def detect_events(previous: Optional[MatchState], current: MatchState) -> list[DetectedEvent]:
    """Fire only on goal, half-time, second-half start, red card, full-time."""
    if previous is None:
        return _bootstrap_events(current)

    events: list[DetectedEvent] = []
    prev_goals = previous.total_goals
    curr_goals = current.total_goals
    if curr_goals > prev_goals:
        events.append(
            DetectedEvent(
                "goal",
                current.minute,
                {
                    "home_goals": current.home_goals,
                    "away_goals": current.away_goals,
                    "prev_home": previous.home_goals,
                    "prev_away": previous.away_goals,
                    "goals_added": curr_goals - prev_goals,
                },
            )
        )
    if current.red_cards > previous.red_cards:
        events.append(
            DetectedEvent(
                "red_card",
                current.minute,
                {"red_cards": current.red_cards, "prev_red_cards": previous.red_cards},
            )
        )
    if previous.phase != "half_time" and current.phase == "half_time":
        events.append(DetectedEvent("half_time", current.minute or 45, {"phase": current.phase}))
    if previous.phase == "half_time" and current.phase in {"second_half", "extra_time"}:
        events.append(
            DetectedEvent("second_half_start", current.minute or 45, {"phase": current.phase})
        )
    if previous.phase != "full_time" and current.phase == "full_time":
        events.append(
            DetectedEvent(
                "full_time",
                current.minute or 90,
                {
                    "home_goals": current.home_goals,
                    "away_goals": current.away_goals,
                },
            )
        )
    return events


def _bootstrap_events(current: MatchState) -> list[DetectedEvent]:
    """If we join a match already in a later phase, do not replay past goals."""
    if current.phase == "full_time":
        return [DetectedEvent("full_time", current.minute or 90, current.as_dict())]
    return []
