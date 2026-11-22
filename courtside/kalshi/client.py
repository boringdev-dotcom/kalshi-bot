"""Kalshi REST client: public market data plus signed portfolio calls.

Order placement targets the V2 endpoint (`POST /portfolio/events/orders`),
which quotes everything from the YES side:

    side "bid" = buy YES at `price`
    side "ask" = sell YES at `price`  (economically: buy NO at 1 - price)

Courtside thinks in under/over, so `side_and_price` does the translation.

Kalshi keeps an account's cash in separate pools, one per exchange shard, and a
market can only spend from its own shard (NBA and the soccer leagues sit on
different ones). The Kalshi app and site move cash between shards when you
order; API orders do not, so `fund_shard` tops the market's shard up from the
others before each buy.
"""

from __future__ import annotations

import asyncio
import base64
import math
import time
import uuid
from typing import Any, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

API_PREFIX = "/trade-api/v2"
PUBLIC_HOST = "https://api.elections.kalshi.com"
READS_PER_SECOND = 8.0  # Kalshi turns away bursts of reads past about a dozen at once
NBA_TOTAL_SERIES = "KXNBATOTAL"
NBA_SPREAD_SERIES = "KXNBASPREAD"  # full-game spreads; quarters have their own series below
CENTICENTS_PER_DOLLAR = 10_000  # shard transfers are sized in hundredths of a cent


def quarter_series(q: int, kind: str) -> str:
    """Kalshi series for a quarter market, e.g. KXNBA1QTOTAL, KXNBA3QSPREAD."""
    return f"KXNBA{q}Q{'TOTAL' if kind == 'total' else 'SPREAD'}"


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
        self._read_lock = asyncio.Lock()
        self._next_read = 0.0

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
        for attempt in range(2):
            if method == "GET":
                await self._pace()
            headers = self._headers(method, full) if signed else {}
            resp = await self._http.request(
                method, (host or self.host) + full, params=params, json=body, headers=headers
            )
            if resp.status_code != 429 or method != "GET" or attempt:
                break
            await asyncio.sleep(1.0)  # turned away for going too fast: wait, then once more
        if resp.status_code >= 400:
            raise KalshiError(f"Kalshi {method} {path} -> {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    async def _pace(self) -> None:
        """Space reads out evenly. The NBA and soccer desks share this client and Kalshi's limit."""
        async with self._read_lock:
            now = time.monotonic()
            wait = self._next_read - now
            self._next_read = max(now, self._next_read) + 1.0 / READS_PER_SECOND
        if wait > 0:
            await asyncio.sleep(wait)

    # -- public market data (always from production: real prices) ------------
    async def nba_total_events(self) -> list[dict[str, Any]]:
        return await self.events(NBA_TOTAL_SERIES)

    async def events(self, series_ticker: str) -> list[dict[str, Any]]:
        """Open events for a series, with their markets and live quotes."""
        events: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(5):
            page = await self._request(
                "GET",
                "/events",
                params={
                    "series_ticker": series_ticker,
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

    async def positions(self) -> dict[str, float]:
        """Contracts held per market: positive is YES, negative is NO."""
        held: dict[str, float] = {}
        cursor: Optional[str] = None
        for _ in range(10):
            params: dict[str, Any] = {"count_filter": "position", "limit": 200, **({"cursor": cursor} if cursor else {})}
            data = await self._request("GET", "/portfolio/positions", params=params, signed=True)
            for row in data.get("market_positions") or []:
                count = float(row.get("position_fp") or row.get("position") or 0)
                if count:
                    held[row["ticker"]] = count
            cursor = data.get("cursor")
            if not cursor:
                break
        return held

    async def fills(self, ticker: str, limit: int = 100) -> list[dict[str, Any]]:
        """Recent fills on one market, newest first: contracts, YES/NO price in cents, fee, time."""
        data = await self._request("GET", "/portfolio/fills", params={"ticker": ticker, "limit": limit}, signed=True)
        out = []
        for row in data.get("fills") or []:
            out.append({
                "count": float(row.get("count_fp") or row.get("count") or 0),
                "yes_price": float(row.get("yes_price_dollars") or 0) * 100,
                "no_price": float(row.get("no_price_dollars") or 0) * 100,
                "fee": float(row.get("fee_cost") or 0),
                "created_time": row.get("created_time") or "",
                "order_id": row.get("order_id"),
            })
        return out

    async def shard_balances(self) -> dict[int, float]:
        """Cash in each exchange shard, in dollars."""
        data = await self._request("GET", "/portfolio/balance", signed=True)
        return {int(row["exchange_index"]): float(row["balance"]) for row in data.get("balance_breakdown") or []}

    async def market_shard(self, ticker: str) -> int:
        return int((await self.market(ticker)).get("exchange_index") or 0)

    async def transfer_between_shards(self, source: int, destination: int, dollars: float) -> str:
        body = {
            "source": "event_contract",
            "destination": "event_contract",
            "amount": int(round(dollars * CENTICENTS_PER_DOLLAR)),
            "source_exchange_shard": source,
            "destination_exchange_shard": destination,
            "client_transfer_id": str(uuid.uuid4()),
        }
        data = await self._request("POST", "/portfolio/intra_exchange_instance_transfer", body=body, signed=True)
        return str(data.get("transfer_id") or "")

    async def fund_shard(self, ticker: str, needed: float, wait_s: float = 8.0) -> list[dict[str, Any]]:
        """Make sure the shard `ticker` trades on holds `needed` dollars, pulling from the
        other shards (fullest first) if it is short. Returns the transfers made."""
        shard = await self.market_shard(ticker)
        balances = await self.shard_balances()
        short = round(needed - balances.get(shard, 0.0), 4)
        if short <= 0:
            return []
        others = sorted(((b, i) for i, b in balances.items() if i != shard and b > 0), reverse=True)
        total = sum(balances.values())
        if sum(b for b, _ in others) + 1e-9 < short:
            raise KalshiError(f"Not enough cash on Kalshi: this order needs ${needed:,.2f} and the account holds ${total:,.2f}.")
        moves: list[dict[str, Any]] = []
        for available, source in others:
            if short <= 0:
                break
            amount = min(available, math.ceil(short * 100) / 100.0)  # whole cents, never more than the shard has
            transfer_id = await self.transfer_between_shards(source, shard, amount)
            moves.append({"from": source, "to": shard, "amount": amount, "transfer_id": transfer_id})
            short = round(short - amount, 4)
        # Transfers settle asynchronously. Wait (the balance endpoint allows ~1 read a second)
        # until the cash lands; if it is slow, place the order anyway and let Kalshi decide.
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            try:
                if (await self.shard_balances()).get(shard, 0.0) + 1e-9 >= needed:
                    break
            except KalshiError:
                pass
        return moves

    async def place_order(
        self, ticker: str, side: str, action: str, contracts: int, price_cents: int
    ) -> dict[str, Any]:
        """Immediate-or-cancel limit order. Returns filled contracts and average price.

        A buy first makes sure the market's shard holds enough cash (see `fund_shard`).

        `price_cents` is the limit for the side being traded (e.g. 94 to buy the
        under at 94c). The returned `price` is expressed the same way.
        """
        if action == "buy":
            p = price_cents / 100.0
            fee = math.ceil(0.07 * contracts * p * (1 - p) * 100 - 1e-9) / 100.0
            await self.fund_shard(ticker, contracts * p + fee + 0.01)
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
