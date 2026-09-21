#!/usr/bin/env python3
"""Import Kalshi fills/orders/settlements and match soccer totals to scorelines.

Phase 0 helper. Writes a local JSON/markdown report. Does not place orders.

Usage:
    uv run python scripts/import_history.py --out data/history_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kalshi_bot.config import Settings
from kalshi_bot.feeds import espn, fotmob, matcher
from kalshi_bot.kalshi.rest import KalshiClient, is_total_market, parse_strike
from kalshi_bot.rem import remaining_goals

logger = logging.getLogger(__name__)


def paginate(fetch, key: str, limit: int = 200) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = None
    while True:
        page = fetch(limit=limit, cursor=cursor)
        batch = page.get(key) or []
        rows.extend(batch)
        cursor = page.get("cursor")
        if not cursor or not batch:
            break
    return rows


def parse_fill_ts(fill: dict[str, Any]) -> Optional[int]:
    raw = fill.get("created_time") or fill.get("ts")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = int(raw)
        return ts // 1000 if ts > 10_000_000_000 else ts
    try:
        return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def soccer_total_fill(fill: dict[str, Any]) -> bool:
    ticker = (fill.get("ticker") or fill.get("market_ticker") or "").upper()
    return "TOTAL" in ticker and any(
        token in ticker for token in ("EPL", "LALIGA", "BUNDES", "LIGUE", "SERIE", "UCL", "MLS", "SOCCER", "UEL")
    )


def infer_minute(kickoff_ts: Optional[int], fill_ts: Optional[int]) -> Optional[int]:
    if not kickoff_ts or not fill_ts:
        return None
    return max(0, int((fill_ts - kickoff_ts) / 60))


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Kalshi soccer totals history")
    parser.add_argument("--out", default="data/history_report.md")
    parser.add_argument("--json-out", default="data/history_report.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings()
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_pem:
        raise SystemExit("KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PEM are required")

    client = KalshiClient(
        settings.kalshi_api_key_id,
        settings.kalshi_private_key_pem,
        settings.api_base_url(),
    )
    fills = [f for f in paginate(client.get_fills, "fills") if soccer_total_fill(f)]
    orders = paginate(client.get_orders, "orders")
    settlements = paginate(client.get_settlements, "settlements")
    logger.info("Loaded %s soccer-total fills, %s orders, %s settlements", len(fills), len(orders), len(settlements))

    rows = []
    fixtures_by_day: dict[str, list[dict[str, Any]]] = {}
    for fill in fills:
        ticker = fill.get("ticker") or fill.get("market_ticker")
        try:
            market = client.get_market(ticker)
        except Exception as exc:
            logger.warning("market %s: %s", ticker, exc)
            market = {"ticker": ticker}
        if market and not is_total_market(market):
            continue
        strike = parse_strike(market or {})
        title = (market or {}).get("title") or ticker
        home, away = matcher.parse_teams_from_title(title)
        fill_ts = parse_fill_ts(fill)
        kickoff = None
        for key in ("open_time", "close_time", "expiration_time"):
            raw = (market or {}).get(key)
            if raw:
                try:
                    kickoff = int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())
                    break
                except ValueError:
                    pass
        fixture = None
        if kickoff:
            day = datetime.fromtimestamp(kickoff, tz=timezone.utc).strftime("%Y%m%d")
            if day not in fixtures_by_day:
                fixtures_by_day[day] = matcher.gather_fixtures(kickoff)
            fixture = matcher.match_fixture(home, away, kickoff, fixtures_by_day[day])
        goals_at_fill = None
        if fixture and fixture.get("id") and not fixture.get("league_slug"):
            details = fotmob.match_details(str(fixture["id"]))
            if details:
                # Best-effort: use final score if we cannot reconstruct timeline.
                state = fotmob.live_state(details)
                goals_at_fill = state.total_goals
        rem = remaining_goals(strike, goals_at_fill) if strike is not None and goals_at_fill is not None else None
        price = fill.get("no_price") or fill.get("yes_price") or fill.get("price")
        rows.append(
            {
                "ticker": ticker,
                "title": title,
                "strike": strike,
                "side": fill.get("side") or fill.get("taker_side"),
                "count": fill.get("count") or fill.get("size"),
                "price": price,
                "fill_ts": fill_ts,
                "minute": infer_minute(kickoff or (fixture or {}).get("kickoff_ts"), fill_ts),
                "rem": rem,
                "league": (fixture or {}).get("league"),
                "matched": bool(fixture),
            }
        )

    minutes = Counter(r["minute"] for r in rows if r["minute"] is not None)
    rem_bucket = Counter(round(r["rem"], 1) for r in rows if r["rem"] is not None)
    report = {
        "fills": len(fills),
        "soccer_total_rows": len(rows),
        "matched_fixtures": sum(1 for r in rows if r["matched"]),
        "orders": len(orders),
        "settlements": len(settlements),
        "entry_minute_hist": dict(sorted(minutes.items())),
        "rem_hist": {str(k): v for k, v in sorted(rem_bucket.items())},
        "rows": rows,
        "proposed_playbook": {
            "note": "Conservative placeholders until this report is reviewed",
            "entry_min_minute": 70,
            "entry_max_rem": 1.0,
            "entry_no_price_band": [78, 93],
            "stop_cents": 8,
            "flatten_on_goal": True,
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.json_out)
    json_path.write_text(json.dumps(report, indent=2))
    lines = [
        "# Kalshi soccer totals history",
        "",
        f"- Fills scanned: {len(fills)}",
        f"- Soccer total rows: {len(rows)}",
        f"- Matched fixtures: {report['matched_fixtures']}",
        f"- Orders: {len(orders)}",
        f"- Settlements: {len(settlements)}",
        "",
        "## Entry minute histogram",
        "",
        "```",
        json.dumps(report["entry_minute_hist"], indent=2),
        "```",
        "",
        "## rem histogram",
        "",
        "```",
        json.dumps(report["rem_hist"], indent=2),
        "```",
        "",
        "## Proposed playbook (review before going live)",
        "",
        json.dumps(report["proposed_playbook"], indent=2),
        "",
    ]
    out.write_text("\n".join(lines))
    logger.info("Wrote %s and %s", out, json_path)


if __name__ == "__main__":
    main()
