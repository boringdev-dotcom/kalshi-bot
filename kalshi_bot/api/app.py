"""FastAPI read API + WebSocket event stream and trading controls."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from kalshi_bot.agents.orchestrator import day_start_ts
from kalshi_bot.config import Settings
from kalshi_bot.playbook import MAX_CONTRACTS_PER_DAY, MAX_CONTRACTS_PER_MATCH, PLAYBOOK_NOTES
from kalshi_bot.store import Store
from kalshi_bot.watcher.discovery import game_id_for, infer_league, infer_teams


def create_app(settings: Optional[Settings] = None, store: Optional[Store] = None) -> FastAPI:
    settings = settings or Settings()
    store = store or Store(settings.sqlite_path)
    if store.get_control("paper_mode") is None:
        store.set_paper(settings.paper_mode)
    if store.get_control("trading_paused") is None:
        store.set_paused(settings.trading_paused)

    app = FastAPI(title="Kalshi Soccer Bot", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.store = store

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "paper": store.is_paper(), "paused": store.is_paused()}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {
            "paper": store.is_paper(),
            "paused": store.is_paused(),
            "kalshi_env": settings.kalshi_env,
            "model": settings.xai_model,
            "xai_configured": bool(settings.xai_api_key),
            "telegram": settings.use_telegram,
            "live_games": len(store.live_games()),
            "open_positions": len(store.open_positions()),
            "playbook": PLAYBOOK_NOTES,
        }

    @app.get("/api/games/upcoming")
    def upcoming() -> dict[str, Any]:
        return {"games": store.upcoming_games(horizon_hours=settings.watch_horizon_hours)}

    @app.get("/api/games/live")
    def live() -> dict[str, Any]:
        games = store.live_games()
        for game in games:
            game["verdicts"] = store.latest_verdicts(game["id"])
            game["positions"] = store.positions_for_game(game["id"])
        return {"games": games}

    @app.get("/api/games/{game_id}")
    def game_detail(game_id: str) -> dict[str, Any]:
        game = store.get_game(game_id)
        if not game:
            raise HTTPException(404, "game not found")
        orders = store.orders_for_game(game_id)
        pnl = _paper_pnl(game, orders, store.positions_for_game(game_id))
        return {
            "game": game,
            "events": store.events_for_game(game_id),
            "verdicts": store.verdicts_for_game(game_id),
            "orders": orders,
            "positions": store.positions_for_game(game_id),
            "costs": store.costs(game_id=game_id),
            "pnl": pnl,
        }

    @app.get("/api/portfolio")
    def portfolio() -> dict[str, Any]:
        start = day_start_ts()
        orders = store.orders_today(start)
        positions = store.open_positions()
        used_day = sum(o["count"] for o in orders if o["action"] == "buy_no")
        realized = 0.0
        for order in orders:
            if order["action"] == "flatten":
                # paper mark: flatten vs entry is unknown without paired lots; report notional
                realized += 0
        return {
            "paper": store.is_paper(),
            "positions": positions,
            "orders_today": orders,
            "daily_pnl": _daily_pnl(store),
            "caps": {
                "per_match": MAX_CONTRACTS_PER_MATCH,
                "per_day": MAX_CONTRACTS_PER_DAY,
                "used_today": used_day,
            },
        }

    @app.get("/api/costs")
    def costs() -> dict[str, Any]:
        start = day_start_ts()
        return {
            "today": store.cost_summary(since_ts=start),
            "all": store.cost_summary(),
        }

    @app.post("/api/control/pause")
    def pause() -> dict[str, Any]:
        store.set_paused(True)
        return {"paused": True}

    @app.post("/api/control/resume")
    def resume() -> dict[str, Any]:
        store.set_paused(False)
        return {"paused": False}

    @app.post("/api/control/paper")
    def paper_on() -> dict[str, Any]:
        store.set_paper(True)
        return {"paper": True}

    @app.post("/api/control/live")
    def paper_off() -> dict[str, Any]:
        store.set_paper(False)
        return {"paper": False}

    class WatchBody(BaseModel):
        home_team: str
        away_team: str
        kickoff_ts: Optional[int] = None
        league: Optional[str] = None
        tickers: list[str] = []
        fotmob_id: Optional[str] = None
        espn_id: Optional[str] = None
        event_ticker: Optional[str] = None

    @app.post("/api/games/watch")
    def watch(body: WatchBody) -> dict[str, Any]:
        gid = body.event_ticker or game_id_for(
            {"event_ticker": body.event_ticker, "ticker": (body.tickers[0] if body.tickers else ""), "title": f"{body.home_team} vs {body.away_team}"}
        )
        if not gid:
            gid = f"manual-{int(time.time())}"
        store.upsert_game(
            {
                "id": gid,
                "kalshi_event_ticker": body.event_ticker or gid,
                "home_team": body.home_team,
                "away_team": body.away_team,
                "league": body.league or infer_league({"ticker": body.tickers[0] if body.tickers else ""}),
                "kickoff_ts": body.kickoff_ts or int(time.time()) + 3600,
                "status": "upcoming",
                "fotmob_id": body.fotmob_id,
                "espn_id": body.espn_id,
            }
        )
        for ticker in body.tickers:
            home, away = infer_teams({"title": f"{body.home_team} vs {body.away_team}", "ticker": ticker})
            store.upsert_market({"ticker": ticker, "game_id": gid, "title": f"{home} vs {away}"})
        return {"game": store.get_game(gid)}

    @app.websocket("/ws/events")
    async def ws_events(ws: WebSocket) -> None:
        await ws.accept()
        last_id = store.latest_event_id()
        try:
            while True:
                rows = store.events_since(last_id)
                for row in rows:
                    last_id = row["id"]
                    game = store.get_game(row["game_id"])
                    await ws.send_json({"type": "event", "event": row, "game": game})
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    return app


def _paper_pnl(game: dict, orders: list[dict], positions: list[dict]) -> dict[str, Any]:
    open_notional = 0
    for pos in positions:
        if pos["count"] and pos.get("avg_price"):
            open_notional += pos["count"] * pos["avg_price"]
    return {
        "open_contracts": sum(p["count"] for p in positions),
        "open_notional_cents": open_notional,
        "order_count": len(orders),
        "score": f"{game.get('home_goals', 0)}-{game.get('away_goals', 0)}",
    }


def _daily_pnl(store: Store) -> dict[str, Any]:
    start = day_start_ts()
    orders = store.orders_today(start)
    buy = sum(o["count"] * (o.get("price") or 0) for o in orders if o["action"] == "buy_no")
    flatten = sum(o["count"] for o in orders if o["action"] == "flatten")
    return {
        "buy_no_notional_cents": buy,
        "flatten_contracts": flatten,
        "note": "Mark-to-market P&L is approximate until settlement import.",
    }


app = create_app()
