"""Live buys fund the market's exchange shard first, the way Kalshi's own app does."""

from __future__ import annotations

import asyncio
import json

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from courtside.kalshi.client import KalshiClient


def fake_kalshi(shards: dict[int, float], market_shard: int, settle_after: int = 0):
    """A Kalshi stand-in: balances per shard, transfers that land after `settle_after` balance reads."""
    calls: list[tuple[str, str, dict]] = []
    pending: list[tuple[int, int, float]] = []
    reads = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/trade-api/v2")
        body = json.loads(request.content) if request.content else {}
        calls.append((request.method, path, body))
        if path.startswith("/markets/"):
            return httpx.Response(200, json={"market": {"ticker": path.rsplit("/", 1)[1], "exchange_index": market_shard}})
        if path == "/portfolio/balance":
            reads["n"] += 1
            if reads["n"] > settle_after:
                for src, dst, amt in pending:
                    shards[src] -= amt
                    shards[dst] = shards.get(dst, 0.0) + amt
                pending.clear()
            breakdown = [{"exchange_index": i, "balance": f"{b:.4f}"} for i, b in shards.items()]
            return httpx.Response(200, json={"balance": round(sum(shards.values()) * 100), "balance_breakdown": breakdown})
        if path == "/portfolio/intra_exchange_instance_transfer":
            pending.append((body["source_exchange_shard"], body["destination_exchange_shard"], body["amount"] / 10_000))
            return httpx.Response(200, json={"transfer_id": "t1"})
        if path == "/portfolio/events/orders":
            return httpx.Response(201, json={"order_id": "o1", "fill_count": body["count"], "average_fill_price": "0.1900", "average_fee_paid": "0.0108"})
        return httpx.Response(404, json={})

    return handler, calls


def client(handler) -> KalshiClient:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    k = KalshiClient("key-id", pem)
    k._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    k._next_read = 0.0
    return k


def test_buy_tops_up_the_markets_shard_from_the_others():
    # Soccer on shard 0 with $40; the NBA shard holds the rest. Buying 115 NO at 81c needs ~$94.39.
    shards = {0: 40.0, 1: 0.0, 2: 0.0, 3: 300.0}
    handler, calls = fake_kalshi(shards, market_shard=0, settle_after=2)
    fill = asyncio.run(client(handler).place_order("KXEPLTOTAL-26NOV21MCIFUL-3", "under", "buy", 115, 81))
    transfers = [b for m, p, b in calls if p == "/portfolio/intra_exchange_instance_transfer"]
    assert len(transfers) == 1
    t = transfers[0]
    assert (t["source_exchange_shard"], t["destination_exchange_shard"]) == (3, 0)
    assert t["source"] == t["destination"] == "event_contract"
    # 115 x 81c + $1.24 fee + 1c cushion = $94.40; less the $40 there = $54.40 (in centicents).
    assert t["amount"] == 544000
    # The order goes out only after the cash has landed.
    order_at = [p for _, p, _ in calls].index("/portfolio/events/orders")
    assert shards[0] >= 94.39 and order_at > [p for _, p, _ in calls].index("/portfolio/intra_exchange_instance_transfer")
    assert fill["filled"] == 115 and fill["price"] == 81


def test_buy_with_enough_in_the_shard_moves_nothing():
    handler, calls = fake_kalshi({0: 10.0, 3: 200.0}, market_shard=3)
    asyncio.run(client(handler).place_order("KXNBATOTAL-X-220", "under", "buy", 10, 90))
    assert not [p for _, p, _ in calls if "transfer" in p]


def test_sell_never_moves_cash():
    handler, calls = fake_kalshi({0: 0.0, 3: 0.0}, market_shard=0)
    asyncio.run(client(handler).place_order("KXEPLTOTAL-X-3", "under", "sell", 5, 70))
    assert [p for _, p, _ in calls] == ["/portfolio/events/orders"]


def test_not_enough_anywhere_says_so_plainly():
    handler, calls = fake_kalshi({0: 5.0, 3: 10.0}, market_shard=0)
    try:
        asyncio.run(client(handler).place_order("KXEPLTOTAL-X-3", "under", "buy", 100, 81))
    except Exception as exc:  # noqa: BLE001
        assert "account holds $15.00" in str(exc)
    else:
        raise AssertionError("expected a clear not-enough-cash error")
    assert not [p for _, p, _ in calls if "transfer" in p or "orders" in p]
