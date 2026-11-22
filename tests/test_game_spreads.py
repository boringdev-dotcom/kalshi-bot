"""Full-game spreads (Kalshi's KXNBASPREAD): loading, pricing, trading and settling."""

from __future__ import annotations

import asyncio
import random

from courtside.domain import FanDuelOdds, Game, Rung, Team, rung_dict
from courtside.feeds.sim import SimGame
from courtside.model.quarters import project_game_margin
from courtside.model.totals import refresh_game
from tests.test_core import make_engine


def spread_game(home=0, away=0, state="pre", period=0, clock=720.0, book_spread=None) -> Game:
    g = Game(id="g1", home=Team("SAC", "Sacramento", "5a2d81"), away=Team("BOS", "Boston", "007a33"))
    g.state, g.period, g.clock_seconds = state, period, clock
    g.home.score, g.away.score = home, away
    if book_spread is not None:
        g.fanduel = FanDuelOdds(spread=book_spread)
    g.spreads = [
        Rung(ticker=f"KXNBASPREAD-X-{t}{int(s + 0.5)}", strike=s, kind="spread", team=t, other_team=o, yes_ask=50, no_ask=52)
        for t, o in (("BOS", "SAC"), ("SAC", "BOS"))
        for s in (2.5, 6.5, 10.5)
    ]
    return g


def test_pregame_margin_follows_the_sportsbook_spread():
    g = spread_game(book_spread=-6.5)  # Sacramento (home) favoured by 6.5
    proj = project_game_margin(g)
    assert proj["margin_mean"] == 6.5 and 13 < proj["margin_sd"] < 15.5
    refresh_game(g)
    by = {(r.team, r.strike): r for r in g.spreads}
    # Home favoured by 6.5: SAC -6.5 is a coin flip, SAC -2.5 likely, BOS -2.5 unlikely.
    assert abs(by[("SAC", 6.5)].p_under - 0.5) < 0.01
    assert by[("SAC", 2.5)].p_under < 0.5 < by[("BOS", 2.5)].p_under
    assert g.margin_projection == proj


def test_late_lead_tightens_the_margin_and_final_settles_it():
    g = spread_game(home=110, away=99, state="live", period=4, clock=60.0)
    refresh_game(g)
    by = {(r.team, r.strike): r for r in g.spreads}
    assert 1 - by[("SAC", 6.5)].p_under > 0.95  # up 11 with a minute left
    assert 1 - by[("SAC", 10.5)].p_under > 0.5
    assert by[("BOS", 2.5)].p_under > 0.99

    g.state = "final"
    refresh_game(g)
    assert g.margin_projection is None
    assert g.settle_value("game", "spread", "SAC") == 11 and g.settle_value("game", "spread", "BOS") == -11
    assert by[("SAC", 10.5)].p_under == 0.0 and by[("BOS", 2.5)].p_under == 1.0


def test_spreads_ride_with_the_game_detail_not_every_tick():
    g = spread_game()
    assert "spreads" not in g.to_dict()
    r = rung_dict(g.spreads[0])
    assert (r["segment"], r["kind"], r["yes_label"], r["no_label"]) == ("game", "spread", "BOS -2.5", "SAC +2.5")
    assert g.rung(g.spreads[0].ticker) is g.spreads[0]


def test_a_full_game_spread_by_hand_trades_and_settles_at_the_final():
    async def run():
        engine = make_engine()
        await engine.update_settings({"agent_enabled": False})
        sim = SimGame(random.Random(5))
        sim.fast_forward(2, 400.0)
        sim.quote()
        game = sim.game
        engine.games, engine.by_id = [game], {game.id: game}
        refresh_game(game)
        assert game.spreads and all(r.segment == "game" and r.kind == "spread" for r in game.spreads)
        rung = next(r for r in game.spreads if r.yes_ask and 25 <= r.yes_ask <= 75)
        pos = await engine.manual_order(rung.ticker, "over", 10, rung.yes_ask)
        assert (pos["segment"], pos["kind"], pos["label"]) == ("game", "spread", f"{rung.team} -{rung.strike:g}")
        while game.state != "final":
            sim.advance(30.0)
            sim.quote()
            refresh_game(game)
        await engine._settle_finished()
        return engine, game, rung

    engine, game, rung = asyncio.run(run())
    assert engine.open_rows() == []
    row = engine.db.one("SELECT * FROM positions WHERE status='closed'")
    margin = game.settle_value("game", "spread", rung.team)
    assert row["final_total"] == margin
    assert (row["exit_reason"] == "settled_win") == (margin > rung.strike)
    # A spread is not a full-game total: it stays out of the totals calibration.
    assert engine.learning_state()["calibration"] == []
    assert "full_game" in engine.memory.list(kind="episode")[0]["tags"]
