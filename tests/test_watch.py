"""The agent watching bets you placed yourself: it sells only when you switched it on and the bet
has clearly gone wrong, for a while, not on one bad quote."""

from __future__ import annotations

import asyncio

import pytest

from courtside.agent.engine import TradeError
from courtside.agent.policy import WATCH_CONFIRM_S, watch_signal
from courtside.soccer import model
from tests.test_core import make_engine
from tests.test_game_spreads import spread_game
from tests.test_soccer import a_match, make_desk, with_markets


def test_the_rule_sells_a_bet_gone_wrong_not_a_wobble():
    # Bought at 60c with a 60% chance.
    assert watch_signal(entry_price=60, p_entry=0.60, p_now=0.45, bid=44) is None  # a wobble
    reason, why = watch_signal(entry_price=60, p_entry=0.60, p_now=0.25, bid=24)
    assert reason == "risk_exit" and "25%" in why and "60%" in why
    # The price halved and the model agrees it is in trouble.
    assert watch_signal(entry_price=60, p_entry=0.60, p_now=0.42, bid=30)[0] == "stop_loss"
    # The price halved but the model still likes it: a thin book, not a bet gone wrong.
    assert watch_signal(entry_price=60, p_entry=0.60, p_now=0.58, bid=30) is None
    # The model has given up but the market still pays more than you paid: nothing to protect.
    assert watch_signal(entry_price=60, p_entry=0.60, p_now=0.20, bid=65) is None
    # Almost worthless already: selling saves nothing.
    assert watch_signal(entry_price=60, p_entry=0.60, p_now=0.02, bid=2) is None
    assert watch_signal(entry_price=60, p_entry=0.60, p_now=0.02, bid=None) is None


def nba_setup():
    engine = make_engine()
    asyncio.run(engine.update_settings({"agent_enabled": False}))  # watching your bets does not need the agent on
    game = spread_game(home=50, away=48, state="live", period=2, clock=300.0)
    for r in game.spreads:
        r.yes_bid, r.no_bid, r.p_under = 48, 50, 0.5
    engine.games, engine.by_id = [game], {game.id: game}
    return engine, game


def test_a_watched_nba_bet_is_sold_once_the_trouble_lasts():
    engine, game = nba_setup()
    rung, other = game.spreads[0], game.spreads[1]
    watched = asyncio.run(engine.manual_order(rung.ticker, "over", 10, 50, watch=True))
    plain = asyncio.run(engine.manual_order(other.ticker, "over", 10, 50))
    assert watched["watch"] is True and plain["watch"] is False
    assert "watching" in engine.db.one("SELECT reasoning FROM decisions ORDER BY id LIMIT 1")["reasoning"]

    # The game turns: both bets now look like losers.
    for r in (rung, other):
        r.yes_bid, r.p_under = 20, 0.82
    asyncio.run(engine._watch_user_bets())
    assert len(engine.positions_api()) == 2  # not on the first bad look

    engine._watch_seen[watched["id"]] -= WATCH_CONFIRM_S + 1  # it stayed bad
    asyncio.run(engine._watch_user_bets())
    left = engine.positions_api()
    assert [p["id"] for p in left] == [plain["id"]]  # the bet you did not ask it to watch is left alone
    trade = engine.trades_api()[0]
    assert trade["exit_reason"] == "risk_exit" and trade["exit_price"] == 20
    sold = engine.db.one("SELECT * FROM decisions WHERE kind='exit'")
    assert "Sold your" in sold["headline"] and "watch" in sold["reasoning"]


def test_recovery_resets_the_clock_and_the_switch_flips_both_ways():
    engine, game = nba_setup()
    rung = game.spreads[0]
    pos = asyncio.run(engine.manual_order(rung.ticker, "over", 10, 50))
    assert engine.set_watch(pos["id"], True)["watch"] is True

    rung.yes_bid, rung.p_under = 20, 0.82
    asyncio.run(engine._watch_user_bets())
    rung.yes_bid, rung.p_under = 47, 0.52  # it came back
    asyncio.run(engine._watch_user_bets())
    assert pos["id"] not in engine._watch_seen

    rung.yes_bid, rung.p_under = 20, 0.82
    asyncio.run(engine._watch_user_bets())
    engine._watch_seen[pos["id"]] -= WATCH_CONFIRM_S + 1
    assert engine.set_watch(pos["id"], False)["watch"] is False  # you switched it off in time
    asyncio.run(engine._watch_user_bets())
    assert len(engine.positions_api()) == 1


def test_only_your_own_open_bets_can_be_watched():
    engine, game = nba_setup()
    rung = game.spreads[0]
    pos = asyncio.run(engine.open_position(game, rung, "over", 5, 50, opened_by="agent"))
    with pytest.raises(TradeError, match="already manages"):
        engine.set_watch(pos["id"], True)
    with pytest.raises(TradeError, match="not open"):
        engine.set_watch(999, True)


def test_a_watched_soccer_bet_is_sold_when_the_match_turns():
    desk, _ = make_desk()
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    home = next(x for x in m.markets if x.kind == "winner" and x.outcome == "home")
    watched = asyncio.run(desk.order(home.ticker, "yes", 10, 47, watch=True))
    assert watched["watch"] is True

    # Mainz score twice; the market and the model both turn on Augsburg.
    m.state, m.period = "live", 2
    home.yes_bid, home.yes_ask, home.p_yes = 12, 13, 0.12
    asyncio.run(desk._watch_bets())
    assert desk.positions_api()
    desk._watch_seen[watched["id"]] -= WATCH_CONFIRM_S + 1
    asyncio.run(desk._watch_bets())
    assert desk.positions_api() == []
    trade = desk.trades_api()[0]
    assert trade["exit_reason"] == "risk_exit" and trade["exit_price"] == 12

    # The switch on a bet placed without it.
    other = asyncio.run(desk.order(home.ticker, "yes", 5, 13))
    assert other["watch"] is False and desk.set_watch(other["id"], True)["watch"] is True


# ----------------------------------------------------------------- Claude decides
from courtside.agent.watch import MIN_GAP_S, BetWatcher, checked  # noqa: E402


class FakeBrain:
    """Stands in for Claude: answers each look with the next verdict in line."""

    available = True

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)
        self.asked: list[tuple[str, dict, str]] = []

    async def review_watched(self, game_id, bet, why):
        self.asked.append((game_id, bet, why))
        return self.verdicts.pop(0) if self.verdicts else None


def verdict(action, chance, concern="medium", reason="Because."):
    return {"action": action, "win_chance": chance, "concern": concern, "reason": reason}


async def look(owner, tick):
    """One watch pass, then wait for any look it started."""
    await tick()
    for st in list(owner.watcher.states.values()):
        if st.task is not None:
            await st.task


def test_when_the_agent_looks_again():
    w = BetWatcher()
    assert "First look" in w.why_now(1, p_now=0.6, signature="Q2, risk low", alarm=False, now=0.0)
    st = w.states[1]
    st.reviewed_at, st.p_at_review, st.signature = 0.0, 0.6, "Q2, risk low"
    w.record(1, verdict("hold", 0.6, "low"), "t")
    assert w.why_now(1, p_now=0.1, signature="Q4, risk high", alarm=True, now=MIN_GAP_S - 1) is None  # too soon
    assert "Alarm" in w.why_now(1, p_now=0.6, signature="Q2, risk low", alarm=True, now=MIN_GAP_S)
    assert "game changed" in w.why_now(1, p_now=0.6, signature="Q3, risk low", alarm=False, now=MIN_GAP_S)
    assert "slid from 60% to 48%" in w.why_now(1, p_now=0.48, signature="Q2, risk low", alarm=False, now=MIN_GAP_S)
    assert w.why_now(1, p_now=0.58, signature="Q2, risk low", alarm=False, now=MIN_GAP_S) is None  # calm and rated low
    assert w.why_now(1, p_now=0.58, signature="Q2, risk low", alarm=False, now=421) == "Routine check."


def test_a_sell_its_own_numbers_argue_against_is_held():
    assert checked(verdict("sell", 0.30), bid=25)["action"] == "sell"
    held = checked(verdict("sell", 0.55), bid=25)
    assert held["action"] == "hold" and held["concern"] == "high" and "55%" in held["reason"]


def test_claude_holds_through_an_alarm_and_sells_when_it_judges_the_bet_gone():
    engine, game = nba_setup()
    engine.brain = FakeBrain(
        verdict("hold", 0.55, "low", "Lakers just went cold but the pace is fine."),
        verdict("hold", 0.40, "high", "A 9-0 run, but their best scorer sat with four fouls and is coming back."),
        verdict("sell", 0.15, "high", "The run reached 18-2 and the starters are out for good."),
    )
    rung = game.spreads[0]
    pos = asyncio.run(engine.manual_order(rung.ticker, "over", 10, 50, watch=True))

    async def run():
        await look(engine, engine._watch_user_bets)  # first look
        note = engine.positions_api()[0]["watch_note"]
        assert note["action"] == "hold" and "went cold" in note["reason"]

        rung.yes_bid, rung.p_under = 20, 0.82  # the rule's alarm fires...
        for st in list(engine.watcher.states.values()):
            st.reviewed_at -= MIN_GAP_S
        await look(engine, engine._watch_user_bets)
        engine._watch_seen.clear()
        for _ in range(3):
            await look(engine, engine._watch_user_bets)
        assert engine.positions_api(), "...but Claude said hold, and the rule does not overrule it"
        assert engine.db.one("SELECT * FROM decisions WHERE kind='hold'")["source"] == "claude"

        for st in list(engine.watcher.states.values()):
            st.reviewed_at -= MIN_GAP_S
        await look(engine, engine._watch_user_bets)

    asyncio.run(run())
    assert engine.positions_api() == []
    whys = [why for _, _, why in engine.brain.asked]
    assert whys[0] == "First look: the owner just asked you to watch this bet." and whys[1].startswith("Alarm")
    bet = engine.brain.asked[0][1]
    assert bet["sell_now"]["bid_cents"] == 48 and bet["paid_cents"] == pos["entry_price"] and "win the game by more than" in bet["wins_if"]
    sold = engine.db.one("SELECT * FROM decisions WHERE kind='exit'")
    assert sold["source"] == "claude" and "18-2" in sold["reasoning"]


def test_with_no_answer_from_claude_the_fixed_rule_covers_the_bet():
    engine, game = nba_setup()
    engine.brain = FakeBrain()  # never answers
    rung = game.spreads[0]
    asyncio.run(engine.manual_order(rung.ticker, "over", 10, 50, watch=True))
    rung.yes_bid, rung.p_under = 20, 0.82

    async def run():
        await look(engine, engine._watch_user_bets)
        assert engine.watcher.failed(engine.positions_api()[0]["id"])
        await look(engine, engine._watch_user_bets)  # the rule picks it up...
        for k in engine._watch_seen:
            engine._watch_seen[k] -= WATCH_CONFIRM_S + 1  # ...and the trouble lasts
        await look(engine, engine._watch_user_bets)

    asyncio.run(run())
    assert engine.positions_api() == [] and engine.trades_api()[0]["exit_reason"] == "risk_exit"


def test_practice_games_use_the_rule_not_claude():
    engine, game = nba_setup()
    game.simulated = True
    engine.brain = FakeBrain(verdict("sell", 0.1))
    asyncio.run(engine.manual_order(game.spreads[0].ticker, "over", 10, 50, watch=True))
    asyncio.run(look(engine, engine._watch_user_bets))
    assert engine.brain.asked == [] and engine.positions_api()


def test_claude_sells_a_watched_soccer_bet_when_the_match_turns():
    desk, engine = make_desk()
    engine.brain = FakeBrain(verdict("hold", 0.5, "medium", "Even game."), verdict("sell", 0.1, "high", "Mainz scored twice and Augsburg are down to ten."))
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    home = next(x for x in m.markets if x.kind == "winner" and x.outcome == "home")
    pos = asyncio.run(desk.order(home.ticker, "yes", 10, 47, watch=True))
    m.state, m.period = "live", 1

    async def run():
        await look(desk, desk._watch_bets)
        assert desk.positions_api()[0]["watch_note"]["reason"] == "Even game."
        m.away.score, m.home.red_cards = 2, 1
        home.yes_bid, home.yes_ask, home.p_yes = 12, 13, 0.12
        for st in desk.watcher.states.values():
            st.reviewed_at -= MIN_GAP_S
        await look(desk, desk._watch_bets)

    asyncio.run(run())
    assert desk.positions_api() == []
    assert "game changed" in engine.brain.asked[1][2] and "0-2" in engine.brain.asked[1][2]
    assert engine.brain.asked[0][1]["paid_cents"] == pos["entry_price"]
    assert desk.trades_api()[0]["exit_reason"] == "risk_exit"
