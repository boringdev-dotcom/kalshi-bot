"""Orders that Kalshi only partly fills: they work through the book and go back for the rest, and
whatever still did not trade stays open and visible, never quietly dropped (the Madrid sale)."""

from __future__ import annotations

import asyncio
import json

import httpx

from courtside.agent.policy import sell_floor
from courtside.kalshi.client import offers, walk
from courtside.soccer import model
from tests.test_core import make_engine
from tests.test_game_spreads import spread_game
from tests.test_kalshi_shards import client
from tests.test_soccer import a_match, make_desk, with_markets


def exchange(fills: list[tuple[str, str]]):
    """Kalshi answering each order with the next (fill_count, average YES price) from `fills`."""
    orders: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        if request.url.path.endswith("/portfolio/events/orders"):
            orders.append(body)
            count, avg = fills.pop(0) if fills else ("0", None)
            return httpx.Response(201, json={"order_id": f"o{len(orders)}", "fill_count": count, "average_fill_price": avg,
                                             "average_fee_paid": "0.0100"})
        return httpx.Response(404, json={})

    return handler, orders


def test_a_sale_goes_back_for_what_is_left_until_it_is_all_sold():
    # Selling 223 NO with buyers down to 65c: 78.57 go first, the rest a moment later.
    handler, orders = exchange([("78.57", "0.2300"), ("144.43", "0.2500")])
    fill = asyncio.run(client(handler).fill_order("KXUCLTOTAL-X-6", "under", "sell", 223, 65, pause=0))
    assert [o["count"] for o in orders] == ["223.00", "144.43"]
    assert all(o["price"] == "0.3500" and o["reduce_only"] and o["time_in_force"] == "immediate_or_cancel" for o in orders)
    assert fill["filled"] == 223 and fill["left"] == 0 and fill["asked"] == 223
    assert abs(fill["price"] - (78.57 * 77 + 144.43 * 75) / 223) < 1e-6


def test_what_never_fills_is_reported_not_hidden():
    handler, orders = exchange([("40.00", "0.4100")])
    fill = asyncio.run(client(handler).fill_order("KXNBATOTAL-X-220", "over", "sell", 100, 38, pause=0))
    assert len(orders) == 3  # it tried, and tried again
    assert fill["filled"] == 40 and fill["left"] == 60 and round(fill["price"]) == 41


def test_sales_walk_down_the_bids_only_so_far():
    assert sell_floor(77) == 65  # 15% below
    assert sell_floor(50) == 42
    assert sell_floor(20) == 17  # at least 3c
    assert sell_floor(3) == 1


def test_the_book_is_read_from_the_side_you_trade():
    book = {"yes": [(40.0, 10.0), (39.0, 50.0)], "no": [(58.0, 5.0), (57.0, 100.0)]}
    assert offers(book, "over", "sell") == [(40.0, 10.0), (39.0, 50.0)]  # YES bids
    assert offers(book, "over", "buy") == [(42.0, 5.0), (43.0, 100.0)]  # YES asks = 100 - NO bids
    plan = walk(offers(book, "over", "buy"), 30)
    assert plan["contracts"] == 30 and plan["worst"] == 43.0 and abs(plan["avg"] - (5 * 42 + 25 * 43) / 30) < 1e-9


class PartFill:
    """Kalshi filling only part of each order."""

    def __init__(self, filled: float, price: float):
        self.filled, self.price, self.calls = filled, price, []

    async def fill_order(self, ticker, side, action, contracts, limit, **kw):
        self.calls.append((ticker, side, action, contracts, limit))
        got = min(self.filled, contracts)
        left = round(contracts - got, 2)
        return {"order_id": "o1", "filled": got, "price": self.price, "fees": 0.5, "asked": contracts, "left": left}


def test_a_soccer_sale_that_only_part_fills_keeps_the_rest_open_and_watched():
    desk, engine = make_desk()
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    over = next(x for x in m.markets if x.kind == "total" and x.strike == 2.5)
    pid = desk.db.insert("soccer_positions", {
        "match_id": m.id, "match_label": m.label, "league": m.league, "ticker": over.ticker, "segment": "match",
        "kind": "total", "outcome": "over", "strike": 2.5, "side": "no", "label": "Under 2.5 goals", "contracts": 223,
        "entry_price": 89, "cost": 199.0, "fees": 0.53, "mode": "live", "status": "open", "watch": True,
        "opened_at": "2026-11-24T20:57:55+00:00",
    })
    engine.settings["trading_mode"] = "live"
    engine.kalshi = PartFill(78.57, 77)
    trade = asyncio.run(desk.close(pid))
    assert trade["contracts"] == 78.57 and trade["left"] == 144.43
    assert engine.kalshi.calls[0][4] == sell_floor(over.bid("no"))  # walked down the bids, not one price
    still = desk.positions_api()
    assert len(still) == 1 and still[0]["id"] == pid and still[0]["contracts"] == 144.43 and still[0]["watch"] is True
    assert abs(still[0]["cost"] + trade["cost"] - 199.0) < 0.011


def test_a_short_buy_says_how_many_it_got():
    desk, engine = make_desk()
    m = with_markets(a_match(lam_home=1.6, lam_away=1.1))
    model.price(m)
    desk.matches, desk.by_id = [m], {m.id: m}
    engine.settings["trading_mode"] = "live"
    home = next(x for x in m.markets if x.kind == "winner" and x.outcome == "home")
    engine.kalshi = PartFill(40, 45)
    engine.kalshi.can_sign = True
    pos = asyncio.run(desk.order(home.ticker, "yes", 220, 47))
    assert pos["contracts"] == 40 and pos["asked"] == 220


def test_an_nba_sale_that_only_part_fills_keeps_the_rest_open():
    engine = make_engine()
    asyncio.run(engine.update_settings({"agent_enabled": False}))
    game = spread_game(home=50, away=48, state="live", period=2, clock=300.0)
    game.simulated = False
    for r in game.spreads:
        r.yes_ask, r.yes_bid, r.no_bid, r.p_under = 50, 48, 50, 0.5
    engine.games, engine.by_id = [game], {game.id: game}
    engine.settings["trading_mode"] = "live"
    engine.kalshi = PartFill(100, 50)
    rung = game.spreads[0]
    pos = asyncio.run(engine.manual_order(rung.ticker, "over", 100, 52, watch=True))
    engine.kalshi = PartFill(30, 47)
    trade = asyncio.run(engine.close_position(pos["id"]))
    assert trade["contracts"] == 30 and trade["left"] == 70
    still = engine.positions_api()
    assert [(p["id"], p["contracts"], p["watch"]) for p in still] == [(pos["id"], 70, True)]


class Holdings:
    """What Kalshi reports holding and filling, for checking positions sold outside Courtside."""

    def __init__(self, held: dict, fills: list):
        self.held, self._fills = held, fills

    async def positions(self):
        return self.held

    async def fills(self, ticker, limit=100):
        return [f for f in self._fills if f.get("ticker", ticker) == ticker]


def nba_live_bet(engine, game, rung, side: str, contracts: float, opened_at: str) -> int:
    return engine.db.insert("positions", {
        "game_id": game.id, "game_label": game.label, "ticker": rung.ticker, "strike": rung.strike, "side": side,
        "segment": rung.segment, "kind": rung.kind, "team": rung.team, "label": rung.position_label(side),
        "contracts": contracts, "entry_price": 60, "cost": round(contracts * 0.6 + 0.5, 2), "fees": 0.5,
        "opened_at": opened_at, "opened_by": "user", "mode": "live", "simulated": False, "p_win_entry": 0.6,
        "context": {}, "memory_ids": [], "watch": True,
    })


def test_an_nba_bet_sold_on_kalshis_own_app_is_closed_at_that_price():
    engine = make_engine()
    game = spread_game(home=50, away=48, state="live", period=3, clock=300.0)
    game.simulated = False
    engine.games, engine.by_id = [game], {game.id: game}
    engine.settings["trading_mode"] = "live"
    rung = game.spreads[0]
    pid = nba_live_bet(engine, game, rung, "under", 45, "2026-11-24T23:10:00+00:00")
    engine.kalshi = Holdings({}, [
        {"count": 45, "yes_price": 30, "no_price": 70, "fee": 0.66, "created_time": "2026-11-24T23:40:00Z"},  # your sale
        {"count": 45, "yes_price": 40, "no_price": 60, "fee": 0.76, "created_time": "2026-11-24T23:09:58Z"},  # the buy
    ])
    closed = asyncio.run(engine.sync_with_kalshi())
    assert [t["id"] for t in closed] == [pid]
    assert closed[0]["exit_price"] == 70 and closed[0]["exit_reason"] == "sold_on_kalshi"
    assert engine.positions_api() == []


def test_nba_sync_leaves_held_settled_and_part_sold_bets_right():
    engine = make_engine()
    game = spread_game(home=50, away=48, state="live", period=3, clock=300.0)
    game.simulated = False
    engine.games, engine.by_id = [game], {game.id: game}
    engine.settings["trading_mode"] = "live"
    held, gone, part = game.spreads[0], game.spreads[1], game.spreads[2]
    a = nba_live_bet(engine, game, held, "under", 45, "2026-11-24T23:10:00+00:00")
    nba_live_bet(engine, game, gone, "over", 10, "2026-11-24T23:10:00+00:00")
    c = nba_live_bet(engine, game, part, "over", 100, "2026-11-24T23:10:00+00:00")
    engine.kalshi = Holdings({held.ticker: -45.0, part.ticker: 60.0}, [
        # Gone with no sale on record: settled, so settlement handles it.
        {"ticker": gone.ticker, "count": 10, "yes_price": 60, "no_price": 40, "fee": 0.1, "created_time": "2026-11-24T23:09:59Z"},
        # 40 of the 100 sold on Kalshi.
        {"ticker": part.ticker, "count": 40, "yes_price": 75, "no_price": 25, "fee": 0.4, "created_time": "2026-11-24T23:30:00Z"},
    ])
    closed = asyncio.run(engine.sync_with_kalshi())
    assert [(t["contracts"], t["exit_price"]) for t in closed] == [(40, 75)]
    left = {p["id"]: p["contracts"] for p in engine.positions_api()}
    assert left[a] == 45 and left[c] == 60 and len(left) == 3
