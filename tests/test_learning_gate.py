from kalshi_bot.agents.orchestrator import handle_event
from kalshi_bot.config import Settings
from kalshi_bot.learning.brief import compile_brief, estimate_tokens
from kalshi_bot.learning.gate import apply_gate
from kalshi_bot.store import Store


def _board(store: Store, gid="GATE", minute=78, rem=1.5, ask=86, league="premier_league"):
    store.upsert_game(
        {
            "id": gid,
            "home_team": "A",
            "away_team": "B",
            "league": league,
            "league_tier": 1,
            "status": "live",
            "home_goals": 1,
            "away_goals": 0,
            "minute": minute,
            "phase": "second_half",
        }
    )
    store.upsert_market(
        {
            "ticker": "M-25",
            "game_id": gid,
            "strike": 2.5,
            "title": "Over 2.5",
            "no_bid": ask - 2,
            "no_ask": ask,
            "rem": rem,
        }
    )
    game = store.get_game(gid)
    payload = {
        "event": {"id": 1, "event_type": "goal", "minute": minute},
        "state": {
            "home_goals": 1,
            "away_goals": 0,
            "minute": minute,
            "phase": "second_half",
            "total_goals": 1,
        },
        "markets": store.markets_for_game(gid),
        "game": game,
    }
    return game, payload


def test_gate_skips_llm_outside_window(tmp_path):
    store = Store(str(tmp_path / "gate.sqlite"))
    game, payload = _board(store, minute=20, rem=2.5)
    result = apply_gate(store, game, payload["event"], payload, paper=True, day_start=0)
    assert result.skip_llm is True
    assert "minute" in result.reason
    decisions = store.decisions_for_game(game["id"])
    assert decisions
    assert all(row["action"] == "would-skip" for row in decisions)
    assert all(row["reason"].startswith("gate:") for row in decisions)
    store.close()


def test_gate_passes_open_entry(tmp_path):
    store = Store(str(tmp_path / "gate2.sqlite"))
    game, payload = _board(store, minute=78, rem=1.5, ask=86)
    result = apply_gate(store, game, payload["event"], payload, paper=True, day_start=0)
    assert result.skip_llm is False
    assert result.allowed
    store.close()


def test_handle_event_gated_does_not_call_agents(tmp_path):
    store = Store(str(tmp_path / "gate3.sqlite"))
    game, payload = _board(store, gid="EARLY", minute=12, rem=2.5)
    out = handle_event(
        Settings(),
        store,
        None,
        game,
        payload["event"],
        payload,
    )
    assert out["gated"] is True
    assert store.recent_decisions()
    store.close()


def test_brief_under_token_budget(tmp_path):
    store = Store(str(tmp_path / "brief.sqlite"))
    game, _ = _board(store, gid="BRIEF")
    brief = compile_brief(store, game, phase="kickoff")
    assert brief["token_estimate"] < 2000
    assert estimate_tokens(brief["text"]) < 2000
    assert "playbook_v=" in brief["text"]
    assert store.latest_brief(game["id"])["id"] == brief["id"]
    store.close()
