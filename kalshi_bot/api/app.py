"""FastAPI read API + WebSocket event stream and trading controls."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from kalshi_bot.agents.orchestrator import day_start_ts
from kalshi_bot.config import Settings
from kalshi_bot.learning.mine import run_nightly
from kalshi_bot.learning.playbook_version import HARD_CAP_KEYS, ensure_playbook_v1, version_payload
from kalshi_bot.learning.proposals import (
    HardCapError,
    approve_proposal,
    reject_proposal,
    shadow_proposal,
)
from kalshi_bot.limits import (
    cap_usage,
    enforce_loss_cap,
    ensure_default_limits,
    get_limits,
    session_pnl,
    set_limits,
)
from kalshi_bot.playbook import PLAYBOOK_NOTES
from kalshi_bot.replay import list_fixtures, replay_fixture, resolve_fixture
from kalshi_bot.store import Store
from kalshi_bot.watcher.discovery import infer_league, infer_teams


class WatchBody(BaseModel):
    home_team: str
    away_team: str
    kickoff_ts: Optional[int] = None
    league: Optional[str] = None
    tickers: list[str] = []
    fotmob_id: Optional[str] = None
    espn_id: Optional[str] = None
    event_ticker: Optional[str] = None


class LimitsBody(BaseModel):
    max_contracts_per_match: Optional[int] = None
    max_contracts_per_day: Optional[int] = None
    max_daily_loss_cents: Optional[int] = None


class ReplayBody(BaseModel):
    fixture_id: Optional[str] = None
    ticker: Optional[str] = None
    date: Optional[str] = None
    path: Optional[str] = None


def _snapshot(store: Store, game_id: Optional[str] = None) -> dict[str, Any]:
    start = day_start_ts()
    loss = enforce_loss_cap(store, start)
    limits = get_limits(store)
    usage = cap_usage(store, game_id or "", start) if game_id else {
        "per_match": limits["max_contracts_per_match"],
        "per_day": limits["max_contracts_per_day"],
        "used_match": 0,
        "used_today": sum(
            o["count"] for o in store.orders_today(start) if o["action"] == "buy_no"
        ),
        "remaining_match": limits["max_contracts_per_match"],
        "remaining_day": limits["max_contracts_per_day"]
        - sum(o["count"] for o in store.orders_today(start) if o["action"] == "buy_no"),
        "max_daily_loss_cents": limits["max_daily_loss_cents"],
    }
    return {
        "paper": store.is_paper(),
        "paused": store.is_paused(),
        "pause_reason": store.pause_reason(),
        "limits": limits,
        "caps": usage,
        "pnl": loss,
    }


def create_app(settings: Optional[Settings] = None, store: Optional[Store] = None) -> FastAPI:
    settings = settings or Settings()
    store = store or Store(settings.sqlite_path)
    if store.get_control("paper_mode") is None:
        store.set_paper(settings.paper_mode)
    if store.get_control("trading_paused") is None:
        store.set_paused(settings.trading_paused)
    ensure_default_limits(store)
    ensure_playbook_v1(store)

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
        snap = _snapshot(store)
        return {
            **snap,
            "paper_only": True,
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
        start = day_start_ts()
        snap = _snapshot(store)
        games = store.live_games()
        for game in games:
            game["verdicts"] = store.latest_verdicts(game["id"])
            game["positions"] = store.positions_for_game(game["id"])
            game["decisions"] = store.decisions_for_game(game["id"])
            game["caps"] = cap_usage(store, game["id"], start)
        return {"games": games, **snap}

    @app.get("/api/games/{game_id}")
    def game_detail(game_id: str) -> dict[str, Any]:
        game = store.get_game(game_id)
        if not game:
            raise HTTPException(404, "game not found")
        start = day_start_ts()
        orders = store.orders_for_game(game_id)
        return {
            "game": game,
            "events": store.events_for_game(game_id),
            "verdicts": store.verdicts_for_game(game_id),
            "decisions": store.decisions_for_game(game_id),
            "orders": orders,
            "positions": store.positions_for_game(game_id),
            "costs": store.costs(game_id=game_id),
            "pnl": session_pnl(store, start),
            "caps": cap_usage(store, game_id, start),
            "paper": store.is_paper(),
            "reflection": store.reflection_for_game(game_id),
            "brief": store.latest_brief(game_id),
        }

    @app.get("/api/portfolio")
    def portfolio() -> dict[str, Any]:
        start = day_start_ts()
        snap = _snapshot(store)
        return {
            **snap,
            "positions": store.open_positions(),
            "orders_today": store.orders_today(start),
            "decisions": store.recent_decisions(40),
            "daily_pnl": snap["pnl"],
        }

    @app.get("/api/decisions")
    def decisions(game_id: Optional[str] = None) -> dict[str, Any]:
        rows = store.decisions_for_game(game_id) if game_id else store.recent_decisions(80)
        return {"decisions": rows, "paper": store.is_paper()}

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
        store.set_pause_reason("manual")
        return {"paused": True, "pause_reason": "manual"}

    @app.post("/api/control/resume")
    def resume() -> dict[str, Any]:
        store.set_paused(False)
        store.set_pause_reason(None)
        snap = _snapshot(store)
        return {"paused": snap["paused"], "pause_reason": snap["pause_reason"], "pnl": snap["pnl"]}

    @app.post("/api/control/paper")
    def paper_on() -> dict[str, Any]:
        store.set_paper(True)
        return {"paper": True}

    @app.post("/api/control/live")
    def paper_off() -> dict[str, Any]:
        store.set_paper(False)
        return {"paper": False, "warning": "Live mode sends real Kalshi orders."}

    @app.post("/api/control/limits")
    def limits_update(payload: LimitsBody) -> dict[str, Any]:
        set_limits(
            store,
            max_contracts_per_match=payload.max_contracts_per_match,
            max_contracts_per_day=payload.max_contracts_per_day,
            max_daily_loss_cents=payload.max_daily_loss_cents,
        )
        return _snapshot(store)

    @app.get("/api/replay/fixtures")
    def replay_fixtures() -> dict[str, Any]:
        return {"fixtures": list_fixtures(), "runs": store.replay_games()}

    @app.post("/api/replay")
    def replay_run(payload: ReplayBody) -> dict[str, Any]:
        store.set_paper(True)
        try:
            fixture = resolve_fixture(
                fixture_id=payload.fixture_id,
                ticker=payload.ticker,
                date=payload.date,
                path=payload.path,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        result = replay_fixture(store, fixture, settings)
        return result

    @app.get("/api/learning")
    def learning() -> dict[str, Any]:
        versions = version_payload(store)
        return {
            "lessons": store.list_lessons(),
            "calibration": store.list_calibration(),
            "proposals": store.list_proposals(),
            "playbook": versions,
            "hard_cap_keys": sorted(HARD_CAP_KEYS),
            "propose_only": True,
        }

    @app.post("/api/learning/mine")
    def learning_mine() -> dict[str, Any]:
        return run_nightly(store)

    @app.post("/api/learning/proposals/{proposal_id}/approve")
    def learning_approve(proposal_id: int) -> dict[str, Any]:
        try:
            return approve_proposal(store, proposal_id)
        except HardCapError as exc:
            raise HTTPException(400, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/learning/proposals/{proposal_id}/reject")
    def learning_reject(proposal_id: int) -> dict[str, Any]:
        try:
            return {"proposal": reject_proposal(store, proposal_id)}
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/learning/proposals/{proposal_id}/shadow")
    def learning_shadow(proposal_id: int) -> dict[str, Any]:
        try:
            return {"proposal": shadow_proposal(store, proposal_id)}
        except HardCapError as exc:
            raise HTTPException(400, str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/api/games/watch")
    def watch(payload: WatchBody) -> dict[str, Any]:
        gid = payload.event_ticker
        if not gid:
            slug = f"{payload.home_team}-{payload.away_team}".upper().replace(" ", "")[:28]
            gid = f"MANUAL-{slug}-{int(time.time())}"
        store.upsert_game(
            {
                "id": gid,
                "kalshi_event_ticker": payload.event_ticker or gid,
                "home_team": payload.home_team,
                "away_team": payload.away_team,
                "league": payload.league or infer_league({"ticker": payload.tickers[0] if payload.tickers else ""}),
                "kickoff_ts": payload.kickoff_ts or int(time.time()) + 3600,
                "status": "upcoming",
                "fotmob_id": payload.fotmob_id,
                "espn_id": payload.espn_id,
            }
        )
        for ticker in payload.tickers:
            home, away = infer_teams({"title": f"{payload.home_team} vs {payload.away_team}", "ticker": ticker})
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


app = create_app()
