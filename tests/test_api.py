from fastapi.testclient import TestClient

from kalshi_bot.api.app import create_app
from kalshi_bot.config import Settings
from kalshi_bot.demo import seed_demo
from kalshi_bot.store import Store


def test_watch_and_controls(tmp_path):
    store = Store(str(tmp_path / "api.sqlite"))
    seed_demo(store)
    app = create_app(Settings(sqlite_path=str(tmp_path / "api.sqlite")), store)
    client = TestClient(app)
    assert client.get("/health").json()["ok"] is True
    playbook = client.get("/api/status").json()["playbook"]
    assert playbook["entry_min_minute"] == 60
    assert playbook["entry_max_minute"] == 92
    assert playbook["entry_max_rem"] == 2
    assert playbook["entry_no_price_min"] == 80
    assert playbook["entry_no_price_max"] == 92
    assert playbook["max_contracts_per_match"] == 150
    assert playbook["allowed_tiers"] == [1, 2]
    assert playbook["paper_mode_default"] is True
    paused = client.post("/api/control/pause").json()
    assert paused["paused"] is True
    client.post("/api/control/resume")
    added = client.post(
        "/api/games/watch",
        json={"home_team": "Liverpool", "away_team": "Everton", "league": "premier_league", "tickers": ["KXEPLTOTAL-X-25"]},
    )
    assert added.status_code == 200
    game = added.json()["game"]
    assert game["home_team"] == "Liverpool"
    assert game["id"].startswith("MANUAL-LIVERPOOL-EVERTON")
    live = client.get("/api/games/live").json()["games"]
    assert any(g["home_team"] == "Real Madrid" for g in live)
    costs = client.get("/api/costs").json()
    assert costs["all"]["calls"] >= 2
    status = client.get("/api/status").json()
    assert status["paper"] is True
    assert status["limits"]["max_contracts_per_match"] == 150
    port = client.get("/api/portfolio").json()
    assert "remaining_day" in port["caps"]
    assert port["caps"]["used_today"] >= 0
    learning = client.get("/api/learning").json()
    assert learning["propose_only"] is True
    assert "max_daily_loss_cents" in learning["hard_cap_keys"]
    assert learning["playbook"]["current"] >= 1
    fixtures = client.get("/api/replay/fixtures").json()["fixtures"]
    assert any(f["id"] == "milan-lecce-2026-09-20" for f in fixtures)
    replayed = client.post("/api/replay", json={"fixture_id": "milan-lecce-2026-09-20"}).json()
    assert replayed["paper"] is True
    assert any(d["action"] == "would-place" for d in replayed["decisions"])
    limits = client.post(
        "/api/control/limits",
        json={"max_contracts_per_match": 40, "max_contracts_per_day": 80, "max_daily_loss_cents": 900},
    ).json()
    assert limits["limits"]["max_contracts_per_match"] == 40
    store.close()
