from kalshi_bot.models import MatchState
from kalshi_bot.watcher.detector import detect_events


def test_goal_event():
    prev = MatchState(0, 0, 22, "first_half")
    curr = MatchState(1, 0, 23, "first_half")
    events = detect_events(prev, curr)
    assert [e.event_type for e in events] == ["goal"]
    assert events[0].payload["goals_added"] == 1


def test_half_time_and_second_half():
    first = MatchState(1, 0, 45, "first_half")
    ht = MatchState(1, 0, 45, "half_time")
    second = MatchState(1, 0, 46, "second_half")
    assert detect_events(first, ht)[0].event_type == "half_time"
    assert detect_events(ht, second)[0].event_type == "second_half_start"


def test_red_card_and_full_time():
    prev = MatchState(1, 1, 80, "second_half", red_cards=0)
    red = MatchState(1, 1, 81, "second_half", red_cards=1)
    ft = MatchState(1, 1, 90, "full_time", red_cards=1)
    assert detect_events(prev, red)[0].event_type == "red_card"
    assert detect_events(red, ft)[0].event_type == "full_time"


def test_minute_only_does_not_fire():
    prev = MatchState(0, 0, 10, "first_half")
    curr = MatchState(0, 0, 11, "first_half")
    assert detect_events(prev, curr) == []


def test_bootstrap_skips_in_progress():
    live = MatchState(2, 1, 67, "second_half")
    assert detect_events(None, live) == []
