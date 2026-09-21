from kalshi_bot.decisions import WOULD_PLACE, WOULD_SKIP, record_decision
from kalshi_bot.learning.journal import (
    ERROR,
    LUCK,
    SKILL,
    UNLUCKY,
    attach_outcomes,
    grade_decision,
    grade_game,
    process_grade,
    snapshot_features,
)
from kalshi_bot.store import Store


def _game(store: Store, gid="G1", goals=1, league="premier_league"):
    store.upsert_game(
        {
            "id": gid,
            "home_team": "Home",
            "away_team": "Away",
            "league": league,
            "league_tier": 1,
            "status": "finished",
            "home_goals": goals,
            "away_goals": 0,
            "minute": 90,
            "phase": "full_time",
        }
    )
    store.upsert_market(
        {
            "ticker": "T-25",
            "game_id": gid,
            "strike": 2.5,
            "title": "Over 2.5",
            "no_bid": 84,
            "no_ask": 86,
        }
    )
    return store.get_game(gid)


def test_snapshot_and_process_grades():
    feats = snapshot_features(
        {"league": "premier_league", "league_tier": 1, "home_goals": 1, "away_goals": 0},
        {"strike": 2.5, "rem": 1.5, "no_ask": 86, "no_bid": 84, "ticker": "T"},
        {"minute": 78, "phase": "second_half", "home_goals": 1, "away_goals": 0},
    )
    assert feats["league"] == "premier_league"
    assert feats["minute"] == 78
    assert feats["rem"] == 1.5
    assert process_grade(placed=True, should_place=True, won=True) == SKILL
    assert process_grade(placed=True, should_place=True, won=False) == UNLUCKY
    assert process_grade(placed=True, should_place=False, won=True) == LUCK
    assert process_grade(placed=True, should_place=False, won=False) == ERROR
    assert process_grade(placed=False, should_place=True, won=True) == ERROR
    assert process_grade(placed=False, should_place=True, won=False) == LUCK
    assert process_grade(placed=False, should_place=False, won=False) == SKILL


def test_counterfactual_and_skill_vs_luck(tmp_path):
    store = Store(str(tmp_path / "journal.sqlite"))
    game = _game(store, goals=1)
    good = snapshot_features(
        game,
        {"ticker": "T-25", "strike": 2.5, "rem": 1.5, "no_ask": 86, "no_bid": 84},
        {"minute": 78, "phase": "second_half", "home_goals": 1, "away_goals": 0},
    )
    early = snapshot_features(
        game,
        {"ticker": "T-25", "strike": 2.5, "rem": 1.5, "no_ask": 86, "no_bid": 84},
        {"minute": 20, "phase": "first_half", "home_goals": 0, "away_goals": 0},
    )
    record_decision(
        store,
        game_id=game["id"],
        action=WOULD_PLACE,
        reason="in window",
        market_ticker="T-25",
        size=10,
        price=86,
        rem=1.5,
        features=good,
    )
    record_decision(
        store,
        game_id=game["id"],
        action=WOULD_SKIP,
        reason="too early",
        market_ticker="T-25",
        size=10,
        price=86,
        rem=1.5,
        features=early,
    )
    store.add_event(game["id"], "goal", 23, {"home_goals": 1})
    graded = grade_game(store, game["id"])
    by_action = {row["action"]: row for row in graded}
    placed = by_action[WOULD_PLACE]
    skipped = by_action[WOULD_SKIP]
    assert placed["settled"] == 1
    assert placed["outcome"] == "won"
    assert placed["realized_pnl_cents"] == (100 - 86) * 10
    assert placed["process_grade"] == SKILL
    assert skipped["realized_pnl_cents"] == 0
    assert skipped["counterfactual_pnl_cents"] == (100 - 86) * 10
    assert skipped["process_grade"] == UNLUCKY
    assert skipped["goals_after"] >= 1
    store.close()


def test_unlucky_place_and_error_skip(tmp_path):
    store = Store(str(tmp_path / "journal2.sqlite"))
    game = _game(store, gid="G2", goals=3)
    good = snapshot_features(
        game,
        {"ticker": "T-25", "strike": 2.5, "rem": 1.5, "no_ask": 86, "no_bid": 84},
        {"minute": 78, "phase": "second_half", "home_goals": 1, "away_goals": 0},
    )
    record_decision(
        store,
        game_id="G2",
        action=WOULD_PLACE,
        reason="in window",
        market_ticker="T-25",
        size=5,
        price=86,
        rem=1.5,
        features=good,
    )
    record_decision(
        store,
        game_id="G2",
        action=WOULD_SKIP,
        reason="hesitated",
        market_ticker="T-25",
        size=5,
        price=86,
        rem=1.5,
        features=good,
    )
    rows = attach_outcomes(store, "G2")
    grades = {row["action"]: grade_decision(row, game) for row in rows}
    assert grades[WOULD_PLACE] == UNLUCKY
    assert grades[WOULD_SKIP] == LUCK
    store.close()
