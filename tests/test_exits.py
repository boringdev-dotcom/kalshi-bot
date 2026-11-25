"""The agent's early sales: it only sells when buyers pay more than the bet is worth held to the
end, and its selling styles are judged on what selling did against holding."""

from __future__ import annotations

from courtside.agent.learner import Learner
from courtside.agent.playbook import Q4_UNDER, Playbook
from courtside.agent.policy import exit_signal, worth_selling
from courtside.db import DB
from tests.test_core import q4_game, quote


def turned_game():
    """A one-possession game that has run hot: an under bought at 94c is in trouble."""
    game = q4_game(total=226, clock=150, margin=3)
    quote(game)
    return game, next(r for r in game.ladder if r.strike == 241.5)


def signal_for(game, rung, entry=94, profile="balanced"):
    p = Playbook(DB(":memory:")).params(Q4_UNDER)
    return exit_signal(side="under", strike=241.5, entry_price=entry, game=game, rung=rung, p=p, profile=profile)


def test_a_sale_has_to_beat_what_the_bet_is_worth():
    assert not worth_selling(82, 0.90)  # selling a 90% bet for 82c gives money away
    assert not worth_selling(80, 0.79)  # about what it is worth: fees and spread make it a loss
    assert worth_selling(88, 0.80)


def test_a_warning_alone_does_not_sell_at_a_fair_price():
    game, rung = turned_game()
    signal = signal_for(game, rung)
    assert signal is not None and signal.reason in ("risk_exit", "stop_loss")
    assert signal.hold and "Holding" in signal.headline and signal.data["worth"] == f"{round(rung.p_under * 100)}c"


def test_it_sells_when_buyers_pay_more_than_the_bet_is_worth():
    game, rung = turned_game()
    rung.no_bid = min(99, round(rung.p_under * 100) + 6)
    signal = signal_for(game, rung)
    assert signal is not None and not signal.hold and signal.price == rung.no_bid


def test_a_price_drop_the_model_does_not_believe_is_ridden_out():
    game = q4_game(total=200, clock=300, margin=12)
    quote(game)
    rung = next(r for r in game.ladder if r.strike == 241.5)
    assert rung.p_under > 0.9
    rung.no_bid = 80  # 14c under a 94c entry, past the stop, while the model still says over 90%
    signal = signal_for(game, rung, profile="tight")
    assert signal is not None and signal.reason == "stop_loss" and signal.hold


def test_styles_whose_sales_give_up_winners_get_used_less():
    learner = Learner(DB(":memory:"), seed=3)
    for _ in range(30):
        learner.grade_exit("tight", -0.15, simulated=False)  # sold eventual winners for less
        learner.grade_exit("patient", 0.0, simulated=False)  # held to the end
    picks = [learner.choose_exit_profile() for _ in range(300)]
    assert picks.count("tight") < 15
    arms = {a["key"]: a for a in learner.exit_arms()}
    assert arms["tight"]["n"] == 30 and arms["tight"]["mean_return"] == -0.15 and arms["balanced"]["n"] == 0


def test_past_trades_are_graded_once():
    db = DB(":memory:")
    learner = Learner(db, seed=1)
    rows = [
        {"exit_profile": "tight", "pnl": 20.0, "counterfactual_pnl": 30.0, "cost": 100.0, "simulated": 0},  # gave up $10
        {"exit_profile": "tight", "pnl": -10.0, "counterfactual_pnl": -100.0, "cost": 100.0, "simulated": 0},  # saved $90
        {"exit_profile": "patient", "pnl": 6.0, "counterfactual_pnl": 6.0, "cost": 94.0, "simulated": 1},
    ]
    assert learner.rebuild_exit_grades(rows) == 3
    assert learner.rebuild_exit_grades(rows) == 0
    arms = {a["key"]: a for a in learner.exit_arms()}
    assert arms["tight"]["n"] == 2 and abs(arms["tight"]["mean_return"] - 0.4) < 1e-9
    assert arms["patient"]["n"] == 0  # practice stays out of the real-markets record


def test_the_agent_keeps_a_bet_buyers_underpay_for_and_says_why():
    import asyncio

    from tests.test_core import make_engine

    engine = make_engine()
    asyncio.run(engine.update_settings({"agent_enabled": False}))
    game = q4_game(total=200, clock=300, margin=12)
    quote(game)
    engine.games, engine.by_id = [game], {game.id: game}
    rung = next(r for r in game.ladder if r.strike == 241.5)
    pos = asyncio.run(engine.open_position(game, rung, "under", 50, rung.no_ask, opened_by="agent", exit_profile="tight"))
    rung.no_bid = 80
    asyncio.run(engine._manage_exits())
    asyncio.run(engine._manage_exits())  # said once, not every tick
    assert [p["id"] for p in engine.positions_api()] == [pos["id"]]
    holds = [d for d in engine.db.query("SELECT * FROM decisions") if d["kind"] == "hold"]
    assert len(holds) == 1 and "pays less than it is worth" in holds[0]["headline"]

    rung.p_under = 0.70  # the model turns too, and 80c is now more than the bet is worth: it sells
    asyncio.run(engine._manage_exits())
    assert engine.positions_api() == []
