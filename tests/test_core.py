"""Behavioural tests for the model, rules, learner, memory, engine and API."""

from __future__ import annotations

import asyncio
import random

import pytest
from fastapi.testclient import TestClient

from courtside.agent.engine import Engine, TradeError
from courtside.agent.learner import Learner
from courtside.agent.memory import MemoryStore
from courtside.agent.playbook import Q4_UNDER, Playbook
from courtside.agent.policy import arm_key, exit_signal, find_entries, kalshi_fee, size_order, Skip
from courtside.agent.trainer import train
from courtside.api.app import create_app
from courtside.config import Config
from courtside.db import DB
from courtside.domain import FanDuelOdds, Game, Rung, Team
from courtside.events import Hub
from courtside.kalshi.client import cents, side_and_price
from courtside.feeds.live import LiveFeed
from courtside.kalshi.client import KalshiClient
from courtside.model.totals import distribution, implied_total, refresh_game


def q4_game(total=200, clock=360.0, margin=10, line=228.5, strikes=range(229, 262, 2)) -> Game:
    home, away = total // 2 + margin // 2, total - (total // 2 + margin // 2)
    game = Game(
        id="g1", home=Team("CLE", "Cavaliers", home), away=Team("MEM", "Grizzlies", away),
        state="live", period=4, clock_seconds=clock, clock=f"{int(clock // 60)}:{int(clock % 60):02d}",
        pregame_total=228.5, fanduel=FanDuelOdds(total_line=line, live=True),
    )
    game.ladder = [Rung(ticker=f"T{s}", strike=s + 0.5) for s in strikes]
    refresh_game(game)
    return game


def quote(game: Game, discount: float = 0.0) -> None:
    """Price each rung at the model's probability minus `discount`, 2c wide."""
    for r in game.ladder:
        ask = min(99, max(2, round((r.p_under - discount) * 100)))
        r.no_ask, r.no_bid = ask, ask - 2
        r.yes_ask, r.yes_bid = 100 - r.no_bid, 100 - r.no_ask
    refresh_game(game)


# ------------------------------------------------------------------- model
def test_under_probability_rises_with_strike_and_falls_with_time():
    d = distribution(total=190, secs_left=360, margin=10, pregame_total=228)
    probs = [d.p_under(d.mean + k) for k in (0, 5, 10, 15)]
    assert probs == sorted(probs) and 0.4 < probs[0] < 0.65 and probs[-1] > 0.93
    early = distribution(total=170, secs_left=720, margin=10, pregame_total=228)
    assert early.p_under(early.mean + 10) < d.p_under(d.mean + 10)


def test_close_late_games_carry_overtime_and_foul_risk():
    tight = distribution(total=215, secs_left=60, margin=1, pregame_total=228)
    blowout = distribution(total=215, secs_left=60, margin=20, pregame_total=228)
    assert tight.p_ot > 0.15 and blowout.p_ot < 0.001
    assert tight.mean > blowout.mean + 3
    assert tight.p_under(tight.current + 12.5) < blowout.p_under(blowout.current + 12.5)


def test_strike_already_passed_cannot_win():
    d = distribution(total=240, secs_left=100, margin=5, pregame_total=228)
    assert d.p_under(239.5) == 0.0


# ------------------------------------------------------------------ kalshi
def test_v2_order_translation():
    assert side_and_price("under", "buy", 94) == ("ask", "0.0600")  # buy NO 94c = sell YES at 6c
    assert side_and_price("under", "sell", 90) == ("bid", "0.1000")
    assert side_and_price("over", "buy", 12) == ("bid", "0.1200")
    assert side_and_price("over", "sell", 30) == ("ask", "0.3000")
    assert cents("0.9400") == 94 and cents("0.0000") is None and cents(None) is None


def test_fees_and_sizing_match_the_users_example():
    assert kalshi_fee(319, 94) == pytest.approx(1.26)
    contracts, cost, fees = size_order(300, 94)
    assert cost <= 300 and contracts in (317, 318, 319)
    assert 17 < contracts - cost < 21  # "$300 to win about $20"


# ------------------------------------------------------------------ policy
def test_entry_picks_an_under_with_the_right_cushion():
    p = Playbook(DB(":memory:")).params(Q4_UNDER)
    game = q4_game(total=200, clock=300, margin=12)
    quote(game, discount=0.03)
    found = find_entries(game, p)
    assert isinstance(found, list) and found
    line = game.fanduel.total_line
    for c in found:
        assert p["buffer_min"] <= c.rung.strike - line <= p["buffer_max"]
        assert p["min_price"] <= c.price <= p["max_price"]
        assert c.edge * 100 >= p["min_edge"]


def test_entry_skips_fairly_priced_and_tight_games():
    p = Playbook(DB(":memory:")).params(Q4_UNDER)
    rich = q4_game(total=200, clock=300, margin=12)
    quote(rich, discount=-0.03)  # market charges 3 points more than the model thinks it is worth
    skip = find_entries(rich, {**p, "min_price": 80, "max_price": 99, "min_edge": 1.0})
    assert isinstance(skip, Skip) and skip.code == "no_edge"
    tight = q4_game(total=200, clock=240, margin=2)
    quote(tight, discount=0.04)
    skip = find_entries(tight, p)
    assert isinstance(skip, Skip) and skip.code == "close_game"
    assert find_entries(q4_game(clock=700), p) is None  # outside the time window


def test_exit_fires_when_the_game_turns():
    p = Playbook(DB(":memory:")).params(Q4_UNDER)
    game = q4_game(total=200, clock=300, margin=12)
    quote(game)
    rung = next(r for r in game.ladder if r.strike == 241.5)
    assert exit_signal(side="under", strike=241.5, entry_price=rung.no_ask, game=game, rung=rung, p=p) is None
    hot = q4_game(total=226, clock=150, margin=3)  # 26 points in 2:30, now a one-possession game
    quote(hot)
    rung2 = next(r for r in hot.ladder if r.strike == 241.5)
    signal = exit_signal(side="under", strike=241.5, entry_price=rung.no_ask, game=hot, rung=rung2, p=p)
    assert signal is not None and signal.reason in ("risk_exit", "stop_loss")
    assert signal.price == rung2.no_bid


# ----------------------------------------------------------------- learner
def test_learner_turns_against_a_losing_spot_and_discounts_practice():
    learner = Learner(DB(":memory:"), seed=1)
    arm = arm_key(11, 5, 3)
    assert learner.entry_view(arm, 0.96, 94)["ev"] > 0
    for i in range(12):
        learner.record(arm=arm, exit_profile="balanced", ret=-0.2, won=False, p_model=0.96, price_cents=94, simulated=False)
        if i == 2:  # three ugly trades are not yet grounds to overrule the playbook
            assert learner.allows(learner.entry_view(arm, 0.96, 94), 1.0)  # even against an impossible bar
    assert learner.entry_view(arm, 0.96, 94)["ev"] < 0
    assert not learner.allows(learner.entry_view(arm, 0.96, 94), -0.015)
    # Practice in the sandbox never moves a real-market decision, and vice versa.
    other = arm_key(13, 8, 20)
    for _ in range(12):
        learner.record(arm=other, exit_profile="tight", ret=-0.2, won=False, p_model=0.96, price_cents=94, simulated=True)
    assert learner.entry_view(other, 0.96, 94)["ev"] == pytest.approx(learner.entry_view(arm_key(20, 1, 20), 0.96, 94)["ev"])
    learner.env = "sim"
    assert learner.entry_view(other, 0.96, 94)["ev"] < 0 < learner.entry_view(arm, 0.96, 94)["ev"]
    assert len(learner.arms()) == 60 and {a["key"] for a in learner.exit_arms()} == {"tight", "balanced", "patient"}


# ------------------------------------------------------------------ memory
def test_memory_recall_and_reinforcement():
    mem = MemoryStore(DB(":memory:"))
    rule = mem.add("guidance", "Be careful in one-possession games late", tags=["close_game", "late"], source="user")
    mem.add("lesson", "Blowouts coast and stay under", tags=["blowout"])
    hits = mem.recall(["close_game", "nba"], text="tight game")
    assert hits and hits[0]["id"] == rule["id"]
    before = hits[0]["confidence"]
    mem.reinforce([rule["id"]], positive=False)
    mem.reinforce([rule["id"]], positive=False)
    assert mem.get(rule["id"])["confidence"] < before
    assert mem.get(rule["id"])["uses"] == 1


# --------------------------------------------------------- trainer + engine
def test_training_gym_runs_and_feeds_the_learner():
    db = DB(":memory:")
    playbook, learner, memory = Playbook(db), Learner(db, seed=3), MemoryStore(db)
    result = train(db, playbook, learner, memory, episodes=150, seed=7)
    assert result["episodes"] == 150 and result["trades"] > 5
    assert sum(a["sim_n"] for a in learner.arms()) == result["trades"]
    assert sum(a["n"] for a in learner.arms()) == 0  # nothing real was learned
    learner.env = "sim"
    assert sum(a["n"] for a in learner.arms()) == result["trades"]
    assert db.one("SELECT COUNT(*) n FROM positions WHERE training=0")["n"] == 0


def make_engine() -> Engine:
    cfg = Config(_env_file=None, kalshi_api_key_id="", kalshi_private_key_pem="", anthropic_api_key="", odds_api_key="")
    return Engine(cfg, DB(":memory:"), Hub())


def test_engine_trades_the_sim_and_the_books_balance():
    async def run() -> Engine:
        engine = make_engine()
        await engine.update_settings({"sim_speed": 60, "max_open_positions": 6, "max_total_exposure": 3000})
        for _ in range(600):
            engine._last_real -= 1.0  # pretend a second passed
            await engine.tick()
        return engine

    random.seed(5)
    engine = asyncio.run(run())
    closed = engine.db.query("SELECT * FROM positions WHERE status='closed' AND training=0")
    assert closed, "the agent should have traded over ten simulated hours of basketball"
    acct = engine.account()
    realised = sum(r["pnl"] for r in closed)
    assert acct["pnl_total"] == pytest.approx(realised, abs=0.01)
    unrealised = sum(p["pnl"] for p in engine.positions_api())
    assert acct["equity"] == pytest.approx(engine.cfg.paper_starting_cash + realised + unrealised, abs=0.05)
    assert engine.db.one("SELECT COUNT(*) n FROM decisions WHERE kind='enter'")["n"] >= len(closed)
    assert engine.memory.list(kind="episode")
    for row in closed:
        if row["exit_reason"] in ("settled_win", "settled_loss"):
            won = (row["final_total"] < row["strike"]) == (row["side"] == "under")
            assert (row["exit_reason"] == "settled_win") == won


def test_live_mode_is_refused_without_keys_or_live_data():
    async def run() -> None:
        engine = make_engine()
        with pytest.raises(TradeError):
            await engine.update_settings({"trading_mode": "live"})
        assert engine.settings["trading_mode"] == "paper"

    asyncio.run(run())


# --------------------------------------------------------------------- api
def test_api_shapes_and_a_manual_paper_order(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    app = create_app(db_path=str(tmp_path / "t.db"), start_engine=False)
    engine: Engine = app.state.engine
    with TestClient(app) as client:
        asyncio.run(engine.update_settings({"agent_enabled": False, "data_source": "sim"}))
        asyncio.run(engine.tick())
        state = client.get("/api/state").json()
        assert set(state) == {"settings", "health", "agent", "account"}
        games = client.get("/api/games").json()
        live = next(g for g in games if g["state"] == "live" and g["ladder"])
        rung = next(r for r in live["ladder"] if r["no_ask"] and 50 <= r["no_ask"] <= 97)
        detail = client.get(f"/api/games/{live['id']}").json()
        assert detail["timeline"] and {"t", "total", "projected", "lo", "hi", "line"} <= set(detail["timeline"][0])

        bad = client.post("/api/orders", json={"ticker": rung["ticker"], "side": "under", "contracts": 10, "price": 1})
        assert bad.status_code == 400 and "limit" in bad.json()["detail"]
        ok = client.post("/api/orders", json={"ticker": rung["ticker"], "side": "under", "contracts": 10, "price": rung["no_ask"]})
        assert ok.status_code == 200
        pos = ok.json()
        assert pos["contracts"] == 10 and pos["opened_by"] == "user" and pos["simulated"] is True
        assert client.get("/api/positions").json()[0]["id"] == pos["id"]
        trade = client.post(f"/api/positions/{pos['id']}/close").json()
        assert trade["exit_reason"] == "manual" and trade["pnl"] < 0  # paid the spread and fees

        strat = client.put(f"/api/playbook/{Q4_UNDER}", json={"params": {"stake": 250, "buffer_min": 11}}).json()
        values = {p["key"]: p["value"] for p in strat["params"]}
        assert values["stake"] == 250 and values["buffer_min"] == 11
        assert client.put(f"/api/playbook/{Q4_UNDER}", json={"params": {"nope": 1}}).status_code == 400

        mem = client.post("/api/memory", json={"text": "Never trade the second night of a back-to-back"}).json()
        assert mem["kind"] == "guidance" and mem["pinned"] and mem["source"] == "user"
        assert client.patch(f"/api/memory/{mem['id']}", json={"pinned": False}).json()["pinned"] is False
        learning = client.get("/api/learning").json()
        assert len(learning["arms"]) == 60 and len(learning["exit_arms"]) == 3
        result = client.post("/api/sim/train", json={"episodes": 40}).json()
        assert result["episodes"] == 40
        assert client.put("/api/settings", json={"trading_mode": "live"}).status_code == 400
        chat = client.post("/api/chat", json={"message": "hi"})
        assert '"type": "error"' in chat.text  # no Claude key in this test


# -------------------------------------------------------------- live feeds
class FakeResponse:
    def __init__(self, payload, headers=None):
        self._payload, self.headers = payload, headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


ESPN = {"events": [{
    "id": "401", "date": "2026-11-19T00:00Z",
    "status": {"period": 4, "clock": 312.0, "displayClock": "5:12", "type": {"state": "in"}},
    "competitions": [{
        "competitors": [
            {"homeAway": "home", "score": "101", "team": {"abbreviation": "CLE", "displayName": "Cleveland Cavaliers", "location": "Cleveland", "color": "860038"}},
            {"homeAway": "away", "score": "96", "team": {"abbreviation": "GS", "displayName": "Golden State Warriors", "location": "Golden State", "color": "ffc72c"}},
        ],
        "odds": [{"overUnder": 231.5, "spread": -4.5}],
    }],
}]}
KALSHI = [{"event_ticker": "KXNBATOTAL-26NOV18GSWCLE", "title": "Golden State vs Cleveland: Total Points", "markets": [
    {"ticker": f"KXNBATOTAL-26NOV18GSWCLE-{s}", "floor_strike": s - 0.5, "yes_bid_dollars": f"{b / 100:.4f}",
     "yes_ask_dollars": f"{(b + 2) / 100:.4f}", "no_bid_dollars": f"{(98 - b) / 100:.4f}", "no_ask_dollars": f"{(100 - b) / 100:.4f}", "volume_fp": "10.00"}
    for s, b in ((228, 70), (232, 49), (236, 30), (240, 14), (244, 6))
]}]
ODDS = [{"home_team": "Cleveland Cavaliers", "away_team": "Golden State Warriors", "bookmakers": [{"key": "fanduel", "last_update": "2026-11-19T02:10:00Z", "markets": [
    {"key": "totals", "outcomes": [{"name": "Over", "price": -112, "point": 232.5}, {"name": "Under", "price": -108, "point": 232.5}]},
    {"key": "spreads", "outcomes": [{"name": "Cleveland Cavaliers", "price": -110, "point": -5.5}, {"name": "Golden State Warriors", "price": -110, "point": 5.5}]},
    {"key": "h2h", "outcomes": [{"name": "Cleveland Cavaliers", "price": -420}, {"name": "Golden State Warriors", "price": 320}]},
]}]}]


def test_live_feed_joins_espn_kalshi_and_fanduel():
    class FakeHttp:
        async def get(self, url, params=None):
            return FakeResponse(ODDS, {"x-requests-remaining": "480"}) if "odds-api" in url else FakeResponse(ESPN)

        async def aclose(self):
            return None

    class FakeKalshi(KalshiClient):
        async def nba_total_events(self):
            return KALSHI

    async def run():
        cfg = Config(_env_file=None, odds_api_key="k", kalshi_api_key_id="", kalshi_private_key_pem="", anthropic_api_key="")
        feed = LiveFeed(cfg, FakeKalshi())
        feed._http = FakeHttp()
        await feed.refresh()  # scores first, so the next pass knows the game is live
        feed._next = dict.fromkeys(feed._next, 0.0)
        return feed, await feed.refresh()

    feed, games = asyncio.run(run())
    assert all(s["ok"] for s in feed.status.values()), feed.status
    (game,) = games
    assert (game.away.abbr, game.home.abbr) == ("GSW", "CLE")  # ESPN's "GS" normalised to Kalshi's code
    assert game.state == "live" and game.period == 4 and game.total == 197 and round(game.minutes_left, 1) == 5.2
    assert game.event_ticker == "KXNBATOTAL-26NOV18GSWCLE" and [r.strike for r in game.ladder] == [227.5, 231.5, 235.5, 239.5, 243.5]
    assert game.ladder[3].no_ask == 86 and game.ladder[3].yes_ask == 16
    fd = game.fanduel
    assert (fd.source, fd.live, fd.total_line, fd.over_price, fd.under_price, fd.spread, fd.home_ml, fd.away_ml) == ("fanduel", True, 232.5, -112, -108, -5.5, -420, 320)
    assert game.pregame_total == 231.5
    assert implied_total(game.ladder) == 231.5  # the strike quoted 49-51


# -------------------------------------------------------------------- auth
def bare_config(**kw) -> Config:
    base = dict(kalshi_api_key_id="", kalshi_private_key_pem="", anthropic_api_key="", odds_api_key="", app_password="")
    return Config(_env_file=None, **{**base, **kw})


def test_password_gate_protects_api_and_socket(tmp_path, monkeypatch):
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.delenv("RENDER", raising=False)
    app = create_app(db_path=str(tmp_path / "a.db"), start_engine=False, cfg=bare_config(app_password="hunter2-not-real"))
    with TestClient(app) as client:
        assert client.get("/health").json()["ok"] is True
        assert client.get("/api/auth/status").json() == {"required": True, "locked": False, "authed": False}
        assert client.get("/api/auth/status").headers["cache-control"] == "no-store"
        assert client.get("/api/auth/nope").status_code == 404  # unknown API paths are never the HTML page
        assert client.get("/api/state").status_code == 401
        assert client.post("/api/orders", json={"ticker": "X", "side": "under", "contracts": 1, "price": 50}).status_code == 401
        assert client.put("/api/settings", json={"trading_mode": "live"}).status_code == 401
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws"):
                pass
        assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": "hunter2-not-real"}).status_code == 200
        assert client.get("/api/auth/status").json()["authed"] is True
        assert client.get("/api/state").status_code == 200
        with client.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "state"
        client.post("/api/auth/logout")
        assert client.get("/api/state").status_code == 401


def test_hosted_without_a_password_stays_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    app = create_app(db_path=str(tmp_path / "b.db"), start_engine=False, cfg=bare_config())
    with TestClient(app) as client:
        assert client.get("/api/auth/status").json() == {"required": False, "locked": True, "authed": False}
        assert client.get("/api/state").status_code == 503
        assert client.post("/api/auth/login", json={"password": ""}).status_code in (401, 422)
        assert client.post("/api/auth/login", json={"password": "anything"}).status_code == 401
        assert client.get("/api/state").status_code == 503


def test_repeated_wrong_passwords_are_throttled(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    app = create_app(db_path=str(tmp_path / "c.db"), start_engine=False, cfg=bare_config(app_password="hunter2-not-real"))
    with TestClient(app) as client:
        codes = [client.post("/api/auth/login", json={"password": f"guess{i}"}).status_code for i in range(10)]
        assert codes[:8] == [401] * 8 and codes[8:] == [429, 429]
        assert client.post("/api/auth/login", json={"password": "hunter2-not-real"}).status_code == 429
