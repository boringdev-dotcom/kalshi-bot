"""Per-game 15s live-state poller."""

from __future__ import annotations

import logging
from typing import Optional

from kalshi_bot.feeds import espn, fotmob
from kalshi_bot.kalshi.rest import KalshiClient, best_no_ask, best_no_bid, no_depth
from kalshi_bot.models import MatchState
from kalshi_bot.rem import remaining_goals
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)


def fetch_live_state(game: dict) -> Optional[MatchState]:
    if game.get("fotmob_id"):
        details = fotmob.match_details(str(game["fotmob_id"]))
        if details:
            return fotmob.live_state(details)
    if game.get("espn_id"):
        summary = espn.fetch_event(str(game["espn_id"]))
        if summary:
            try:
                return espn.live_state_from_summary(summary)
            except Exception:
                logger.debug("ESPN summary parse failed for %s", game["id"], exc_info=True)
    return None


def refresh_quotes(store: Store, client: Optional[KalshiClient], game: dict, state: MatchState) -> list[dict]:
    quotes = []
    for market in store.markets_for_game(game["id"]):
        book = None
        live = dict(market)
        if client:
            try:
                raw = client.get_market(market["ticker"])
                book = client.get_orderbook(market["ticker"], depth=5)
                live["no_bid"] = best_no_bid(raw, book)
                live["no_ask"] = best_no_ask(raw, book)
                live["yes_bid"] = raw.get("yes_bid")
                live["yes_ask"] = raw.get("yes_ask")
                live["no_depth"] = no_depth(book)
            except Exception as exc:
                logger.warning("Quote refresh failed for %s: %s", market["ticker"], exc)
        strike = market.get("strike")
        if strike is not None:
            live["rem"] = remaining_goals(float(strike), state.total_goals)
        live["game_id"] = game["id"]
        store.upsert_market(live)
        quotes.append(live)
    return quotes
