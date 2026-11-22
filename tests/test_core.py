"""Behavioural tests for the model, rules, learner, memory, engine and API."""

from __future__ import annotations

import asyncio
import random

import pytest
from fastapi.testclient import TestClient

from courtside.agent.brain import Brain
from courtside.agent.engine import Engine, TradeError
from courtside.agent.learner import Learner
from courtside.agent.memory import MemoryStore
from courtside.agent.observer import QuarterObserver
from courtside.agent.playbook import Q4_UNDER, Playbook
from courtside.agent.policy import arm_key, exit_signal, find_entries, kalshi_fee, size_order, Skip
from courtside.agent.trainer import train
from courtside.api.app import create_app
from courtside.config import Config
from courtside.db import DB
from courtside.domain import FanDuelOdds, Game, Rung, Team
from courtside.events import Hub
from courtside.kalshi.client import cents, side_and_price
from courtside.model.quarters import implied_margin, project_quarter
from courtside.feeds.live import EASTERN, LiveFeed, slate_day
from courtside.feeds.patterns import Snapshot, PlayerLine, build_context, parse_espn
from courtside.feeds.sim import SimGame
from courtside.kalshi.client import KalshiClient, quarter_series
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
    assert find_entries(q4_game(clock=100), p) is None  # inside the last 2:30: too late to open


def test_entry_window_opens_the_moment_q3_ends():
    p = Playbook(DB(":memory:")).params(Q4_UNDER)
    assert p["max_minutes_left"] == 12

    def at(period: int, clock: float) -> Game:
        game = q4_game(total=172, clock=clock, margin=12)
        game.period = period
        refresh_game(game)
        quote(game, discount=0.03)
        return game

    mid_third = at(3, 45.0)
    assert not mid_third.in_fourth and find_entries(mid_third, p) is None

    horn = at(3, 0.0)  # ESPN reports the break as period 3, clock 0
    assert horn.at_q3_end and horn.in_fourth and horn.minutes_left == 12 and horn.q4_clock == "12:00"
    assert find_entries(horn, p) is not None

    tip = at(4, 720.0)
    found = find_entries(tip, {**p, "min_price": 70})  # a 10-14 pt cushion is cheaper this early
    assert isinstance(found, list) and found and found[0].context["minutes_left"] == 12
    assert found[0].arm.split("|")[1] == "9-12"


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


def test_quarter_charts_follow_each_quarter():
    async def run() -> Engine:
        engine = make_engine()
        await engine.update_settings({"sim_speed": 30})
        for _ in range(60):
            engine._last_real -= 1.0
            await engine.tick()
        return engine

    random.seed(3)
    engine = asyncio.run(run())
    for game in engine.games:
        books = engine.quarter_timelines.get(game.id, {})
        for view in game.quarter_view:
            points = books.get(view["segment"], [])
            if view["status"] == "upcoming":
                assert not points
                continue
            ts = [p["t"] for p in points]
            assert ts == sorted(ts) and all(0 <= t <= 720 for t in ts)
            if view["status"] == "final" and points:
                last = points[-1]
                assert last["t"] == 720 and last["projected"] == last["total"] and last["m_projected"] == last["margin"]
    assert any(p["m_line"] is not None for g in engine.quarter_timelines.values() for pts in g.values() for p in pts)


def test_implied_margin_reads_both_teams_rungs():
    def rung(team, strike, mid):
        return Rung(ticker=f"{team}{strike}", strike=strike, team=team, yes_bid=mid - 1, yes_ask=mid + 1)

    # Home (CLE) 55% to win by 3.5+, 45% by 5.5+; away (MEM) 30% to win by 1.5+.
    rungs = [rung("CLE", 3.5, 55), rung("CLE", 5.5, 45), rung("MEM", 1.5, 30)]
    assert implied_margin(rungs, "CLE") == 4.5
    # Away favoured: MEM 60% to win by 1.5+, 40% by 3.5+, so the 50/50 margin is MEM by 2.5.
    rungs = [rung("MEM", 1.5, 60), rung("MEM", 3.5, 40), rung("CLE", 1.5, 20)]
    assert implied_margin(rungs, "CLE") == -2.5


# ----------------------------------------------------------------- floor patterns
def _espn_summary() -> dict:
    """A tiny ESPN game summary: two teams, starters, a substitution, fouls and baskets."""
    def athlete(pid, name, starter, pf="0"):
        return {"athlete": {"id": pid, "displayName": name}, "starter": starter, "didNotPlay": False,
                "stats": ["20", "10", "4-6", "1-2", "1-2", "3", "2", "1", "0", "0", "1", "2", pf, "+4"]}

    names = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]
    home = [athlete(f"h{i}", f"Home Player{i}", i < 5, pf="5" if i == 0 else "1") for i in range(7)]
    away = [athlete(f"a{i}", f"Away Player{i}", i < 5) for i in range(7)]

    def play(kind, period, clock, team, parts=(), score=0, text=""):
        return {"type": {"text": kind}, "period": {"number": period}, "clock": {"displayValue": clock}, "team": {"id": team},
                "participants": [{"athlete": {"id": p}} for p in parts], "scoringPlay": score > 0, "scoreValue": score, "text": text}

    plays = [play("Substitution", 4, "11:00", "1", ("h5", "h1"))]
    plays += [play("Personal Foul", 4, f"{10 - i}:00", "2", ("a1",)) for i in range(4)]  # four away fouls
    plays += [play("Offensive Foul", 4, "5:30", "1", ("h2",))]  # does not count toward the limit
    plays += [play("Jump Shot", 4, f"{11 - i // 2}:{30 if i % 2 == 0 else 0:02d}", "1", ("h3",), score=2) for i in range(6)]
    return {
        "boxscore": {
            "teams": [{"team": {"id": "1", "abbreviation": "CLE"}}, {"team": {"id": "2", "abbreviation": "NY"}}],
            "players": [
                {"team": {"abbreviation": "CLE"}, "statistics": [{"names": names, "athletes": home}]},
                {"team": {"abbreviation": "NY"}, "statistics": [{"names": names, "athletes": away}]},
            ],
        },
        "plays": plays,
        "injuries": [{"team": {"abbreviation": "NY"}, "injuries": [{"athlete": {"displayName": "Hurt Guy"}, "status": "Out"}]}],
    }


def test_espn_patterns_track_the_floor_fouls_and_runs():
    snap = parse_espn(_espn_summary(), {"NY": "NYK"})
    on = {p.id for p in snap.players if p.on_court}
    assert on == {"h0", "h2", "h3", "h4", "h5", "a0", "a1", "a2", "a3", "a4"}  # h1 subbed out for h5
    assert [f[0] for f in snap.fouls] == ["NYK"] * 4  # the offensive foul is not a team foul
    assert snap.out == [("NYK", "Hurt Guy")]
    assert len(snap.plays) == 12 and snap.plays[0]["team"] == "CLE" and snap.plays[0]["clock"] == "11:00"
    assert sum(p["points"] for p in snap.plays) == 12

    game = Game(id="g", home=Team("CLE", "Cavaliers", 90), away=Team("NYK", "Knicks", 80),
                state="live", period=4, clock_seconds=480.0, clock="8:00")
    ctx = build_context(game, snap)
    keys = [n["key"] for n in ctx["notes"]]
    assert keys[0] == "bonus_early"  # NYK has four fouls with 8:00 left: CLE shoots on the next one
    bonus = ctx["notes"][0]
    assert bonus["team"] == "CLE" and bonus["lean"] == "up" and "8:00 left in Q4" in bonus["text"]
    assert "foul_trouble" in keys and "run" in keys  # Player0 has 5 fouls; CLE scored 12 unanswered
    nyk = next(t for t in ctx["teams"] if t["abbr"] == "NYK")
    assert nyk["fouls"] == 4 and nyk["penalty"]


def test_last_two_minutes_bonus_rule():
    players = [PlayerLine(id=f"{t}{i}", name=f"P {t}{i}", team=t, starter=True, on_court=True) for t in ("CLE", "NYK") for i in range(5)]
    game = Game(id="g", home=Team("CLE", "Cavaliers", 100), away=Team("NYK", "Knicks", 98),
                state="live", period=4, clock_seconds=90.0, clock="1:30")
    # Two fouls before the last two minutes, one inside them: the next foul is free throws.
    snap = Snapshot(players=players, fouls=[("NYK", 4, 400.0), ("NYK", 4, 300.0), ("NYK", 4, 110.0)])
    assert next(t for t in build_context(game, snap)["teams"] if t["abbr"] == "NYK")["penalty"]
    snap = Snapshot(players=players, fouls=[("NYK", 4, 400.0), ("NYK", 4, 300.0)])
    assert not next(t for t in build_context(game, snap)["teams"] if t["abbr"] == "NYK")["penalty"]


def test_trades_save_the_floor_patterns_for_learning():
    async def run() -> Engine:
        engine = make_engine()
        engine._last_real -= 1.0
        await engine.tick()
        game, rung = next(
            (g, r) for g in engine.games if g.state == "live" for r in g.ladder if r.no_ask and r.no_bid and r.no_ask <= 95
        )
        game.context = {"notes": [
            {"key": "bonus_early", "text": "CLE is in the bonus with 8:00 left in Q4.", "lean": "up", "team": "CLE", "weight": 3},
            {"key": "run", "text": "CLE is on a 12-0 run over the last 3:30.", "lean": None, "team": "CLE", "weight": 2},
        ]}
        pos = await engine.manual_order(rung.ticker, "under", 5, rung.no_ask)
        await engine.close_position(pos["id"])
        return engine

    engine = asyncio.run(run())
    row = engine.db.one("SELECT * FROM positions WHERE opened_by='user'")
    assert row["context"]["patterns"] == ["bonus_early", "run"] and len(row["context"]["on_floor"]) == 2
    record = engine.learning_state()["patterns"]
    assert record[0]["key"] == "all" and record[0]["trades"] == 1 and record[0]["yours"] == 1
    assert {r["key"] for r in record[1:]} == set(row["context"]["patterns"])
    episode = engine.memory.list(kind="episode")[0]
    assert any(t.startswith("pattern:") for t in episode["tags"]) and "On the floor:" in episode["text"]


def test_game_briefing_carries_everything_for_an_analysis():
    import json

    engine = make_engine()
    engine._last_real -= 1.0
    asyncio.run(engine.tick())
    brain = Brain(engine.cfg, engine)
    game = next(g for g in engine.games if g.state == "live")
    brief = json.loads(json.dumps(brain.game_briefing(game), default=str))
    for key in ("score", "projection", "on_the_floor", "team_fouls_this_period", "players", "quarters",
                "full_game_ladder_near_line", "my_positions_here", "record_by_pattern", "recalled_memories"):
        assert key in brief
    assert brief["players"] and sum(p["on_court"] for p in brief["players"]) == 10
    assert len(brief["quarters"]) == 4

    async def ask() -> list[dict]:
        return [ev async for ev in brain.chat("Your read?", game_id=game.id, analysis=True)]

    events = asyncio.run(ask())  # no Claude key in tests: a clear error, nothing stored
    assert events[0]["type"] == "error" and not brain.history()

    # With Claude connected, the briefing and the analysis ask go to the model; the transcript keeps only the words.
    sent: list = []

    class Block:
        type, text = "text", "Heading under the line."

    class Final:
        stop_reason, content = "end_turn", [Block()]

    class Stream:
        def __init__(self, **kw):
            sent.append(kw["messages"][-1]["content"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def __aiter__(self):
            async def gen():
                delta = type("D", (), {"type": "text_delta", "text": "Heading under the line."})()
                yield type("E", (), {"type": "content_block_delta", "delta": delta})()
            return gen()

        async def get_final_message(self):
            return Final()

    class Messages:
        def stream(self, **kw):
            return Stream(**kw)

    class Client:
        beta = type("B", (), {"messages": Messages()})()

    brain.client = Client()
    brain.cfg.anthropic_api_key = "test"
    events = asyncio.run(ask())
    assert events[-1]["type"] == "done"
    assert f"[game briefing: {game.label}]" in sent[0] and "Agent analysis" in sent[0] and sent[0].endswith("Your read?")
    assert game.plays and f"[play-by-play: {game.label}, all {len(game.plays)} plays" in sent[0]
    assert "Q1 " in sent[0] and " makes " in sent[0]  # every play from the tip, not only the latest
    assert [m["text"] for m in brain.history()] == ["Your read?", "Heading under the line."]


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
        assert [m["segment"] for m in detail["quarter_markets"]] == ["q1", "q2", "q3", "q4"]
        assert len(detail["quarter_markets"][0]["totals"]) == 13 and len(detail["quarter_markets"][0]["spreads"]) == 13
        assert {"yes_label", "no_label", "segment", "kind", "team"} <= set(detail["quarter_markets"][3]["spreads"][0])
        assert len(live["quarters"]) == 4 and "quarter_markets" not in live and len(live["home"]["quarters"]) >= 1

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
        assert {"observations", "settled", "games", "cells", "your_trades"} <= set(learning["quarters"])
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
            {"homeAway": "home", "score": "101", "linescores": [{"value": 30.0}, {"value": 24.0}, {"value": 29.0}, {"value": 17.0}],
             "team": {"abbreviation": "CLE", "displayName": "Cleveland Cavaliers", "location": "Cleveland", "color": "860038"}},
            {"homeAway": "away", "score": "96", "linescores": [{"value": 27.0}, {"value": 31.0}, {"value": 22.0}],
             "team": {"abbreviation": "GS", "displayName": "Golden State Warriors", "location": "Golden State", "color": "ffc72c"}},
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
        async def events(self, series_ticker):
            if series_ticker == "KXNBATOTAL":
                return KALSHI
            quote = {"yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4300", "no_bid_dollars": "0.5700", "no_ask_dollars": "0.6000", "volume_fp": "1.00"}
            event = f"{series_ticker}-26NOV18GSWCLE"
            if series_ticker.endswith("TOTAL"):
                markets = [{"ticker": f"{event}-{s}", "floor_strike": s - 0.5, "yes_sub_title": f"Over {s - 0.5} points", **quote} for s in (52, 54, 56)]
            else:
                markets = [
                    {"ticker": f"{event}-CLE4", "floor_strike": 3.5, "yes_sub_title": "Cleveland wins by over 3.5 points", **quote},
                    {"ticker": f"{event}-GSW2", "floor_strike": 1.5, "yes_sub_title": "Golden State wins by over 1.5 points", **quote},
                    {"ticker": f"{event}-XYZ9", "floor_strike": 8.5, "yes_sub_title": "Somebody wins by over 8.5 points", **quote},
                ]
            return [{"event_ticker": event, "title": "Golden State vs Cleveland", "markets": markets}]

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

    # Quarter by quarter: finished periods from the linescore, the live one from the score.
    assert game.home.quarters == [30, 24, 29, 18] and game.away.quarters == [27, 31, 22, 16]
    assert sum(game.home.quarters) == 101 and sum(game.away.quarters) == 96
    assert quarter_series(3, "spread") == "KXNBA3QSPREAD"
    assert set(game.quarter_markets) == {"q1", "q2", "q3", "q4"}
    q1 = game.quarter_markets["q1"]
    assert [r.strike for r in q1["total"]] == [51.5, 53.5, 55.5] and all(r.segment == "q1" and r.kind == "total" for r in q1["total"])
    spreads = {r.team: r for r in q1["spread"]}
    assert set(spreads) == {"CLE", "GSW"}  # the rung naming neither team is dropped, not guessed at
    assert (spreads["CLE"].label("over"), spreads["CLE"].label("under")) == ("CLE -3.5", "GSW +3.5")
    assert spreads["GSW"].position_label("under") == "Q1 CLE +1.5"
    # Full-game spreads come from their own series and belong to the whole game.
    assert {r.team for r in game.spreads} == {"CLE", "GSW"} and all(r.segment == "game" and r.kind == "spread" for r in game.spreads)
    assert game.spreads[0].ticker.startswith("KXNBASPREAD-") and game.spreads[0].position_label("over") == "GSW -1.5"
    refresh_game(game)
    assert [v["status"] for v in game.quarter_view] == ["final", "final", "final", "live"]
    assert game.settle_value("q1", "total", None) == 57 and game.settle_value("q1", "spread", "CLE") == 3
    assert game.settle_value("q2", "spread", "GSW") == 7 and game.settle_value("q4", "total", None) is None
    # Q1 finished 57 with CLE +3: every Q1 market is now a certainty one way or the other.
    assert [r.p_under for r in q1["total"]] == [0.0, 0.0, 0.0] and spreads["CLE"].p_under == 1.0


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


# ---------------------------------------------------------- quarter markets
def test_quarter_model_tracks_the_clock_and_the_score():
    game = q4_game(total=0, clock=720.0, margin=0)
    game.state, game.period = "pre", 0
    game.home.score = game.away.score = 0
    before = [project_quarter(game, q) for q in (1, 2, 3, 4)]
    assert all(52 < p["total_mean"] < 62 and 9 < p["total_sd"] < 10.5 for p in before)
    assert before[0]["total_mean"] > before[3]["total_mean"] - 3  # first quarters run at least as hot as fourths

    game.state, game.period, game.clock_seconds, game.clock = "live", 2, 180.0, "3:00"
    game.home.quarters, game.away.quarters = [30, 22], [26, 20]
    game.home.score, game.away.score = 52, 46
    live = project_quarter(game, 2)
    assert project_quarter(game, 1) is None  # finished
    assert 42 + 10 < live["total_mean"] < 42 + 20 and live["total_sd"] < 6  # 42 scored, three minutes of scoring to come
    assert 1.5 < live["margin_mean"] < 3.5  # home leads the quarter 22-20 and is the better side
    assert game.quarter_points(2) == (22, 20) and game.quarter_seconds_left(3) == 720


def test_a_quarter_trade_by_hand_settles_when_the_quarter_ends():
    async def run():
        engine = make_engine()
        await engine.update_settings({"agent_enabled": False})
        sim = SimGame(random.Random(11))
        sim.fast_forward(2, 500.0)
        sim.quote()
        engine.games, engine.by_id = [sim.game], {sim.game.id: sim.game}
        refresh_game(sim.game)
        game = sim.game

        total = next(r for r in game.quarter_markets["q2"]["total"] if r.no_ask and r.yes_ask and 25 <= r.no_ask <= 75)
        spread = next(r for r in game.quarter_markets["q2"]["spread"] if r.no_ask and r.yes_ask and 25 <= r.yes_ask <= 75)
        under = await engine.manual_order(total.ticker, "under", 20, total.no_ask)
        cover = await engine.manual_order(spread.ticker, "over", 20, spread.yes_ask)
        assert (under["segment"], under["kind"], under["label"]) == ("q2", "total", f"Q2 Under {total.strike:g}")
        assert (cover["kind"], cover["team"], cover["label"]) == ("spread", spread.team, f"Q2 {spread.team} -{spread.strike:g}")

        settled_q1 = game.quarter_markets["q1"]["total"][0]
        with pytest.raises(TradeError, match="already settled"):
            await engine.open_position(game, settled_q1, "under", 5, 50, opened_by="user")

        sim.fast_forward(3, 700.0)  # Q2 is over
        sim.quote()
        refresh_game(game)
        await engine._settle_finished()
        return engine, game, total, spread

    engine, game, total, spread = asyncio.run(run())
    assert engine.open_rows() == []
    rows = {r["kind"]: r for r in engine.db.query("SELECT * FROM positions WHERE status='closed'")}
    home, away = game.quarter_points(2)
    assert rows["total"]["final_total"] == home + away
    assert (rows["total"]["exit_reason"] == "settled_win") == (home + away < total.strike)
    margin = home - away if spread.team == game.home.abbr else away - home
    assert rows["spread"]["final_total"] == margin
    assert (rows["spread"]["exit_reason"] == "settled_win") == (margin > spread.strike)
    assert rows["total"]["pnl"] == pytest.approx((20 if rows["total"]["exit_reason"] == "settled_win" else 0) - rows["total"]["cost"], abs=0.01)
    # The agent keeps a record of your quarter trades, and they never feed its own Q4 learner.
    episodes = engine.memory.list(kind="episode")
    assert len(episodes) == 2 and all({"quarter", "q2", "manual"} <= set(e["tags"]) for e in episodes)
    assert "your trade" in episodes[0]["text"] and "left in Q2" in episodes[0]["text"]
    assert sum(a["n"] + a["sim_n"] for a in engine.learner.arms()) == 0
    mine = engine.learning_state()["quarters"]["your_trades"]
    assert {(t["segment"], t["kind"], t["n"]) for t in mine} == {("q2", "total", 1), ("q2", "spread", 1)}


def test_shadow_book_records_quarter_prices_and_scores_them():
    db = DB(":memory:")
    observer = QuarterObserver(db)
    rng = random.Random(21)
    for _ in range(12):
        sim = SimGame(rng)
        game = sim.game
        sim.tip_in = 0.0
        while game.state != "final":
            sim.advance(20.0)
            sim.quote()
            refresh_game(game)
            observer.observe([game])
    book = observer.summary(simulated=True)
    assert book["games"] == 12 and book["observations"] > 1000 and book["settled"] == book["observations"]
    assert observer.summary(simulated=False)["observations"] == 0  # the sandbox never leaks into the real book
    assert {c["segment"] for c in book["cells"]} == {"q1", "q2", "q3", "q4"}
    assert {c["kind"] for c in book["cells"]} == {"total", "spread"} and {c["checkpoint"] for c in book["cells"]} == {"open", "mid"}
    # Dearer contracts win more often, and by mid-quarter the prices are worth trusting.
    favs = [c for c in book["cells"] if c["bucket"] == "80-97" and c["n"] >= 30]
    dogs = [c for c in book["cells"] if c["bucket"] == "3-20" and c["n"] >= 30]
    assert favs and dogs
    assert min(c["win_rate"] for c in favs) > max(c["win_rate"] for c in dogs)
    assert all(abs(c["win_rate"] - c["price"] / 100) < 0.2 for c in favs + dogs)
    # Nothing is recorded twice for the same market and moment.
    assert db.one("SELECT COUNT(*) n FROM (SELECT ticker, checkpoint FROM observations GROUP BY 1, 2 HAVING COUNT(*) > 1)")["n"] == 0


def test_an_existing_database_gains_the_quarter_columns(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE positions (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL DEFAULT 'open', game_id TEXT NOT NULL, "
        "game_label TEXT NOT NULL, ticker TEXT NOT NULL, strike REAL NOT NULL, side TEXT NOT NULL, contracts INTEGER NOT NULL, "
        "entry_price INTEGER NOT NULL, cost REAL NOT NULL, fees REAL NOT NULL DEFAULT 0, opened_at TEXT NOT NULL, opened_by TEXT NOT NULL, "
        "mode TEXT NOT NULL, simulated INTEGER NOT NULL DEFAULT 0, training INTEGER NOT NULL DEFAULT 0, strategy_id TEXT, exit_profile TEXT, "
        "arm_key TEXT, p_win_entry REAL NOT NULL DEFAULT 0, context TEXT NOT NULL DEFAULT '{}', memory_ids TEXT NOT NULL DEFAULT '[]', "
        "exit_price INTEGER, closed_at TEXT, pnl REAL, exit_reason TEXT, counterfactual_pnl REAL, exit_verdict TEXT, final_total INTEGER)"
    )
    old.execute(
        "INSERT INTO positions(game_id, game_label, ticker, strike, side, contracts, entry_price, cost, opened_at, opened_by, mode) "
        "VALUES('g', 'MEM @ CLE', 'T251', 250.5, 'under', 319, 94, 299.9, '2026-11-18T00:00:00+00:00', 'agent', 'paper')"
    )
    old.commit()
    old.close()
    row = DB(path).one("SELECT * FROM positions")
    assert (row["segment"], row["kind"], row["team"], row["label"]) == ("game", "total", None, None)
    assert Engine._label(row) == "Under 250.5" and Engine.trade_api({**row, "exit_price": 100, "pnl": 19.1, "closed_at": "x", "exit_reason": "settled_win", "counterfactual_pnl": 19.1, "exit_verdict": None, "final_total": 240})["label"] == "Under 250.5"


def test_slate_day_rolls_over_at_six_eastern():
    from datetime import datetime, timezone

    def at(y, m, d, h, mi=0):
        return datetime(y, m, d, h, mi, tzinfo=EASTERN)

    assert slate_day(at(2026, 11, 19, 1, 30)) == "20261118"  # late West Coast game still on last night's board
    assert slate_day(at(2026, 11, 19, 5, 59)) == "20261118"
    assert slate_day(at(2026, 11, 19, 6, 0)) == "20261119"
    assert slate_day(at(2026, 11, 19, 10, 12)) == "20261119"  # ESPN's default was still on the 18th here
    assert slate_day(at(2026, 11, 19, 23, 50)) == "20261119"
    assert slate_day(datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc)) == "20261119"  # 10 PM ET


def test_finished_games_are_archived_with_every_play():
    from courtside.feeds.patterns import play_lines

    engine = make_engine()
    brain = Brain(engine.cfg, engine)
    snap = parse_espn(_espn_summary(), {"NY": "NYK"})
    game = Game(id="nba-1", home=Team("CLE", "Cavaliers", 112, quarters=[30, 28, 26, 28]),
                away=Team("NYK", "Knicks", 104, quarters=[25, 27, 30, 22]), state="final", period=4,
                clock_seconds=0.0, clock="0:00", pregame_total=221.5)
    game.context = build_context(game, snap)
    game.plays = snap.plays
    engine.games, engine.by_id = [game], {game.id: game}

    engine._archive_finished()  # not yet: the last play-by-play after the final has not been read
    assert engine.db.query("SELECT * FROM game_archive") == []

    game.context["final"] = True
    engine._archive_finished()
    engine._archive_finished()  # once only
    rows = engine.db.query("SELECT * FROM game_archive")
    assert len(rows) == 1 and rows[0]["label"] == "NYK @ CLE" and rows[0]["home_score"] == 112
    assert rows[0]["plays"] == snap.plays and rows[0]["by_quarter"]["CLE"] == [30, 28, 26, 28]
    assert {p["name"] for p in rows[0]["context"]["players"]} >= {"Home Player0", "Away Player0"}

    # Once it has left the board, the agent can still read every play.
    engine.games, engine.by_id = [], {}
    summary, out = asyncio.run(brain._t_get_plays("CLE"))
    assert out["plays"] == play_lines(snap.plays) and out["source"].startswith("archive")
    assert "read 12 plays" in summary
    summary, out = asyncio.run(brain._t_get_plays("NYK @ CLE", quarter=4))
    assert out["plays"].startswith("Q4 11:00 CLE")

    # Practice games are not kept.
    game.simulated, game.id = True, "sim-1"
    engine.games = [game]
    engine._archive_finished()
    assert len(engine.db.query("SELECT * FROM game_archive")) == 1


def test_feed_errors_never_show_the_odds_api_key():
    from courtside.feeds.live import redact

    text = "Client error '401 Unauthorized' for url 'https://api.the-odds-api.com/v4/x?apiKey=abc123secret&regions=us'"
    assert "abc123secret" not in redact(text) and "apiKey=REDACTED&regions=us" in redact(text)
