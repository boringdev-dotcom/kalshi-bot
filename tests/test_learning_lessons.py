from kalshi_bot.decisions import WOULD_PLACE, record_decision
from kalshi_bot.learning.journal import grade_game, snapshot_features
from kalshi_bot.learning.lessons import add_hypothesis, matches_condition, validate_lessons
from kalshi_bot.store import Store


def test_condition_match_and_hypothesis(tmp_path):
    store = Store(str(tmp_path / "lessons.sqlite"))
    lid = add_hypothesis(
        store,
        condition="league=serie_a;minute>=70",
        observation="late unders hold",
        suggested_action="prefer entries after 70",
        evidence_game="G1",
        league="serie_a",
    )
    again = add_hypothesis(
        store,
        condition="league=serie_a;minute>=70",
        observation="late unders hold",
        suggested_action="prefer entries after 70",
        evidence_game="G2",
        league="serie_a",
    )
    assert lid == again
    lesson = store.get_lesson(lid)
    assert lesson["status"] == "hypothesis"
    assert lesson["confidence"] == 0
    assert lesson["support_count"] == 2
    assert matches_condition("league=serie_a;minute>=70", {"league": "serie_a", "minute": 80})
    assert not matches_condition("league=serie_a;minute>=70", {"league": "serie_a", "minute": 40})
    store.close()


def test_validate_promotes_with_support(tmp_path):
    store = Store(str(tmp_path / "lessons2.sqlite"))
    add_hypothesis(
        store,
        condition="league=premier_league;minute>=70",
        observation="window works",
        suggested_action="keep late entries",
        league="premier_league",
    )
    for i in range(4):
        gid = f"P{i}"
        store.upsert_game(
            {
                "id": gid,
                "home_team": "H",
                "away_team": "A",
                "league": "premier_league",
                "league_tier": 1,
                "status": "finished",
                "home_goals": 1,
                "away_goals": 0,
                "minute": 90,
                "phase": "full_time",
            }
        )
        feats = snapshot_features(
            store.get_game(gid),
            {"ticker": "T", "strike": 2.5, "rem": 1.5, "no_ask": 86, "no_bid": 84},
            {"minute": 80, "phase": "second_half", "home_goals": 1, "away_goals": 0},
        )
        record_decision(
            store,
            game_id=gid,
            action=WOULD_PLACE,
            reason="late",
            market_ticker="T",
            size=10,
            price=86,
            rem=1.5,
            features=feats,
            agent="kalshi",
        )
        grade_game(store, gid)
    rows = validate_lessons(store)
    assert rows
    assert rows[0]["status"] == "active"
    assert rows[0]["confidence"] > 0
    store.close()
