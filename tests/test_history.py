"""The account chart: ranges, and deposits/withdrawals left out of the gains."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from courtside.api.app import create_app
from courtside.history import adjusted_history
from tests.test_core import bare_config, make_engine

T0 = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_a_deposit_is_not_a_gain():
    # 900 -> 880 (a loss), then $250 deposited (seen a minute after Kalshi's stamp), then 1140 (a $10 gain).
    rows = [{"ts": at(0), "equity": 900.0}, {"ts": at(10), "equity": 880.0}, {"ts": at(21), "equity": 1130.0}, {"ts": at(30), "equity": 1140.0}]
    flows = [{"ts": at(20), "amount": 250.0}]
    h = adjusted_history(rows, flows, {"ts": at(40), "equity": 1140.0})
    values = [p["value"] for p in h["points"]]
    assert values == [1150.0, 1130.0, 1130.0, 1140.0, 1140.0]  # no jump; ends at today's value
    assert h["change"] == -10.0 and h["net_deposits"] == 250.0 and h["end"] == 1140.0

    # A range that starts after the deposit is untouched by it.
    late = adjusted_history(rows, flows, {"ts": at(40), "equity": 1140.0}, since=T0 + timedelta(minutes=25))
    assert [p["value"] for p in late["points"]] == [1130.0, 1140.0, 1140.0] and late["net_deposits"] == 0.0
    assert late["points"][0]["ts"] == at(25) and late["change"] == 10.0


def test_a_withdrawal_and_thinning_a_long_history():
    rows = [{"ts": at(i), "equity": 500.0 + i * 0.1} for i in range(1000)]
    for r in rows[600:]:
        r["equity"] -= 200.0  # $200 withdrawn at minute 600
    h = adjusted_history(rows, [{"ts": at(599.5), "amount": -200.0}], {"ts": at(1000), "equity": rows[-1]["equity"]}, max_points=120)
    assert len(h["points"]) <= 121
    steps = [b["value"] - a["value"] for a, b in zip(h["points"], h["points"][1:])]
    assert max(abs(s) for s in steps) < 5  # the withdrawal leaves no cliff
    assert h["net_deposits"] == -200.0 and abs(h["change"] - 99.9) < 0.01


def test_history_route_by_range(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    app = create_app(db_path=str(tmp_path / "a.db"), start_engine=False, cfg=bare_config())
    with TestClient(app) as client:
        engine = app.state.engine
        now = datetime.now(timezone.utc)
        for days, eq in ((40, 10000.0), (5, 10100.0), (0.01, 10150.0)):
            engine.db.insert("equity", {"ts": (now - timedelta(days=days)).isoformat(timespec="seconds"), "book": engine.book, "equity": eq})
        all_ = client.get("/api/account/history").json()
        week = client.get("/api/account/history", params={"since": (now - timedelta(days=7)).isoformat().replace("+00:00", "Z")}).json()
        assert client.get("/api/account/history", params={"since": "soon"}).status_code == 422
    assert [p["value"] for p in all_["points"][:3]] == [10000.0, 10100.0, 10150.0] and len(all_["points"]) == 4
    # A week starts at what the account held a week ago.
    assert [p["value"] for p in week["points"][:3]] == [10000.0, 10100.0, 10150.0] and len(week["points"]) == 4
    assert week["points"][1]["ts"] > week["points"][0]["ts"]


def test_live_snapshots_wait_for_kalshis_balance():
    engine = make_engine()
    engine.settings["trading_mode"], engine.settings["data_source"] = "live", "live"
    assert engine.book == "live"
    engine._snapshot_equity()
    assert engine.db.query("SELECT * FROM equity") == []  # no fake $0 point before the balance is read
