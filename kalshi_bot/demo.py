"""Seed a local SQLite journal so the dashboard can be exercised offline."""

from __future__ import annotations

import time

from kalshi_bot.agents.orchestrator import handle_event
from kalshi_bot.config import Settings
from kalshi_bot.limits import ensure_default_limits
from kalshi_bot.replay import resolve_fixture, replay_fixture
from kalshi_bot.store import Store


def seed_demo(store: Store, settings: Settings | None = None) -> dict:
    settings = settings or Settings()
    now = int(time.time())
    store.set_paper(True)
    store.set_paused(False)
    store.set_pause_reason(None)
    ensure_default_limits(store)

    upcoming_id = "DEMO-EPL-ARSCHE"
    store.upsert_game(
        {
            "id": upcoming_id,
            "kalshi_event_ticker": upcoming_id,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "league": "premier_league",
            "league_tier": 1,
            "kickoff_ts": now + 5400,
            "status": "upcoming",
            "prematch": {
                "league_tier": 1,
                "home": {"gf_avg": 1.8, "ga_avg": 0.8, "over_25_rate": 0.4, "played": 5},
                "away": {"gf_avg": 1.2, "ga_avg": 1.1, "over_25_rate": 0.6, "played": 5},
                "combined_over_25_rate": 0.5,
            },
        }
    )
    store.upsert_market(
        {
            "ticker": "KXEPLTOTAL-DEMOARSCHE-25",
            "game_id": upcoming_id,
            "series_ticker": "KXEPLTOTAL",
            "strike": 2.5,
            "title": "Arsenal vs Chelsea Over 2.5",
            "no_bid": 61,
            "no_ask": 64,
            "rem": 2.5,
        }
    )
    store.upsert_market(
        {
            "ticker": "KXEPLTOTAL-DEMOARSCHE-35",
            "game_id": upcoming_id,
            "series_ticker": "KXEPLTOTAL",
            "strike": 3.5,
            "title": "Arsenal vs Chelsea Over 3.5",
            "no_bid": 78,
            "no_ask": 81,
            "rem": 3.5,
        }
    )

    live_id = "DEMO-LALIGA-RMAFCB"
    store.upsert_game(
        {
            "id": live_id,
            "kalshi_event_ticker": live_id,
            "home_team": "Real Madrid",
            "away_team": "Barcelona",
            "league": "la_liga",
            "league_tier": 1,
            "kickoff_ts": now - 3600,
            "status": "live",
            "home_goals": 1,
            "away_goals": 0,
            "minute": 72,
            "phase": "second_half",
            "prematch": {"league_tier": 1, "combined_over_25_rate": 0.7},
        }
    )
    store.upsert_market(
        {
            "ticker": "KXLALIGATOTAL-DEMORMAFCB-25",
            "game_id": live_id,
            "series_ticker": "KXLALIGATOTAL",
            "strike": 2.5,
            "title": "Real Madrid vs Barcelona Over 2.5",
            "no_bid": 84,
            "no_ask": 87,
            "rem": 1.5,
        }
    )
    store.upsert_market(
        {
            "ticker": "KXLALIGATOTAL-DEMORMAFCB-15",
            "game_id": live_id,
            "series_ticker": "KXLALIGATOTAL",
            "strike": 1.5,
            "title": "Real Madrid vs Barcelona Over 1.5",
            "no_bid": 22,
            "no_ask": 26,
            "rem": 0.5,
        }
    )
    if not store.events_for_game(live_id):
        store.add_event(
            live_id,
            "goal",
            23,
            {"home_goals": 1, "away_goals": 0, "prev_home": 0, "prev_away": 0},
        )
        store.add_event(live_id, "half_time", 45, {"phase": "half_time"})
        store.add_event(live_id, "second_half_start", 46, {"phase": "second_half"})
        store.add_llm_cost("pundit", "grok-4-1-fast", 1200, 400, 0.00044, live_id)
        store.add_llm_cost("kalshi", "grok-4-1-fast", 1600, 350, 0.000495, live_id)

    if not store.decisions_for_game(live_id):
        scan_id = store.add_event(live_id, "second_half_start", 72, {"phase": "second_half", "scan": True})
        live = store.get_game(live_id)
        handle_event(
            settings,
            store,
            None,
            live,
            {"id": scan_id, "event_type": "second_half_start", "minute": 72},
            {
                "event": {"id": scan_id, "event_type": "second_half_start", "minute": 72},
                "state": {
                    "home_goals": 1,
                    "away_goals": 0,
                    "minute": 72,
                    "phase": "second_half",
                    "total_goals": 1,
                },
                "markets": store.markets_for_game(live_id),
                "game": live,
            },
        )

    replay = replay_fixture(store, resolve_fixture(fixture_id="milan-lecce-2026-09-20"), settings)
    return {"replay_game_id": replay["game"]["id"], "replay_decisions": len(replay["decisions"])}
