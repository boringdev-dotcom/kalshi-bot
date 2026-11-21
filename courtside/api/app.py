"""HTTP + WebSocket API. Shapes are documented in docs/API.md."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..agent.brain import Brain
from .auth import COOKIE, Auth
from ..agent.engine import Engine, TradeError
from ..agent.playbook import STRATEGIES
from ..agent.trainer import train
from ..config import Config, get_config
from ..db import DB
from ..domain import SEGMENTS, rung_dict
from ..events import Hub
from ..soccer.desk import SoccerDesk, SoccerTradeError

log = logging.getLogger(__name__)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SettingsPatch(BaseModel):
    trading_mode: Optional[str] = Field(None, pattern="^(paper|live)$")
    data_source: Optional[str] = Field(None, pattern="^(sim|live)$")
    agent_enabled: Optional[bool] = None
    max_stake_per_trade: Optional[float] = Field(None, ge=1, le=100000)
    max_open_positions: Optional[int] = Field(None, ge=1, le=50)
    max_daily_loss: Optional[float] = Field(None, ge=1, le=100000)
    max_total_exposure: Optional[float] = Field(None, ge=1, le=1000000)
    claude_review: Optional[bool] = None
    sim_speed: Optional[float] = Field(None, ge=1, le=60)


class OrderBody(BaseModel):
    ticker: str
    side: str = Field(pattern="^(under|over)$")
    contracts: int = Field(ge=1, le=100000)
    price: int = Field(ge=1, le=99)


class PlaybookPatch(BaseModel):
    enabled: Optional[bool] = None
    params: Optional[dict[str, float]] = None


class MemoryBody(BaseModel):
    text: str = Field(min_length=2, max_length=2000)


class MemoryPatch(BaseModel):
    pinned: Optional[bool] = None
    text: Optional[str] = Field(None, min_length=2, max_length=2000)
    importance: Optional[float] = Field(None, ge=0, le=1)


class SoccerOrderBody(BaseModel):
    ticker: str
    side: str = Field(pattern="^(yes|no)$")
    contracts: int = Field(ge=1, le=100000)
    price: int = Field(ge=1, le=99)


class FavsBody(BaseModel):
    game_id: str


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    # Talk about one game: a fresh briefing on it rides along with the message.
    game_id: Optional[str] = Field(default=None, max_length=64)
    # Ask for a full read of that game (the "Agent analysis" button).
    analysis: bool = False


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=500)


class TrainBody(BaseModel):
    episodes: int = Field(ge=1, le=2000)


def create_app(db_path: Optional[str] = None, start_engine: bool = True, cfg: Optional[Config] = None) -> FastAPI:
    cfg = cfg or get_config()
    db = DB(db_path or cfg.db_path)
    hub = Hub()
    auth = Auth(cfg.app_password, cfg.hosted)
    engine = Engine(cfg, db, hub)
    brain = Brain(cfg, engine)
    engine.brain = brain
    soccer = SoccerDesk(cfg, db, engine)
    brain.soccer = soccer
    background: set[asyncio.Task] = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        background.add(task)
        task.add_done_callback(background.discard)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        loop_task = asyncio.create_task(engine.run()) if start_engine else None
        soccer_task = asyncio.create_task(soccer.run()) if start_engine else None
        yield
        for task in (loop_task, soccer_task):
            if task:
                task.cancel()
        await soccer.aclose()
        await engine.aclose()

    app = FastAPI(title="Courtside", lifespan=lifespan)
    app.state.engine = engine
    app.state.soccer = soccer
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        response = auth.check_request(request) or await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # live data; never serve a stale copy
        return response

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, Any]:
        return {"ok": True, "app": "courtside", "locked": auth.locked}

    @app.get("/api/auth/status")
    async def auth_status(request: Request) -> dict[str, bool]:
        return auth.status(request.cookies.get(COOKIE))

    @app.post("/api/auth/login")
    async def auth_login(body: LoginBody, response: Response) -> dict[str, bool]:
        auth.login(body.password, response)
        return {"ok": True}

    @app.post("/api/auth/logout")
    async def auth_logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    def guard(exc: TradeError) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    # ------------------------------------------------------------------ state
    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        return engine.state()

    @app.put("/api/settings")
    async def put_settings(patch: SettingsPatch) -> dict[str, Any]:
        try:
            await engine.update_settings(patch.model_dump(exclude_none=True))
        except TradeError as exc:
            raise guard(exc)
        return engine.state()

    @app.post("/api/agent/start")
    async def agent_start() -> dict[str, Any]:
        await engine.update_settings({"agent_enabled": True})
        return engine.state()

    @app.post("/api/agent/pause")
    async def agent_pause() -> dict[str, Any]:
        await engine.update_settings({"agent_enabled": False})
        return engine.state()

    # ------------------------------------------------------------------ games
    @app.get("/api/games")
    async def get_games() -> list[dict[str, Any]]:
        return [g.to_dict() for g in engine.games]

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str) -> dict[str, Any]:
        game = engine.by_id.get(game_id)
        if game is None:
            raise HTTPException(404, "No such game")
        decisions = db.query("SELECT * FROM decisions WHERE game_id=? ORDER BY id DESC LIMIT 50", [game_id])
        return {
            "game": game.to_dict(),
            "quarter_markets": [
                {
                    "segment": seg,
                    "totals": [rung_dict(r) for r in game.quarter_markets.get(seg, {}).get("total", [])],
                    "spreads": [rung_dict(r) for r in game.quarter_markets.get(seg, {}).get("spread", [])],
                }
                for seg in SEGMENTS
            ],
            "timeline": engine.timelines.get(game_id, []),
            "quarter_timelines": engine.quarter_timelines.get(game_id, {}),
            "players": (game.context or {}).get("players", []),
            "decisions": decisions,
            "positions": [p for p in engine.positions_api() if p["game_id"] == game_id],
        }

    # ----------------------------------------------------------------- trading
    @app.get("/api/positions")
    async def get_positions() -> list[dict[str, Any]]:
        return engine.positions_api()

    @app.post("/api/positions/{position_id}/close")
    async def close_position(position_id: int) -> dict[str, Any]:
        try:
            return await engine.close_position(position_id, reason="manual")
        except TradeError as exc:
            raise guard(exc)

    @app.get("/api/trades")
    async def get_trades(limit: int = 100) -> list[dict[str, Any]]:
        return engine.trades_api(min(max(limit, 1), 500))

    @app.get("/api/decisions")
    async def get_decisions(limit: int = 100, game_id: Optional[str] = None) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 500)
        if game_id:
            return db.query("SELECT * FROM decisions WHERE game_id=? ORDER BY id DESC LIMIT ?", [game_id, limit])
        return db.query("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", [limit])

    @app.post("/api/orders")
    async def post_order(body: OrderBody) -> dict[str, Any]:
        try:
            return await engine.manual_order(body.ticker, body.side, body.contracts, body.price)
        except TradeError as exc:
            raise guard(exc)

    # ------------------------------------------------------------------ soccer
    @app.get("/api/soccer")
    async def soccer_board() -> dict[str, Any]:
        return soccer.board()

    @app.get("/api/soccer/matches/{match_id}")
    async def soccer_match(match_id: str) -> dict[str, Any]:
        match = soccer.by_id.get(match_id)
        if match is None:
            raise HTTPException(404, "No such match")
        return soccer.detail(match)

    @app.post("/api/soccer/orders")
    async def soccer_order(body: SoccerOrderBody) -> dict[str, Any]:
        try:
            return await soccer.order(body.ticker, body.side, body.contracts, body.price)
        except SoccerTradeError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/soccer/positions/{position_id}/close")
    async def soccer_close(position_id: int) -> dict[str, Any]:
        try:
            return await soccer.close(position_id)
        except SoccerTradeError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/soccer/trades")
    async def soccer_trades(limit: int = 50) -> list[dict[str, Any]]:
        return soccer.trades_api(min(max(limit, 1), 500))

    # ---------------------------------------------------------------- playbook
    @app.get("/api/playbook")
    async def get_playbook() -> list[dict[str, Any]]:
        return engine.playbook.to_api()

    @app.put("/api/playbook/{strategy_id}")
    async def put_playbook(strategy_id: str, patch: PlaybookPatch) -> dict[str, Any]:
        if strategy_id not in STRATEGIES:
            raise HTTPException(404, "No such strategy")
        try:
            engine.playbook.update(strategy_id, enabled=patch.enabled, params=patch.params)
        except KeyError as exc:
            raise HTTPException(400, str(exc.args[0]))
        return next(s for s in engine.playbook.to_api() if s["id"] == strategy_id)

    # ------------------------------------------------------------------ memory
    @app.get("/api/memory")
    async def get_memory(kind: Optional[str] = None, q: Optional[str] = None) -> list[dict[str, Any]]:
        return engine.memory.list(kind=kind or None, q=q or None)

    @app.post("/api/memory")
    async def post_memory(body: MemoryBody) -> dict[str, Any]:
        mem = engine.memory.add("guidance", body.text, importance=0.85, source="user", pinned=True)
        hub.emit("memory", mem)
        if brain.available:
            spawn(brain.interpret_guidance(body.text, mem["id"]))
        return mem

    @app.patch("/api/memory/{memory_id}")
    async def patch_memory(memory_id: int, patch: MemoryPatch) -> dict[str, Any]:
        mem = engine.memory.update(memory_id, patch.model_dump(exclude_none=True))
        if mem is None:
            raise HTTPException(404, "No such memory")
        return mem

    @app.delete("/api/memory/{memory_id}")
    async def delete_memory(memory_id: int) -> dict[str, bool]:
        engine.memory.delete(memory_id)
        return {"ok": True}

    # ---------------------------------------------------------------- learning
    @app.get("/api/learning")
    async def get_learning() -> dict[str, Any]:
        return engine.learning_state()

    @app.post("/api/sim/train")
    async def sim_train(body: TrainBody) -> dict[str, Any]:
        return await asyncio.to_thread(train, db, engine.playbook, engine.learner, engine.memory, body.episodes)

    @app.post("/api/sim/reset")
    async def sim_reset() -> dict[str, Any]:
        await engine.reset_sim()
        return engine.state()

    # -------------------------------------------------------------------- chat
    @app.get("/api/chat/history")
    async def chat_history() -> list[dict[str, Any]]:
        return brain.history()

    @app.delete("/api/chat/history")
    async def chat_clear() -> dict[str, bool]:
        db.execute("DELETE FROM chat")
        return {"ok": True}

    @app.post("/api/favs")
    async def favs(body: FavsBody) -> dict[str, Any]:
        """The agent's favourite bets on one game or match: 85-90% confidence, priced below it."""
        try:
            return await brain.favs(body.game_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            log.exception("favs failed")
            raise HTTPException(502, f"The agent could not pick right now: {type(exc).__name__}")

    @app.post("/api/chat")
    async def chat(body: ChatBody) -> StreamingResponse:
        async def stream():
            try:
                async for event in brain.chat(body.message, game_id=body.game_id, analysis=body.analysis):
                    yield f"data: {json.dumps(event, default=str)}\n\n"
            except Exception as exc:
                log.exception("chat failed")
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --------------------------------------------------------------- websocket
    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        if not auth.check_socket(socket):
            await socket.close(code=4401)
            return
        await hub.join(socket)
        await hub.send(socket, "state", engine.state())
        await hub.send(socket, "games", [g.to_dict() for g in engine.games])
        await hub.send(socket, "positions", engine.positions_api())
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            hub.leave(socket)

    # ------------------------------------------------- built UI (production)
    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            if path.startswith(("api/", "ws")):
                raise HTTPException(404, "Not found")  # never answer an API path with the page
            target = (DIST / path).resolve()
            inside = target.is_relative_to(DIST) and target.is_file()
            return FileResponse(target if path and inside else DIST / "index.html")

    return app
