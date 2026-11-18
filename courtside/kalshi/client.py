"""Kalshi REST client: public market data plus signed portfolio calls.

Order placement targets the V2 endpoint (`POST /portfolio/events/orders`),
which quotes everything from the YES side:

    side "bid" = buy YES at `price`
    side "ask" = sell YES at `price`  (economically: buy NO at 1 - price)

Courtside thinks in under/over, so `side_and_price` does the translation.
"""

from __future__ import annotations

import base64
import time
import uuid
from typing import Any, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

API_PREFIX = "/trade-api/v2"
PUBLIC_HOST = "https://api.elections.kalshi.com"
NBA_TOTAL_SERIES = "KXNBATOTAL"


class KalshiError(RuntimeError):
    pass


def load_private_key(pem: str):
    text = pem.strip().replace("\\n", "\n")
    if not text.startswith("-----"):
        body = "\n".join(text[i : i + 64] for i in range(0, len(text), 64))
        text = f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"
    candidates = [text]
    if "BEGIN PRIVATE KEY" in text:
        candidates.append(
            text.replace("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY").replace(
                "END PRIVATE KEY", "END RSA PRIVATE KEY"
            )
        )
    last: Exception | None = None
    for candidate in candidates:
        try:
            return serialization.load_pem_private_key(candidate.encode(), password=None)
        except ValueError as exc:
            last = exc
    raise KalshiError(f"Could not parse KALSHI_PRIVATE_KEY_PEM: {last}")


def cents(dollars: Any) -> Optional[int]:
    """'0.9400' -> 94. Returns None for missing or zero quotes."""
    try:
        value = round(float(dollars) * 100)
    except (TypeError, ValueError):
        return None
    return value if 0 < value < 100 else None


def side_and_price(side: str, action: str, price_cents: int) -> tuple[str, str]:
    """Translate (under|over, buy|sell, price for that side) to V2 (bid|ask, YES price)."""
    if side == "over":
        v2_side = "bid" if action == "buy" else "ask"
        yes_price = price_cents
    else:
        # Buying NO at p is selling YES at 100 - p; selling NO is buying YES back.
        v2_side = "ask" if action == "buy" else "bid"
        yes_price = 100 - price_cents
    return v2_side, f"{yes_price / 100:.4f}"


class KalshiClient:
    def __init__(self, key_id: str = "", private_key_pem: str = "", host: str = PUBLIC_HOST):
        self.key_id = key_id
        self.host = host.rstrip("/")
        self._key = load_private_key(private_key_pem) if private_key_pem.strip() else None
        self._http = httpx.AsyncClient(timeout=15.0)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def can_sign(self) -> bool:
        return bool(self.key_id and self._key)

    def _headers(self, method: str, path: str) -> dict[str, str]:
        if not self.can_sign:
            raise KalshiError("Kalshi API keys are not configured")
        ts = str(int(time.time() * 1000))
        signature = self._key.sign(
            f"{ts}{method}{path}".encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
        signed: bool = False,
        host: Optional[str] = None,
    ) -> dict[str, Any]:
        full = API_PREFIX + path
        headers = self._headers(method, full) if signed else {}
        resp = await self._http.request(
            method, (host or self.host) + full, params=params, json=body, headers=headers
        )
        if resp.status_code >= 400:
            raise KalshiError(f"Kalshi {method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    # -- public market data (always from production: real prices) ------------
    async def nba_total_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(5):
            page = await self._request(
                "GET",
                "/events",
                params={
                    "series_ticker": NBA_TOTAL_SERIES,
                    "status": "open",
                    "with_nested_markets": "true",
                    "limit": 100,
                    **({"cursor": cursor} if cursor else {}),
                },
                host=PUBLIC_HOST,
            )
            events.extend(page.get("events") or [])
            cursor = page.get("cursor")
            if not cursor:
                break
        return events

    async def market(self, ticker: str) -> dict[str, Any]:
        data = await self._request("GET", f"/markets/{ticker}", host=PUBLIC_HOST)
        return data.get("market") or data

    # -- signed portfolio ---------------------------------------------------
    async def balance(self) -> dict[str, float]:
        data = await self._request("GET", "/portfolio/balance", signed=True)
        return {
            "cash": float(data.get("balance", 0)) / 100.0,
            "portfolio_value": float(data.get("portfolio_value", 0)) / 100.0,
        }

    async def place_order(
        self, ticker: str, side: str, action: str, contracts: int, price_cents: int
    ) -> dict[str, Any]:
        """Immediate-or-cancel limit order. Returns filled contracts and average price.

        `price_cents` is the limit for the side being traded (e.g. 94 to buy the
        under at 94c). The returned `price` is expressed the same way.
        """
        v2_side, yes_price = side_and_price(side, action, price_cents)
        body = {
            "ticker": ticker,
            "client_order_id": str(uuid.uuid4()),
            "side": v2_side,
            "count": f"{contracts:.2f}",
            "price": yes_price,
            "time_in_force": "immediate_or_cancel",
            "self_trade_prevention_type": "taker_at_cross",
        }
        if action == "sell":
            body["reduce_only"] = True
        data = await self._request("POST", "/portfolio/events/orders", body=body, signed=True)
        filled = float(data.get("fill_count") or 0)
        avg_yes = data.get("average_fill_price")
        fill_cents = price_cents
        if avg_yes is not None:
            yes_cents = float(avg_yes) * 100
            fill_cents = yes_cents if side == "over" else 100 - yes_cents
        fee_each = float(data.get("average_fee_paid") or 0)
        return {
            "order_id": data.get("order_id"),
            "filled": int(filled),
            "price": fill_cents,
            "fees": round(fee_each * filled, 2),
        }
