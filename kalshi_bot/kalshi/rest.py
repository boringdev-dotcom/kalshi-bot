"""Kalshi REST client: markets, orderbook, positions, balance, orders."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from .auth import auth_headers

logger = logging.getLogger(__name__)

SOCCER_TOTAL_SERIES = [
    "KXEPLTOTAL",
    "KXLALIGATOTAL",
    "KXBUNDESLIGATOTAL",
    "KXLIGUE1TOTAL",
    "KXSERIEATOTAL",
    "KXUCLTOTAL",
    "KXMLSTOTAL",
    "KXUELTOTAL",
    "KXEFLATOTAL",
    "KXLIGAMXTOTAL",
]

SOCCER_SERIES_PREFIXES = (
    "KXEPL",
    "KXLALIGA",
    "KXBUNDESLIGA",
    "KXLIGUE1",
    "KXSERIEA",
    "KXUCL",
    "KXMLS",
    "KXUEL",
    "KXEFLA",
    "KXLIGAMX",
    "KXSOCCER",
)


class KalshiClient:
    def __init__(
        self,
        key_id: str,
        private_key_pem: str,
        base_url: str,
        timeout: float = 30.0,
    ) -> None:
        self.key_id = key_id
        self.private_key_pem = private_key_pem
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        query = ""
        if params:
            cleaned = {k: v for k, v in params.items() if v is not None}
            if cleaned:
                query = "?" + urlencode(cleaned)
        sign_path = path + query
        headers = auth_headers(self.key_id, self.private_key_pem, method, sign_path)
        headers["Content-Type"] = "application/json"
        url = self.base_url + sign_path
        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(method, url, headers=headers, json=json_body)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                logger.error("Kalshi %s %s failed: %s %s", method, path, response.status_code, response.text)
                raise
            if not response.content:
                return {}
            return response.json()

    def get_markets(
        self,
        status: str = "open",
        series_ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
        limit: int = 200,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/trade-api/v2/markets",
            params={
                "status": status,
                "series_ticker": series_ticker,
                "event_ticker": event_ticker,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def get_market(self, ticker: str) -> dict[str, Any]:
        data = self._request("GET", f"/trade-api/v2/markets/{ticker}")
        return data.get("market") or data

    def get_events(
        self,
        status: Optional[str] = "open",
        series_ticker: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/trade-api/v2/events",
            params={
                "status": status,
                "series_ticker": series_ticker,
                "limit": limit,
                "cursor": cursor,
            },
        )

    def get_orderbook(self, ticker: str, depth: int = 5) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/trade-api/v2/markets/{ticker}/orderbook",
            params={"depth": depth} if depth else None,
        )
        book = data.get("orderbook") or data
        yes = book.get("yes") or []
        no = book.get("no") or []
        return {"ticker": ticker, "yes": yes, "no": no}

    def get_balance(self) -> dict[str, Any]:
        return self._request("GET", "/trade-api/v2/portfolio/balance")

    def get_positions(self, ticker: Optional[str] = None, limit: int = 200) -> dict[str, Any]:
        return self._request(
            "GET",
            "/trade-api/v2/portfolio/positions",
            params={"ticker": ticker, "limit": limit},
        )

    def get_fills(self, ticker: Optional[str] = None, limit: int = 200, cursor: Optional[str] = None) -> dict[str, Any]:
        return self._request(
            "GET",
            "/trade-api/v2/portfolio/fills",
            params={"ticker": ticker, "limit": limit, "cursor": cursor},
        )

    def get_orders(self, ticker: Optional[str] = None, limit: int = 200, cursor: Optional[str] = None) -> dict[str, Any]:
        return self._request(
            "GET",
            "/trade-api/v2/portfolio/orders",
            params={"ticker": ticker, "limit": limit, "cursor": cursor},
        )

    def get_settlements(self, limit: int = 200, cursor: Optional[str] = None) -> dict[str, Any]:
        return self._request(
            "GET",
            "/trade-api/v2/portfolio/settlements",
            params={"limit": limit, "cursor": cursor},
        )

    def create_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price: int,
        client_order_id: Optional[str] = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "ticker": ticker,
            "side": side,
            "action": action,
            "count": count,
            "type": "limit",
        }
        if side.lower() == "no":
            body["no_price"] = price
        else:
            body["yes_price"] = price
        if client_order_id:
            body["client_order_id"] = client_order_id
        return self._request("POST", "/trade-api/v2/portfolio/orders", json_body=body)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/trade-api/v2/portfolio/orders/{order_id}")

    def iter_markets(self, **kwargs: Any) -> list[dict[str, Any]]:
        markets: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = self.get_markets(cursor=cursor, **kwargs)
            batch = page.get("markets") or []
            markets.extend(batch)
            cursor = page.get("cursor")
            if not cursor or not batch:
                break
        return markets

    def soccer_total_markets(self, status: str = "open") -> list[dict[str, Any]]:
        seen: set[str] = set()
        found: list[dict[str, Any]] = []
        for series in SOCCER_TOTAL_SERIES:
            try:
                for market in self.iter_markets(status=status, series_ticker=series, limit=200):
                    ticker = market.get("ticker")
                    if ticker and ticker not in seen:
                        seen.add(ticker)
                        found.append(market)
            except Exception as exc:
                logger.warning("Series %s fetch failed: %s", series, exc)
        if found:
            return found
        logger.info("Falling back to event scan for soccer totals")
        return self._scan_soccer_totals(status, seen)

    def _scan_soccer_totals(self, status: str, seen: set[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        cursor = None
        while True:
            page = self.get_events(status=status, limit=100, cursor=cursor)
            events = page.get("events") or []
            if not events:
                break
            for event in events:
                event_ticker = (event.get("event_ticker") or "").upper()
                title = (event.get("title") or "").upper()
                series = (event.get("series_ticker") or "").upper()
                blob = f"{event_ticker} {title} {series}"
                if "TOTAL" not in blob:
                    continue
                if not any(prefix in blob for prefix in SOCCER_SERIES_PREFIXES):
                    if "SOCCER" not in blob and "FOOTBALL" not in blob:
                        continue
                try:
                    for market in self.iter_markets(status=status, event_ticker=event.get("event_ticker"), limit=50):
                        ticker = market.get("ticker")
                        if ticker and ticker not in seen and is_total_market(market):
                            seen.add(ticker)
                            found.append(market)
                except Exception as exc:
                    logger.warning("Event %s market fetch failed: %s", event_ticker, exc)
            cursor = page.get("cursor")
            if not cursor:
                break
        return found


def is_total_market(market: dict[str, Any]) -> bool:
    series = (market.get("series_ticker") or "").upper()
    ticker = (market.get("ticker") or "").upper()
    title = f"{market.get('title') or ''} {market.get('subtitle') or ''}".upper()
    if "TOTAL" in series or "TOTAL" in ticker:
        return True
    return "OVER" in title and "GOAL" in title


def parse_strike(market: dict[str, Any]) -> Optional[float]:
    ticker = market.get("ticker") or ""
    for text in (
        market.get("yes_sub_title") or "",
        market.get("subtitle") or "",
        market.get("title") or "",
        ticker,
    ):
        match = re.search(r"(\d+(?:\.\d+)?)\s*goals?", text, re.I)
        if match:
            return float(match.group(1))
        match = re.search(r"over\s+(\d+(?:\.\d+)?)", text, re.I)
        if match:
            return float(match.group(1))
    parts = ticker.split("-")
    if len(parts) >= 3:
        suffix = parts[-1]
        match = re.search(r"(\d+)$", suffix)
        if match:
            return int(match.group(1)) + 0.5
    return None


def no_depth(orderbook: dict[str, Any]) -> int:
    total = 0
    for level in orderbook.get("no") or []:
        if isinstance(level, (list, tuple)) and len(level) >= 2:
            total += int(level[1] or 0)
        elif isinstance(level, dict):
            total += int(level.get("quantity") or level.get("qty") or 0)
    return total


def best_no_ask(market: dict[str, Any], orderbook: Optional[dict[str, Any]] = None) -> Optional[int]:
    if market.get("no_ask") is not None:
        return int(market["no_ask"])
    yes_bid = market.get("yes_bid")
    if yes_bid is not None:
        return 100 - int(yes_bid)
    if orderbook:
        yes = orderbook.get("yes") or []
        if yes and isinstance(yes[0], (list, tuple)):
            return 100 - int(yes[0][0])
    return None


def best_no_bid(market: dict[str, Any], orderbook: Optional[dict[str, Any]] = None) -> Optional[int]:
    if market.get("no_bid") is not None:
        return int(market["no_bid"])
    yes_ask = market.get("yes_ask")
    if yes_ask is not None:
        return 100 - int(yes_ask)
    if orderbook:
        no = orderbook.get("no") or []
        if no and isinstance(no[0], (list, tuple)):
            return int(no[0][0])
    return None
