"""Drive watcher/detector through a recorded scoreline and invoke agents paper-only."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from kalshi_bot.agents.orchestrator import day_start_ts, handle_event
from kalshi_bot.config import Settings
from kalshi_bot.learning.brief import compile_brief
from kalshi_bot.learning.playbook_version import ensure_playbook_v1
from kalshi_bot.learning.reflect import reflect_game
from kalshi_bot.limits import enforce_loss_cap, ensure_default_limits, session_pnl
from kalshi_bot.models import MatchState
from kalshi_bot.rem import remaining_goals
from kalshi_bot.store import Store
from kalshi_bot.watcher.detector import detect_events

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIRS = [
    REPO_ROOT / "data" / "replays",
    REPO_ROOT / "tests" / "fixtures",
]
PHASE0_CANDIDATES = [
    REPO_ROOT / "data" / "phase0-out" / "enriched.json",
    Path("/cursor/stores/bc-cb51f061-97d4-4279-b58f-3f609408d29d/internal/phase0-out/enriched.json"),
]


def _normalize_fixture(raw: dict[str, Any], source_id: str, source: str) -> dict[str, Any]:
    game = dict(raw.get("game") or {})
    if not game.get("id"):
        game["id"] = f"REPLAY-{source_id.upper().replace(' ', '-')[:24]}"
    if not str(game["id"]).startswith("REPLAY-"):
        game["id"] = f"REPLAY-{game['id']}"
    return {
        "id": raw.get("id") or source_id,
        "label": raw.get("label") or f"{game.get('home_team')} vs {game.get('away_team')}",
        "source": raw.get("source") or source,
        "game": game,
        "markets": list(raw.get("markets") or []),
        "ticks": list(raw.get("ticks") or []),
    }


def load_fixture_file(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if "ticks" not in raw and "game" not in raw:
        raise ValueError(f"{path} is not a replay fixture")
    return _normalize_fixture(raw, path.stem, "recorded")


def list_recorded_fixtures() -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for folder in FIXTURE_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                fixture = load_fixture_file(path)
            except Exception:
                continue
            if fixture["id"] in seen:
                continue
            seen.add(fixture["id"])
            out.append(
                {
                    "id": fixture["id"],
                    "label": fixture["label"],
                    "source": "recorded",
                    "path": str(path),
                    "home_team": fixture["game"].get("home_team"),
                    "away_team": fixture["game"].get("away_team"),
                    "league": fixture["game"].get("league"),
                }
            )
    return out


def _phase0_paths() -> list[Path]:
    return [p for p in PHASE0_CANDIDATES if p.is_file()]


def list_phase0_matches(limit: int = 40) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in _phase0_paths():
        try:
            data = json.loads(path.read_text())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Phase 0 read failed %s: %s", path, exc)
            continue
        for fill in data.get("fills") or []:
            if fill.get("role") != "buy_no":
                continue
            ticker = fill.get("ticker")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            rows.append(
                {
                    "id": f"phase0:{ticker}",
                    "label": (
                        f"{fill.get('home') or '?'} vs {fill.get('away') or '?'} · "
                        f"{fill.get('kickoff_utc') or fill.get('created_time') or ''} · {ticker}"
                    ),
                    "source": "phase0",
                    "path": str(path),
                    "ticker": ticker,
                    "home_team": fill.get("home"),
                    "away_team": fill.get("away"),
                    "league": fill.get("league"),
                    "date": (fill.get("kickoff_utc") or "")[:10],
                }
            )
            if len(rows) >= limit:
                return rows
    return rows


def list_fixtures() -> list[dict[str, Any]]:
    return list_recorded_fixtures() + list_phase0_matches()


def fixture_from_phase0(ticker: str, path: Optional[Path] = None) -> dict[str, Any]:
    paths = [path] if path else _phase0_paths()
    fill = None
    for candidate in paths:
        data = json.loads(candidate.read_text())
        for row in data.get("fills") or []:
            if row.get("ticker") == ticker:
                fill = row
                break
        if fill:
            break
    if not fill:
        raise ValueError(f"No Phase 0 fill for {ticker}")

    strike = fill.get("over_line") or ((fill.get("strike_n") or 1) - 0.5)
    goals = [float(g) for g in (fill.get("goal_minutes") or [])]
    final = fill.get("final_score") or f"{fill.get('score_home') or 0}-{fill.get('score_away') or 0}"
    try:
        fh, fa = [int(x) for x in str(final).replace(" ", "").split("-")[:2]]
    except ValueError:
        fh = int(fill.get("score_home") or 0)
        fa = int(fill.get("score_away") or 0)

    ticks: list[dict[str, Any]] = []
    h = a = 0
    scored = 0

    def quote(minute: int) -> dict[str, Any]:
        px = int(round((fill.get("no_price") or 0.86) * 100)) or 86
        if minute < 45:
            px = max(50, px - 10)
        return {"no_bid": max(1, px - 2), "no_ask": min(99, px)}

    ticker_key = fill["ticker"]
    ticks.append(
        {
            "home_goals": 0,
            "away_goals": 0,
            "minute": 1,
            "phase": "first_half",
            "red_cards": 0,
            "quotes": {ticker_key: quote(1)},
        }
    )
    for gm in goals:
        scored += 1
        if scored <= fh:
            h += 1
        else:
            a += 1
        minute = int(gm)
        phase = "first_half" if minute < 45 else "second_half"
        ticks.append(
            {
                "home_goals": h,
                "away_goals": a,
                "minute": minute,
                "phase": phase,
                "red_cards": 0,
                "quotes": {ticker_key: quote(minute)},
            }
        )
        if not fill.get("is_1h") and minute < 45 < (goals[goals.index(gm) + 1] if goals.index(gm) + 1 < len(goals) else 90):
            ticks.append(
                {
                    "home_goals": h,
                    "away_goals": a,
                    "minute": 45,
                    "phase": "half_time",
                    "red_cards": 0,
                    "quotes": {ticker_key: quote(45)},
                }
            )
            ticks.append(
                {
                    "home_goals": h,
                    "away_goals": a,
                    "minute": 46,
                    "phase": "second_half",
                    "red_cards": 0,
                    "quotes": {ticker_key: quote(46)},
                }
            )

    if not fill.get("is_1h") and not any(t["phase"] == "half_time" for t in ticks):
        ticks.append(
            {
                "home_goals": h,
                "away_goals": a,
                "minute": 45,
                "phase": "half_time",
                "red_cards": 0,
                "quotes": {ticker_key: quote(45)},
            }
        )
        ticks.append(
            {
                "home_goals": h,
                "away_goals": a,
                "minute": 46,
                "phase": "second_half",
                "red_cards": 0,
                "quotes": {ticker_key: quote(46)},
            }
        )
    ticks.append(
        {
            "home_goals": fh,
            "away_goals": fa,
            "minute": 45 if fill.get("is_1h") else 90,
            "phase": "full_time",
            "red_cards": 0,
            "quotes": {ticker_key: quote(90)},
        }
    )

    slug = ticker.replace("-", "")[-18:]
    return _normalize_fixture(
        {
            "id": f"phase0-{slug}",
            "label": f"{fill.get('home')} vs {fill.get('away')} · Phase 0 {ticker}",
            "source": "phase0",
            "game": {
                "id": f"REPLAY-{slug}",
                "kalshi_event_ticker": ticker.rsplit("-", 1)[0] if "-" in ticker else ticker,
                "home_team": fill.get("home") or "Home",
                "away_team": fill.get("away") or "Away",
                "league": fill.get("league") or "unknown",
                "league_tier": fill.get("tier") or 3,
                "kickoff_ts": 0,
            },
            "markets": [
                {
                    "ticker": ticker,
                    "series_ticker": fill.get("series"),
                    "strike": strike,
                    "title": fill.get("event_title") or ticker,
                }
            ],
            "ticks": ticks,
        },
        f"phase0-{slug}",
        "phase0",
    )


def resolve_fixture(
    *,
    fixture_id: Optional[str] = None,
    ticker: Optional[str] = None,
    date: Optional[str] = None,
    path: Optional[str] = None,
) -> dict[str, Any]:
    if path:
        return load_fixture_file(Path(path))
    if fixture_id and fixture_id.startswith("phase0:"):
        return fixture_from_phase0(fixture_id.split(":", 1)[1])
    if ticker:
        try:
            return fixture_from_phase0(ticker)
        except ValueError:
            for item in list_recorded_fixtures():
                raw = load_fixture_file(Path(item["path"]))
                if any(m.get("ticker") == ticker for m in raw["markets"]):
                    return raw
            raise
    if fixture_id:
        for item in list_recorded_fixtures():
            if item["id"] == fixture_id:
                return load_fixture_file(Path(item["path"]))
        if date:
            for item in list_phase0_matches(limit=200):
                if item.get("date") == date:
                    return fixture_from_phase0(item["ticker"])
        raise ValueError(f"Unknown fixture {fixture_id}")
    if date:
        for item in list_phase0_matches(limit=200):
            if item.get("date") == date:
                return fixture_from_phase0(item["ticker"])
        raise ValueError(f"No Phase 0 match on {date}")
    recorded = list_recorded_fixtures()
    if not recorded:
        raise ValueError("No recorded fixtures found")
    return load_fixture_file(Path(recorded[0]["path"]))


def replay_fixture(
    store: Store,
    fixture: dict[str, Any],
    settings: Optional[Settings] = None,
    *,
    learn: bool = True,
) -> dict[str, Any]:
    """Paper-only: detector ticks → Pundit + Kalshi on each material event."""
    settings = settings or Settings()
    store.set_paper(True)
    ensure_default_limits(store)
    ensure_playbook_v1(store)

    game = dict(fixture["game"])
    gid = game["id"]
    store.clear_game_journal(gid)
    store.upsert_game(
        {
            **game,
            "status": "replay",
            "home_goals": 0,
            "away_goals": 0,
            "minute": 0,
            "phase": "upcoming",
        }
    )
    for market in fixture["markets"]:
        store.upsert_market({**market, "game_id": gid})
    compile_brief(store, store.get_game(gid) or game, phase="kickoff")

    previous: Optional[MatchState] = None
    fired: list[str] = []
    for tick in fixture["ticks"]:
        quotes = tick.get("quotes") or {}
        current = MatchState(
            home_goals=int(tick.get("home_goals") or 0),
            away_goals=int(tick.get("away_goals") or 0),
            minute=int(tick.get("minute") or 0),
            phase=tick.get("phase") or "unknown",
            red_cards=int(tick.get("red_cards") or 0),
            source="replay",
        )
        for market in store.markets_for_game(gid):
            q = quotes.get(market["ticker"]) or {}
            rem = None
            if market.get("strike") is not None:
                rem = remaining_goals(float(market["strike"]), current.total_goals)
            store.upsert_market({**market, **q, "rem": rem, "game_id": gid})
        store.update_game_state(
            gid,
            home_goals=current.home_goals,
            away_goals=current.away_goals,
            minute=current.minute,
            phase=current.phase,
            status="replay",
        )
        for event in detect_events(previous, current):
            if event.event_type in {"half_time", "second_half_start"}:
                compile_brief(store, store.get_game(gid) or game, phase=event.event_type)
            event_id = store.add_event(gid, event.event_type, event.minute, event.payload)
            fired.append(event.event_type)
            payload = {
                "event": {"id": event_id, "event_type": event.event_type, "minute": event.minute},
                "state": current.as_dict(),
                "prior_state": previous.as_dict() if previous else None,
                "markets": store.markets_for_game(gid),
                "game": store.get_game(gid),
            }
            handle_event(
                settings,
                store,
                None,
                store.get_game(gid) or game,
                {"id": event_id, "event_type": event.event_type, "minute": event.minute},
                payload,
            )
            enforce_loss_cap(store, day_start_ts())
        previous = current

    store.update_game_state(gid, status="finished", phase="full_time")
    if learn:
        reflect_game(store, gid, settings)
    start = day_start_ts()
    pnl = session_pnl(store, start)
    decisions = store.decisions_for_game(gid)
    return {
        "game": store.get_game(gid),
        "events": store.events_for_game(gid),
        "decisions": decisions,
        "orders": store.orders_for_game(gid),
        "positions": store.positions_for_game(gid),
        "fired": fired,
        "pnl": pnl,
        "paper": True,
    }
