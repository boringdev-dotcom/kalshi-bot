"""Real-world data: ESPN scores, Kalshi NBA totals ladders, FanDuel odds.

Each source refreshes on its own cadence and fails independently; a source
that is down leaves the last good data in place and reports itself unhealthy.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from ..config import Config
from ..domain import FanDuelOdds, Game, Rung, Team, now_iso
from ..kalshi.client import KalshiClient, cents, quarter_series
from ..model.totals import implied_total
from .patterns import ESPN_SUMMARY, build_context, parse_espn

log = logging.getLogger(__name__)

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
EASTERN = ZoneInfo("America/New_York")

# ESPN abbreviations that differ from the three-letter codes in Kalshi tickers.
ABBR_FIX = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}


def _status(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail, "updated_at": now_iso()}


def _clock_seconds(display: str) -> float:
    try:
        if ":" in display:
            m, s = display.split(":")
            return int(m) * 60 + float(s)
        return float(display)
    except ValueError:
        return 0.0


def _nickname(name: str) -> str:
    return name.strip().split(" ")[-1].lower()


def _ticker_date(start_iso: str) -> str:
    """ESPN start time -> the 'YYMONDD' fragment Kalshi puts in event tickers."""
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(EASTERN)
    except ValueError:
        return ""
    return dt.strftime("%y%b%d").upper()


class LiveFeed:
    def __init__(self, cfg: Config, kalshi: KalshiClient):
        self.cfg = cfg
        self.kalshi = kalshi
        self.games: dict[str, Game] = {}
        self.locations: dict[str, tuple[str, str]] = {}  # game id -> (away city, home city)
        self.status = {
            "scores": _status(False, "Waiting for first ESPN update"),
            "kalshi": _status(False, "Waiting for first Kalshi update"),
            "fanduel": _status(
                False,
                "Waiting for first FanDuel update"
                if cfg.has_odds
                else "ODDS_API_KEY not set. Showing ESPN's pregame consensus line instead.",
            ),
        }
        self._http = httpx.AsyncClient(timeout=10.0)
        self._next = {"scores": 0.0, "kalshi": 0.0, "fanduel": 0.0}
        self._espn_lines: dict[str, FanDuelOdds] = {}
        self._next_quarter: dict[tuple[int, str], float] = {}
        self._next_patterns: dict[str, float] = {}
        self._odds_markets = "totals,spreads,h2h"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def refresh(self) -> list[Game]:
        now = time.monotonic()
        any_live = any(g.state == "live" for g in self.games.values())
        late = any(
            g.state == "live" and (g.period >= 4 or (g.period == 3 and g.clock_seconds <= 180))
            for g in self.games.values()
        )

        if now >= self._next["scores"]:
            self._next["scores"] = now + (4 if any_live else 20)
            await self._guard("scores", self._refresh_scores)
        if now >= self._next["kalshi"]:
            self._next["kalshi"] = now + (3 if any_live else 30)
            await self._guard("kalshi", self._refresh_ladders)
        await self._refresh_quarter_markets(now, any_live)
        await self._refresh_patterns(now)
        if self.cfg.has_odds and now >= self._next["fanduel"]:
            # The Odds API bills one credit per market per request, so be frugal:
            # the full board hourly while idle, totals only while games are live,
            # and fast only once a game is deep enough for the Q4 play to matter.
            self._next["fanduel"] = now + (20 if late else 180 if any_live else 3600)
            self._odds_markets = "totals" if any_live else "totals,spreads,h2h"
            await self._guard("fanduel", self._refresh_fanduel)

        order = {"live": 0, "pre": 1, "final": 2}
        return sorted(self.games.values(), key=lambda g: (order[g.state], g.start_time))

    async def _guard(self, name: str, fn) -> None:
        try:
            detail = await fn()
            self.status[name] = _status(True, detail)
        except Exception as exc:  # a feed outage must never take the loop down
            log.warning("%s feed failed: %s", name, exc)
            self.status[name] = _status(False, f"{type(exc).__name__}: {exc}"[:200])

    # -- ESPN ---------------------------------------------------------------
    async def _refresh_scores(self) -> str:
        resp = await self._http.get(ESPN_SCOREBOARD)
        resp.raise_for_status()
        events = resp.json().get("events") or []
        seen: set[str] = set()
        for ev in events:
            comp = (ev.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            if "home" not in sides or "away" not in sides:
                continue
            gid = f"nba-{ev['id']}"
            seen.add(gid)
            game = self.games.get(gid)
            if game is None:
                game = Game(
                    id=gid,
                    home=self._team(sides["home"]),
                    away=self._team(sides["away"]),
                    start_time=ev.get("date", now_iso()),
                )
                self.games[gid] = game
                self.locations[gid] = (
                    sides["away"]["team"].get("location", ""),
                    sides["home"]["team"].get("location", ""),
                )
            game.home.score = int(sides["home"].get("score") or 0)
            game.away.score = int(sides["away"].get("score") or 0)
            period_now = int((ev.get("status") or {}).get("period") or 0)
            for team, side in ((game.home, sides["home"]), (game.away, sides["away"])):
                team.quarters = self._quarters(side, team.score, period_now)
            status = ev.get("status") or {}
            state = (status.get("type") or {}).get("state", "pre")
            game.state = {"pre": "pre", "in": "live", "post": "final"}.get(state, "pre")
            game.period = int(status.get("period") or 0)
            game.clock_seconds = float(status.get("clock") or 0.0)
            game.clock = status.get("displayClock") or "0:00"
            if game.clock_seconds == 0 and ":" in game.clock:
                game.clock_seconds = _clock_seconds(game.clock)

            odds = (comp.get("odds") or [None])[0]
            if odds and odds.get("overUnder"):
                if game.pregame_total is None:
                    game.pregame_total = float(odds["overUnder"])
                spread = odds.get("spread")
                self._espn_lines[gid] = FanDuelOdds(
                    total_line=float(odds["overUnder"]),
                    spread=float(spread) if spread is not None else None,
                    live=False,
                    source="espn",
                )
            if game.fanduel is None or game.fanduel.source == "espn":
                game.fanduel = self._espn_lines.get(gid)
        for gid in list(self.games):
            if gid not in seen:
                del self.games[gid]
        live = sum(1 for g in self.games.values() if g.state == "live")
        return f"{len(self.games)} games today, {live} live"

    # -- players, fouls and runs (ESPN game summary) ---------------------------
    async def _refresh_patterns(self, now: float) -> None:
        """Who is on the floor, fouls, runs. Fast for live games, slow before tip-off, once after."""
        due = [
            g for gid, g in self.games.items()
            if now >= self._next_patterns.get(gid, 0.0) and not (g.context or {}).get("final")
        ]
        due.sort(key=lambda g: g.state != "live")  # live games first
        for game in due[:8]:
            wait = (8 if game.period >= 3 else 15) if game.state == "live" else 600
            self._next_patterns[game.id] = now + wait
        if due:
            await asyncio.gather(*(self._load_patterns(g) for g in due[:8]))

    async def _load_patterns(self, game: Game) -> None:
        try:
            resp = await self._http.get(ESPN_SUMMARY, params={"event": game.id.removeprefix("nba-")}, timeout=6.0)
            resp.raise_for_status()
            snap = parse_espn(resp.json(), ABBR_FIX)
            game.context = build_context(game, snap)
            if game.state == "final":
                game.context["final"] = True
        except Exception as exc:  # patterns are a nice-to-have; keep the last good ones
            log.info("patterns for %s unavailable: %s", game.label, exc)

    @staticmethod
    def _quarters(side: dict[str, Any], score: int, period: int) -> list[int]:
        """Points by period from ESPN's linescore.

        Finished periods come from the linescore. The period in progress is
        taken as score minus the finished periods, because the score is the
        number ESPN updates first.
        """
        line = []
        for entry in side.get("linescores") or []:
            try:
                line.append(int(float(entry.get("value") or 0)))
            except (TypeError, ValueError):
                line.append(0)
        if period >= 1 and len(line) >= period - 1:
            done = line[: period - 1]
            return done + [max(score - sum(done), 0)]
        return line

    @staticmethod
    def _team(side: dict[str, Any]) -> Team:
        team = side.get("team") or {}
        abbr = team.get("abbreviation", "?")
        return Team(
            abbr=ABBR_FIX.get(abbr, abbr),
            name=team.get("displayName", abbr),
            color=(team.get("color") or "8b9cff").lstrip("#"),
        )

    # -- Kalshi ---------------------------------------------------------------
    async def _refresh_ladders(self) -> str:
        events = await self.kalshi.nba_total_events()
        matched = 0
        for game in self.games.values():
            event = self._match_event(game, events)
            if event is None:
                continue
            matched += 1
            game.event_ticker = event.get("event_ticker")
            rungs = []
            for m in event.get("markets") or []:
                strike = m.get("floor_strike")
                if strike is None:
                    continue
                rungs.append(
                    Rung(
                        ticker=m["ticker"],
                        strike=float(strike),
                        yes_bid=cents(m.get("yes_bid_dollars")),
                        yes_ask=cents(m.get("yes_ask_dollars")),
                        no_bid=cents(m.get("no_bid_dollars")),
                        no_ask=cents(m.get("no_ask_dollars")),
                        volume=float(m.get("volume_fp") or 0),
                        result=m.get("result") or "",
                    )
                )
            if rungs:
                game.ladder = sorted(rungs, key=lambda r: r.strike)
                if game.pregame_total is None and game.state == "pre":
                    # No sportsbook line for this game: take the market's own.
                    game.pregame_total = implied_total(game.ladder)
        return f"{matched}/{len(self.games)} games matched to Kalshi total markets"

    # -- Kalshi quarter totals and spreads -------------------------------------
    async def _refresh_quarter_markets(self, now: float, any_live: bool) -> None:
        """Eight more series (four quarters x total/spread), each on its own clock.

        The quarter being played, and the next one when a quarter is nearly
        over, refresh fast enough to trade off; the rest tick over slowly.
        """
        if not self.games:
            return
        hot: set[int] = set()
        for g in self.games.values():
            if g.state == "live" and 1 <= g.period <= 4:
                hot.add(g.period)
                if g.clock_seconds <= 150 and g.period < 4:
                    hot.add(g.period + 1)
        due = []
        for q in (1, 2, 3, 4):
            for kind in ("total", "spread"):
                if now >= self._next_quarter.get((q, kind), 0.0):
                    self._next_quarter[(q, kind)] = now + (4 if (q in hot and any_live) else 45 if any_live else 120)
                    due.append((q, kind))
        if not due:
            return
        results = await asyncio.gather(*(self.kalshi.events(quarter_series(q, k)) for q, k in due), return_exceptions=True)
        for (q, kind), events in zip(due, results):
            if isinstance(events, Exception):
                log.warning("Kalshi Q%s %s fetch failed: %s", q, kind, events)
                continue
            for game in self.games.values():
                event = self._match_event(game, events)
                if event is None:
                    continue
                rungs = [r for r in (self._quarter_rung(game, q, kind, m) for m in event.get("markets") or []) if r]
                if rungs:
                    rungs.sort(key=lambda r: (r.team != game.away.abbr, r.strike))
                    game.quarter_markets.setdefault(f"q{q}", {})[kind] = rungs

    def _quarter_rung(self, game: Game, q: int, kind: str, m: dict[str, Any]) -> Optional[Rung]:
        strike = m.get("floor_strike")
        if strike is None:
            return None
        rung = Rung(
            ticker=m["ticker"],
            strike=float(strike),
            yes_bid=cents(m.get("yes_bid_dollars")),
            yes_ask=cents(m.get("yes_ask_dollars")),
            no_bid=cents(m.get("no_bid_dollars")),
            no_ask=cents(m.get("no_ask_dollars")),
            volume=float(m.get("volume_fp") or 0),
            result=m.get("result") or "",
            segment=f"q{q}",
            kind=kind,
        )
        if kind == "spread":
            # The ticker ends in the backed team's code and the line, e.g. "-IND11".
            code = re.match(r"([A-Z]+)\d+$", m["ticker"].rsplit("-", 1)[-1])
            team = code.group(1) if code else ""
            if team not in (game.home.abbr, game.away.abbr):
                away_city, home_city = self.locations.get(game.id, ("", ""))
                text = (m.get("yes_sub_title") or m.get("title") or "").lower()
                if home_city and home_city.lower() in text:
                    team = game.home.abbr
                elif away_city and away_city.lower() in text:
                    team = game.away.abbr
                else:
                    return None  # cannot tell which side this backs: do not guess
            rung.team = team
            rung.other_team = game.away.abbr if team == game.home.abbr else game.home.abbr
        return rung

    def _match_event(self, game: Game, events: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        date = _ticker_date(game.start_time)
        away_city, home_city = self.locations.get(game.id, ("", ""))
        for ev in events:
            ticker = (ev.get("event_ticker") or "").upper()
            tail = ticker.rsplit("-", 1)[-1]
            if date and date not in tail:
                continue
            teams = tail.replace(date, "")
            if teams == game.away.abbr + game.home.abbr:
                return ev
            title = (ev.get("title") or "").lower()
            if away_city and home_city and away_city.lower() in title and home_city.lower() in title:
                return ev
        return None

    # -- FanDuel (The Odds API) -----------------------------------------------
    async def _refresh_fanduel(self) -> str:
        resp = await self._http.get(
            ODDS_URL,
            params={
                "apiKey": self.cfg.odds_api_key,
                "regions": "us",
                "bookmakers": "fanduel",
                "markets": self._odds_markets,
                "oddsFormat": "american",
            },
        )
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        by_teams = {
            (_nickname(g.away.name), _nickname(g.home.name)): g for g in self.games.values()
        }
        updated = 0
        for ev in resp.json():
            game = by_teams.get(
                (_nickname(ev.get("away_team", "")), _nickname(ev.get("home_team", "")))
            )
            book = next((b for b in ev.get("bookmakers") or [] if b.get("key") == "fanduel"), None)
            if game is None or book is None:
                continue
            odds = FanDuelOdds(live=game.state == "live", source="fanduel")
            prev = game.fanduel if (game.fanduel and game.fanduel.source == "fanduel") else None
            if prev:  # a totals-only poll must not wipe the spread and moneylines
                odds.spread, odds.home_ml, odds.away_ml = prev.spread, prev.home_ml, prev.away_ml
            odds.updated_at = book.get("last_update") or now_iso()
            for market in book.get("markets") or []:
                outcomes = {o.get("name"): o for o in market.get("outcomes") or []}
                if market.get("key") == "totals" and "Over" in outcomes:
                    odds.total_line = float(outcomes["Over"]["point"])
                    odds.over_price = int(outcomes["Over"]["price"])
                    odds.under_price = int(outcomes.get("Under", {}).get("price", 0)) or None
                elif market.get("key") == "spreads":
                    home = outcomes.get(ev.get("home_team"))
                    if home:
                        odds.spread = float(home["point"])
                elif market.get("key") == "h2h":
                    home, away = outcomes.get(ev.get("home_team")), outcomes.get(ev.get("away_team"))
                    odds.home_ml = int(home["price"]) if home else None
                    odds.away_ml = int(away["price"]) if away else None
            if odds.total_line is not None:
                game.fanduel = odds
                if game.state == "pre":
                    game.pregame_total = odds.total_line
                updated += 1
        return f"{updated} games with FanDuel lines ({remaining} API credits left)"
