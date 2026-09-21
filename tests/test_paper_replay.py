from kalshi_bot.config import Settings
from kalshi_bot.demo import seed_demo
from kalshi_bot.replay import list_fixtures, replay_fixture, resolve_fixture
from kalshi_bot.store import Store


def test_recorded_replay_persists_would_decisions(tmp_path):
    store = Store(str(tmp_path / "replay.sqlite"))
    fixture = resolve_fixture(fixture_id="milan-lecce-2026-09-20")
    result = replay_fixture(store, fixture, Settings())
    actions = {row["action"] for row in result["decisions"]}
    assert "would-place" in actions
    assert "would-skip" in actions
    assert "would-flatten" in actions
    placed = [r for r in result["decisions"] if r["action"] == "would-place" and r["agent"] == "kalshi"]
    assert placed
    assert placed[0]["size"] > 0
    assert placed[0]["price"]
    assert placed[0]["rem"] is not None
    assert result["game"]["status"] == "finished"
    assert store.is_paper() is True
    store.close()


def test_seed_demo_includes_replay_and_live_decisions(tmp_path):
    store = Store(str(tmp_path / "demo.sqlite"))
    seed_demo(store)
    live = store.decisions_for_game("DEMO-LALIGA-RMAFCB")
    replay = store.decisions_for_game("REPLAY-SERIEA-ACMLEC")
    assert live
    assert replay
    assert any(r["action"] == "would-place" for r in live + replay)
    assert any(r["action"] == "would-skip" for r in live + replay)
    names = {item["id"] for item in list_fixtures()}
    assert "milan-lecce-2026-09-20" in names
    store.close()
