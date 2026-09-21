import json
from pathlib import Path

from kalshi_bot.models import MatchState
from kalshi_bot.rem import remaining_goals
from kalshi_bot.store import Store
from kalshi_bot.watcher.detector import detect_events


def test_recorded_fixture_replay(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "match_replay.json").read_text())
    store = Store(str(tmp_path / "replay.sqlite"))
    game = fixture["game"]
    store.upsert_game({**game, "status": "live"})
    for market in fixture["markets"]:
        store.upsert_market({**market, "game_id": game["id"]})

    previous = None
    fired: list[str] = []
    for tick in fixture["ticks"]:
        current = MatchState(**tick)
        events = detect_events(previous, current)
        for event in events:
            event_id = store.add_event(game["id"], event.event_type, event.minute, event.payload)
            assert event_id > 0
            fired.append(event.event_type)
            rem = remaining_goals(2.5, current.total_goals)
            store.upsert_market(
                {**fixture["markets"][0], "game_id": game["id"], "rem": rem}
            )
        store.update_game_state(
            game["id"],
            home_goals=current.home_goals,
            away_goals=current.away_goals,
            minute=current.minute,
            phase=current.phase,
            status="finished" if current.phase == "full_time" else "live",
        )
        previous = current

    assert fired == ["goal", "half_time", "second_half_start", "goal", "full_time"]
    saved = store.get_game(game["id"])
    assert saved["status"] == "finished"
    assert saved["home_goals"] == 1
    assert saved["away_goals"] == 1
    assert saved["markets"][0]["rem"] == 0.5
    assert [e["event_type"] for e in store.events_for_game(game["id"])] == fired
    store.close()
