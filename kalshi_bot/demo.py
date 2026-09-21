"""Seed a local SQLite journal so the dashboard can be exercised offline."""

from __future__ import annotations

import time

from kalshi_bot.store import Store


def seed_demo(store: Store) -> None:
    now = int(time.time())
    store.set_paper(True)
    store.set_paused(False)

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
            "last_verdict": "watch",
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
            "last_verdict": "pass",
        }
    )
    event_id = store.add_event(
        live_id,
        "goal",
        23,
        {"home_goals": 1, "away_goals": 0, "prev_home": 0, "prev_away": 0},
    )
    store.add_event(live_id, "half_time", 45, {"phase": "half_time"})
    store.add_event(live_id, "second_half_start", 46, {"phase": "second_half"})
    store.add_verdict(live_id, "pundit", event_id, "KXLALIGATOTAL-DEMORMAFCB-25", "watch", 0, "Still 1.5 rem at 72'", {})
    store.add_verdict(live_id, "kalshi", event_id, "KXLALIGATOTAL-DEMORMAFCB-25", "hold", 0, "Playbook: rem > 1.0", {})
    store.set_memory(live_id, "pundit", "Quiet second half after early goal. Watch 2.5 No if rem drops.")
    store.set_memory(live_id, "kalshi", "No entry yet. Waiting for rem <= 1.0 after minute 70.")
    if not store.find_order(f"{live_id}:KXLALIGATOTAL-DEMORMAFCB-25:0:buy_no"):
        store.add_order(
            {
                "idempotency_key": f"{live_id}:KXLALIGATOTAL-DEMORMAFCB-25:0:buy_no",
                "game_id": live_id,
                "market_ticker": "KXLALIGATOTAL-DEMORMAFCB-25",
                "event_id": event_id,
                "side": "no",
                "action": "buy_no",
                "count": 2,
                "price": 88,
                "paper": True,
                "status": "paper",
                "reason": "demo seed",
            }
        )
    store.upsert_position(
        {
            "market_ticker": "KXLALIGATOTAL-DEMORMAFCB-25",
            "game_id": live_id,
            "side": "no",
            "count": 2,
            "avg_price": 88,
            "paper": True,
            "stopped": False,
        }
    )
    store.add_llm_cost("pundit", "grok-4-1-fast", 1200, 400, 0.00044, live_id)
    store.add_llm_cost("kalshi", "grok-4-1-fast", 1600, 350, 0.000495, live_id)
