"""Discover Kalshi soccer totals kicking off in the next 6 hours."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from kalshi_bot.feeds import matcher
from kalshi_bot.kalshi.rest import KalshiClient, is_total_market, parse_strike
from kalshi_bot.playbook import league_tier
from kalshi_bot.store import Store

logger = logging.getLogger(__name__)


def _parse_ts(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = int(value)
        return ts // 1000 if ts > 10_000_000_000 else ts
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def infer_league(market: dict[str, Any]) -> str:
    series = (market.get("series_ticker") or market.get("ticker") or "").upper()
    mapping = (
        ("KXEPL", "premier_league"),
        ("KXLALIGA", "la_liga"),
        ("KXBUNDESLIGA", "bundesliga"),
        ("KXLIGUE1", "ligue_1"),
        ("KXSERIEA", "serie_a"),
        ("KXUCL", "ucl"),
        ("KXUEL", "uel"),
        ("KXMLS", "mls"),
        ("KXEFLA", "championship"),
        ("KXLIGAMX", "liga_mx"),
    )
    for prefix, league in mapping:
        if series.startswith(prefix):
            return league
    return "unknown"


def infer_teams(market: dict[str, Any]) -> tuple[str, str]:
    title = market.get("title") or market.get("event_title") or ""
    home, away = matcher.parse_teams_from_title(title)
    if away:
        return home, away
    ticker = market.get("ticker") or ""
    parts = ticker.split("-")
    if len(parts) >= 2:
        token = parts[1]
        letters = re.sub(r"[^A-Z]", "", token[7:] if len(token) > 7 else token)
        if len(letters) >= 6:
            mid = len(letters) // 2
            return letters[:mid], letters[mid:]
    return title or ticker, ""


def game_id_for(market: dict[str, Any]) -> str:
    if market.get("event_ticker"):
        return market["event_ticker"]
    ticker = market.get("ticker") or ""
    parts = ticker.split("-")
    return parts[1] if len(parts) >= 2 else ticker


def discover(store: Store, client: KalshiClient, horizon_hours: int = 6) -> list[dict[str, Any]]:
    now = int(time.time())
    until = now + horizon_hours * 3600
    markets = [m for m in client.soccer_total_markets() if is_total_market(m)]
    fixtures_cache: dict[str, list[dict[str, Any]]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for market in markets:
        kickoff = _parse_ts(
            market.get("expected_expiration_time")
            or market.get("close_time")
            or market.get("open_time")
            or market.get("expiration_time")
        )
        event_open = _parse_ts(market.get("event_open_time") or market.get("open_time"))
        kickoff = event_open or kickoff
        if kickoff is None or kickoff < now - 3600 or kickoff > until:
            continue
        gid = game_id_for(market)
        grouped.setdefault(gid, []).append({**market, "_kickoff": kickoff})

    saved = []
    for gid, group in grouped.items():
        sample = group[0]
        home, away = infer_teams(sample)
        league = infer_league(sample)
        kickoff = sample["_kickoff"]
        day_key = datetime.fromtimestamp(kickoff, tz=timezone.utc).strftime("%Y%m%d")
        if day_key not in fixtures_cache:
            fixtures_cache[day_key] = matcher.gather_fixtures(kickoff)
        fixture = matcher.match_fixture(home, away, kickoff, fixtures_cache[day_key])
        existing = store.get_game(gid)
        game = {
            "id": gid,
            "kalshi_event_ticker": sample.get("event_ticker") or gid,
            "home_team": (fixture or {}).get("home") or home,
            "away_team": (fixture or {}).get("away") or away,
            "league": (fixture or {}).get("league") or league,
            "league_tier": league_tier((fixture or {}).get("league") or league),
            "kickoff_ts": kickoff,
            "status": existing["status"] if existing and existing["status"] == "live" else "upcoming",
            "fotmob_id": (fixture or {}).get("id") if fixture and not (fixture.get("league_slug")) else (existing or {}).get("fotmob_id"),
            "espn_id": (fixture or {}).get("id") if fixture and fixture.get("league_slug") else (existing or {}).get("espn_id"),
            "home_goals": (existing or {}).get("home_goals", 0),
            "away_goals": (existing or {}).get("away_goals", 0),
            "minute": (existing or {}).get("minute", 0),
            "phase": (existing or {}).get("phase", "upcoming"),
            "red_cards": (existing or {}).get("red_cards", 0),
            "prematch_json": (existing or {}).get("prematch_json"),
        }
        store.upsert_game(game)
        for market in group:
            strike = parse_strike(market)
            store.upsert_market(
                {
                    "ticker": market["ticker"],
                    "game_id": gid,
                    "series_ticker": market.get("series_ticker"),
                    "strike": strike,
                    "title": market.get("title") or market.get("yes_sub_title") or market.get("subtitle"),
                    "no_bid": market.get("no_bid"),
                    "no_ask": market.get("no_ask"),
                    "yes_bid": market.get("yes_bid"),
                    "yes_ask": market.get("yes_ask"),
                }
            )
        saved.append(store.get_game(gid))
        logger.info(
            "Discovered %s vs %s kickoff=%s markets=%s matched=%s",
            game["home_team"],
            game["away_team"],
            kickoff,
            len(group),
            bool(fixture),
        )
    return saved
