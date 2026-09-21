"""Tool schemas and dispatch for Pundit (read-only) and Kalshi (write)."""

from __future__ import annotations

import json
from typing import Any, Optional

from kalshi_bot.execution import flatten_position, remaining_caps, submit_buy_no
from kalshi_bot.kalshi.rest import KalshiClient
from kalshi_bot.playbook import constraints_text
from kalshi_bot.store import Store

PUNDIT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_game_state",
            "description": "Current score, minute, phase, rem per market.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orderbook",
            "description": "Kalshi orderbook and No prices for a market ticker.",
            "parameters": {
                "type": "object",
                "properties": {"ticker": {"type": "string"}},
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_prematch_stats",
            "description": "Last-5 form, GF/GA, over/under rate, league tier. Never invent.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_memory",
            "description": "Your prior notes for this game.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]

KALSHI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_positions",
            "description": "Open positions for this game (paper or live journal).",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_balance",
            "description": "Kalshi account balance (live host) plus paper/paused flags.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_playbook",
            "description": "Hard sizing, price band, and stop constraints.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_limit_order",
            "description": "Buy No on a totals market. Idempotent per game/market/event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "count": {"type": "integer"},
                    "price": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "count", "price", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flatten",
            "description": "Close the No position on a market.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Cancel a resting live Kalshi order by id.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
]


class ToolContext:
    def __init__(
        self,
        store: Store,
        client: Optional[KalshiClient],
        game: dict[str, Any],
        event: dict[str, Any],
        agent: str,
        paper: bool,
        paused: bool,
        day_start_ts: int,
    ) -> None:
        self.store = store
        self.client = client
        self.game = game
        self.event = event
        self.agent = agent
        self.paper = paper
        self.paused = paused
        self.day_start_ts = day_start_ts
        self.actions: list[dict[str, Any]] = []


def dispatch(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> str:
    game = ctx.store.get_game(ctx.game["id"]) or ctx.game
    if name == "get_game_state":
        return json.dumps(
            {
                "game": {
                    "id": game["id"],
                    "home": game["home_team"],
                    "away": game["away_team"],
                    "league": game.get("league"),
                    "score": f"{game.get('home_goals', 0)}-{game.get('away_goals', 0)}",
                    "minute": game.get("minute"),
                    "phase": game.get("phase"),
                    "red_cards": game.get("red_cards"),
                },
                "markets": game.get("markets") or [],
                "event": ctx.event,
            }
        )
    if name == "get_orderbook":
        ticker = arguments.get("ticker")
        market = ctx.store.get_market(ticker) if ticker else None
        book = None
        if ctx.client and ticker:
            try:
                book = ctx.client.get_orderbook(ticker, depth=5)
            except Exception as exc:
                book = {"error": str(exc)}
        return json.dumps({"market": market, "orderbook": book})
    if name == "get_prematch_stats":
        return json.dumps(game.get("prematch") or {"note": "prematch stats not available; do not invent"})
    if name == "get_memory":
        return json.dumps({"notes": ctx.store.get_memory(game["id"], ctx.agent)})
    if name == "get_positions":
        return json.dumps({"positions": ctx.store.positions_for_game(game["id"])})
    if name == "get_balance":
        live = None
        if ctx.client and not ctx.paper:
            try:
                live = ctx.client.get_balance()
            except Exception as exc:
                live = {"error": str(exc)}
        match_left, day_left = remaining_caps(ctx.store, game["id"], ctx.day_start_ts)
        return json.dumps(
            {
                "paper": ctx.paper,
                "paused": ctx.paused,
                "live_balance": live,
                "remaining_match_contracts": match_left,
                "remaining_day_contracts": day_left,
            }
        )
    if name == "get_playbook":
        return json.dumps({"text": constraints_text()})
    if name == "place_limit_order":
        if ctx.paused:
            return json.dumps({"error": "trading is paused"})
        try:
            result = submit_buy_no(
                ctx.store,
                ctx.client,
                game_id=game["id"],
                ticker=arguments["ticker"],
                event_id=ctx.event.get("id"),
                count=int(arguments["count"]),
                price=int(arguments["price"]),
                reason=arguments.get("reason") or "",
                paper=ctx.paper,
            )
            ctx.actions.append({"action": "buy_no", "result": result})
            return json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    if name == "flatten":
        if ctx.paused:
            return json.dumps({"error": "trading is paused"})
        try:
            result = flatten_position(
                ctx.store,
                ctx.client,
                game_id=game["id"],
                ticker=arguments["ticker"],
                event_id=ctx.event.get("id"),
                reason=arguments.get("reason") or "",
                paper=ctx.paper,
            )
            ctx.actions.append({"action": "flatten", "result": result})
            return json.dumps(result or {"status": "no_position"})
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    if name == "cancel_order":
        if ctx.paper or ctx.client is None:
            return json.dumps({"status": "skipped", "reason": "paper mode or no client"})
        try:
            result = ctx.client.cancel_order(arguments["order_id"])
            ctx.actions.append({"action": "cancel", "result": result})
            return json.dumps(result)
        except Exception as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"error": f"unknown tool {name}"})
