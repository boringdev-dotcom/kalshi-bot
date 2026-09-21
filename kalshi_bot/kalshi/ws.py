"""Kalshi WebSocket client for held-market ticker updates (price-only)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import websockets

from .auth import WS_PATH, auth_headers

logger = logging.getLogger(__name__)

TickerCallback = Callable[[str, dict], Awaitable[None]]


async def stream_tickers(
    ws_url: str,
    key_id: str,
    private_key_pem: str,
    tickers: list[str],
    on_ticker: TickerCallback,
    stop_event: Optional[asyncio.Event] = None,
    reconnect_delay: float = 1.0,
    max_reconnect_delay: float = 30.0,
) -> None:
    """Subscribe to ticker updates for held markets. No LLM calls."""
    if not tickers:
        return
    delay = reconnect_delay
    while True:
        if stop_event and stop_event.is_set():
            return
        try:
            headers = auth_headers(key_id, private_key_pem, "GET", WS_PATH)
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                delay = reconnect_delay
                sub_id = 1
                for ticker in tickers:
                    await ws.send(
                        json.dumps(
                            {
                                "id": sub_id,
                                "cmd": "subscribe",
                                "params": {"channels": ["ticker"], "market_ticker": ticker},
                            }
                        )
                    )
                    sub_id += 1
                logger.info("Kalshi WS subscribed to %s tickers", len(tickers))
                async for raw in ws:
                    if stop_event and stop_event.is_set():
                        return
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") in {"subscribed", "error"}:
                        if event.get("type") == "error":
                            logger.warning("Kalshi WS error: %s", event)
                        continue
                    data = event.get("msg") or event.get("data") or event
                    ticker = data.get("market_ticker") or data.get("ticker")
                    if ticker and event.get("type") in {"ticker", "market", None}:
                        await on_ticker(ticker, data)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Kalshi WS disconnected: %s; retry in %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_reconnect_delay)
