"""Fan-out of live events to connected browsers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def join(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)

    def leave(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def send(self, ws: WebSocket, kind: str, data: Any) -> None:
        try:
            await ws.send_text(json.dumps({"type": kind, "data": data}))
        except Exception:
            self.leave(ws)

    async def publish(self, kind: str, data: Any) -> None:
        if not self.clients:
            return
        message = json.dumps({"type": kind, "data": data})
        clients = list(self.clients)
        results = await asyncio.gather(
            *(ws.send_text(message) for ws in clients), return_exceptions=True
        )
        for ws, result in zip(clients, results):
            if isinstance(result, Exception):
                self.leave(ws)

    def toast(self, level: str, title: str, body: str = "") -> None:
        """Fire-and-forget notification; safe to call from sync code inside the loop."""
        try:
            asyncio.get_running_loop().create_task(
                self.publish("toast", {"level": level, "title": title, "body": body})
            )
        except RuntimeError:
            pass

    def emit(self, kind: str, data: Any) -> None:
        try:
            asyncio.get_running_loop().create_task(self.publish(kind, data))
        except RuntimeError:
            pass
