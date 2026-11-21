"""Real soccer data: ESPN for fixtures, scores, events and stats; Kalshi for prices.

Each source refreshes on its own clock and fails on its own: a source that is down
leaves the last good data in place and reports itself unhealthy.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from ..domain import now_iso
from ..kalshi.client import KalshiClient, cents
from . import model
from .domain import LEAGUE_BY_KEY, LEAGUES, SERIES, League, Match, Side, SMarket
from .names import pair_score, similarity, split_title

log = logging.getLogger(__name__)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/{what}"
EASTERN = ZoneInfo("America/New_York")
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
DAYS_AHEAD = 6  # fixtures on the board: yesterday through a week out
KEEP_FINAL_HOURS = 14  # finished matches stay on the board this long after kickoff
STATS = {
    "possessionPct": "Possession %",
    "totalShots": "Shots",
    "shotsOnTarget": "On target",
    "wonCorners": "Corners",
    "foulsCommitted": "Fouls",
    "yellowCards": "Yellow cards",
    "redCards": "Red cards",
    "offsides": "Offsides",
    "saves": "Saves",
}
EVENT_KINDS = ("goal", "penalty", "own goal", "red card", "yellow card", "substitution", "halftime", "kickoff", "start 2nd half", "end regular time", "var")


def _status(ok: bool, detail: str) -> dict[str, Any]:
    return {"ok": ok, "detail": detail, "updated_at": now_iso()}


def minute_of(display: str, period: int) -> float:
    """ESPN's "67'" or "45'+2'" -> 67.0 or 47.0."""
    nums = [int(n) for n in re.findall(r"\d+", display or "")]
    if not nums:
        return 45.0 if period >= 2 else 0.0
    return float(sum(nums[:2]))


def ticker_date(start_iso: str) -> str:
    """ESPN kickoff -> the 'YYMONDD' fragment in Kalshi's event tickers (Eastern date)."""
    try:
        dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(EASTERN)
    except ValueError:
        return ""
    return f"{dt:%y}{MONTHS[dt.month - 1]}{dt:%d}"


class SoccerFeed:
    def __init__(self, kalshi: KalshiClient):
        self.kalshi = kalshi
        self.matches: dict[str, Match] = {}
        self.status = {"espn": _status(False, "Waiting for first ESPN update"), "kalshi": _status(False, "Waiting for first Kalshi update")}
        self._http = httpx.AsyncClient(timeout=10.0)
        self._sem = asyncio.Semaphore(6)
        self._next_schedule = 0.0
        self._next_live = 0.0
        self._next_kalshi: dict[str, float] = {}
        self._next_summary: dict[str, float] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ refresh
    async def refresh(self) -> list[Match]:
        now = time.monotonic()
        if now >= self._next_schedule:
            self._next_schedule = now + 600
            await self._guard("espn", self._refresh_schedule)
        elif now >= self._next_live and self._hot_leagues():
            self._next_live = now + 10
            await self._guard("espn", self._refresh_live)
        await self._refresh_summaries(now)
        await self._refresh_kalshi(now)
        for m in self.matches.values():
            self._set_prior(m)
            model.price(m)
        return self.board()

    def board(self) -> list[Match]:
        order = {"live": 0, "pre": 1, "final": 2}
        return sorted(self.matches.values(), key=lambda m: (order[m.state], m.start_time if m.state != "final" else "~" + m.start_time))

    async def _guard(self, name: str, fn) -> None:
        try:
            self.status[name] = _status(True, await fn())
        except Exception as exc:  # a feed outage must never take the loop down
            log.warning("soccer %s feed failed: %s", name, exc)
            self.status[name] = _status(False, f"{type(exc).__name__}: {exc}"[:200])

    def _hot_leagues(self) -> set[str]:
        """Leagues with a match on, or kicking off within 15 minutes."""
        soon = datetime.now(EASTERN) + timedelta(minutes=15)
        hot = set()
        for m in self.matches.values():
            if m.state == "live" or (m.state == "pre" and _when(m.start_time) <= soon) or (m.state == "final" and not m.summary_final):
                hot.add(m.league)
        return hot

    # -------------------------------------------------------------------- ESPN
    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._sem:
            resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _scoreboards(self, pairs: list[tuple[League, str]]) -> int:
        results = await asyncio.gather(
            *(self._get(ESPN.format(code=lg.espn, what="scoreboard"), {"dates": day}) for lg, day in pairs), return_exceptions=True
        )
        failures = 0
        for (lg, _), data in zip(pairs, results):
            if isinstance(data, Exception):
                failures += 1
                continue
            for ev in data.get("events") or []:
                self._apply_event(lg, ev)
        if failures == len(pairs):
            raise RuntimeError("ESPN scoreboards unreachable")
        return failures

    async def _refresh_schedule(self) -> str:
        today = datetime.now(EASTERN).date()
        days = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in range(-1, DAYS_AHEAD + 1)]
        await self._scoreboards([(lg, d) for lg in LEAGUES for d in days])
        self._drop_old()
        live = sum(m.state == "live" for m in self.matches.values())
        return f"{len(self.matches)} matches on the board, {live} live"

    async def _refresh_live(self) -> str:
        today = datetime.now(EASTERN).date()
        days = [today.strftime("%Y%m%d"), (today - timedelta(days=1)).strftime("%Y%m%d")]
        await self._scoreboards([(LEAGUE_BY_KEY[k], d) for k in self._hot_leagues() for d in days])
        live = sum(m.state == "live" for m in self.matches.values())
        return f"{len(self.matches)} matches on the board, {live} live"

    def _drop_old(self) -> None:
        cutoff = datetime.now(EASTERN) - timedelta(hours=KEEP_FINAL_HOURS)
        for mid, m in list(self.matches.items()):
            if m.state == "final" and _when(m.start_time) < cutoff:
                del self.matches[mid]

    @staticmethod
    def _side(c: dict[str, Any]) -> Side:
        t = c.get("team") or {}
        return Side(
            id=str(t.get("id", "")), abbr=t.get("abbreviation", "?"), name=t.get("displayName", "?"),
            short=t.get("shortDisplayName") or t.get("displayName", "?"),
            color=(t.get("color") or "8b9cff").lstrip("#"), logo=t.get("logo") or "",
        )

    def _apply_event(self, league: League, ev: dict[str, Any]) -> None:
        comp = (ev.get("competitions") or [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" not in sides or "away" not in sides:
            return
        mid = f"soccer-{ev['id']}"
        m = self.matches.get(mid)
        if m is None:
            m = Match(id=mid, league=league.key, home=self._side(sides["home"]), away=self._side(sides["away"]), start_time=ev.get("date", ""))
            self.matches[mid] = m
        m.start_time = ev.get("date", m.start_time)
        status = ev.get("status") or {}
        kind = status.get("type") or {}
        m.state = {"pre": "pre", "in": "live", "post": "final"}.get(kind.get("state", "pre"), "pre")
        if kind.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED"):
            m.state = "final" if kind.get("name") == "STATUS_ABANDONED" else "pre"
        m.period = int(status.get("period") or 0)
        m.clock = status.get("displayClock") or ""
        m.status = kind.get("shortDetail") or kind.get("description") or ""
        m.halftime = kind.get("name") == "STATUS_HALFTIME"
        m.minute = minute_of(m.clock, m.period) if m.state == "live" else (90.0 if m.state == "final" else 0.0)
        m.home.score = int(sides["home"].get("score") or 0)
        m.away.score = int(sides["away"].get("score") or 0)
        odds = (comp.get("odds") or [None])[0]
        if odds and (odds.get("moneyline") or odds.get("overUnder") is not None):
            m.odds = odds

    async def _refresh_summaries(self, now: float) -> None:
        due = [
            m for m in self.matches.values()
            if (m.state == "live" or (m.state == "final" and not m.summary_final)) and now >= self._next_summary.get(m.id, 0.0)
        ]
        for m in due[:10]:
            self._next_summary[m.id] = now + 15
        if due:
            await asyncio.gather(*(self._load_summary(m) for m in due[:10]))

    async def _load_summary(self, m: Match) -> None:
        try:
            data = await self._get(ESPN.format(code=LEAGUE_BY_KEY[m.league].espn, what="summary"), {"event": m.id.removeprefix("soccer-")})
        except Exception as exc:  # events and stats are a nice-to-have; keep the last good ones
            log.info("soccer summary for %s unavailable: %s", m.label, exc)
            return
        apply_summary(m, data)
        if m.state == "final":
            m.summary_final = True

    # ------------------------------------------------------------------- Kalshi
    async def _refresh_kalshi(self, now: float) -> None:
        live = {m.league for m in self.matches.values() if m.state == "live"}
        on_board = {m.league for m in self.matches.values()}
        due = []
        for lg in LEAGUES:
            if lg.key in on_board and now >= self._next_kalshi.get(lg.key, 0.0):
                self._next_kalshi[lg.key] = now + (5 if lg.key in live else 60)
                due.append(lg)
        if not due:
            return
        try:
            # First-half markets are only worth fetching until half time.
            first_half_open = {m.league for m in self.matches.values() if m.state == "pre" or (m.state == "live" and not m.first_half_over)}
            jobs = [(lg, suffix) for lg in due for suffix, segment, _ in SERIES if segment != "1h" or lg.key in first_half_open]
            results = await asyncio.gather(*(self._series(lg.kalshi + suffix) for lg, suffix in jobs), return_exceptions=True)
            by_league: dict[str, dict[str, list[dict[str, Any]]]] = {}
            failed = 0
            for (lg, suffix), res in zip(jobs, results):
                if isinstance(res, Exception):
                    failed += 1
                    continue
                by_league.setdefault(lg.key, {})[suffix] = res
            if failed == len(jobs):
                raise RuntimeError("Kalshi soccer series unreachable")
            for lg in due:
                self._apply_kalshi(lg, by_league.get(lg.key, {}))
            priced = sum(1 for m in self.matches.values() if m.markets)
            self.status["kalshi"] = _status(True, f"{priced}/{len(self.matches)} matches priced on Kalshi")
        except Exception as exc:
            log.warning("soccer kalshi feed failed: %s", exc)
            self.status["kalshi"] = _status(False, f"{type(exc).__name__}: {exc}"[:200])

    async def _series(self, ticker: str) -> list[dict[str, Any]]:
        async with self._sem:
            return await self.kalshi.events(ticker)

    def _apply_kalshi(self, lg: League, series: dict[str, list[dict[str, Any]]]) -> int:
        games = series.get("GAME") or []
        by_suffix: dict[str, dict[str, dict[str, Any]]] = {}
        for suffix, events in series.items():
            for e in events:
                by_suffix.setdefault(suffix, {})[e["event_ticker"].split("-", 1)[-1]] = e
        matched = 0
        for m in self.matches.values():
            if m.league != lg.key:
                continue
            if m.event_suffix is None or m.event_suffix not in by_suffix.get("GAME", {}):
                found = match_event(m, games)
                if found is None:
                    continue
                m.event_suffix = found["event_ticker"].split("-", 1)[-1]
                assign_codes(m, found)
            matched += 1
            markets: list[SMarket] = []
            fresh: set[tuple[str, str]] = set()
            for suffix, segment, kind in SERIES:
                if suffix not in by_suffix:
                    continue  # not fetched this round (or it failed): keep what we had
                event = by_suffix[suffix].get(m.event_suffix)
                if event:
                    markets.extend(build_markets(m, event, segment, kind))
                    fresh.add((segment, kind))
            kept = [x for x in m.markets if (x.segment, x.kind) not in fresh]
            if markets or kept:
                m.markets = markets + kept
        return matched

    # --------------------------------------------------------------------- prior
    @staticmethod
    def _set_prior(m: Match) -> None:
        """Pre-match expected goals: fitted to the bookmaker before kickoff, then frozen."""
        if m.lam_home is not None and m.state != "pre":
            return
        fitted, source = None, ""
        if m.odds:
            fitted, source = model.prior_from_odds(m.odds), f"{((m.odds.get('provider') or {}).get('name') or 'Sportsbook')} odds"
        if fitted is None and m.state == "pre" and m.markets:
            fitted, source = model.prior_from_kalshi(m.markets), "Kalshi prices"
        if fitted is None:
            avg = LEAGUE_BY_KEY[m.league].avg_goals
            fitted, source = (avg * model.DEFAULT_HOME_SHARE, avg * (1 - model.DEFAULT_HOME_SHARE)), "league average"
        m.lam_home, m.lam_away = round(fitted[0], 3), round(fitted[1], 3)
        m.prior_source = source


def _when(ts: str) -> datetime:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(EASTERN)


def match_event(m: Match, events: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The Kalshi winner event for an ESPN match: same Eastern date (or a day either side), best names."""
    day = ticker_date(m.start_time)
    try:
        dt = datetime.fromisoformat(m.start_time.replace("Z", "+00:00")).astimezone(EASTERN)
        near = {ticker_date((dt + timedelta(days=d)).isoformat()) for d in (-1, 1)}
    except ValueError:
        near = set()
    best, best_score = None, 0.0
    for e in events:
        frag = e["event_ticker"].split("-", 1)[-1][:7]
        if frag != day and frag not in near:
            continue
        home, away = split_title(e.get("title") or "")
        score = pair_score(m.home.name, m.away.name, home, away) + (0.2 if frag == day else 0.0)
        if score > best_score:
            best, best_score = e, score
    return best if best_score >= 1.2 else None


def assign_codes(m: Match, game_event: dict[str, Any]) -> None:
    """Kalshi's team codes, from the winner markets' ticker suffixes and outcome names."""
    for mk in game_event.get("markets") or []:
        code = mk["ticker"].rsplit("-", 1)[-1]
        if code == "TIE":
            continue
        name = mk.get("yes_sub_title") or ""
        side = m.home if similarity(name, m.home.name) >= similarity(name, m.away.name) else m.away
        side.code = code


def _outcome_from_code(m: Match, suffix: str) -> Optional[str]:
    """Which side a market suffix like 'MCI2' or 'M052' names: the longest code it starts with."""
    best, length = None, 0
    for side, name in ((m.home, "home"), (m.away, "away")):
        if side.code and suffix.startswith(side.code) and len(side.code) > length:
            best, length = name, len(side.code)
    return best


def build_markets(m: Match, event: dict[str, Any], segment: str, kind: str) -> list[SMarket]:
    out = []
    for mk in event.get("markets") or []:
        suffix = mk["ticker"].rsplit("-", 1)[-1]
        strike = mk.get("floor_strike")
        if kind == "winner":
            outcome = "tie" if suffix == "TIE" else _outcome_from_code(m, suffix)
            if outcome is None:
                continue
            strike = None
        elif kind == "spread":
            outcome = _outcome_from_code(m, suffix)
            if outcome is None or strike is None:
                continue
        else:
            outcome = None
            if strike is None:
                continue
        out.append(SMarket(
            ticker=mk["ticker"], segment=segment, kind=kind, outcome=outcome,
            strike=float(strike) if strike is not None else None, title=mk.get("title") or "",
            yes_bid=cents(mk.get("yes_bid_dollars")), yes_ask=cents(mk.get("yes_ask_dollars")),
            no_bid=cents(mk.get("no_bid_dollars")), no_ask=cents(mk.get("no_ask_dollars")),
            volume=float(mk.get("volume_fp") or 0), result=mk.get("result") or "",
        ))
    order = {"home": 0, "tie": 1, "away": 2, None: 3}
    return sorted(out, key=lambda x: (order[x.outcome], x.strike or 0))


def apply_summary(m: Match, data: dict[str, Any]) -> None:
    """Goals, cards and subs; team stats; the half-time score; every line of commentary."""
    teams = {}
    for c in ((data.get("header") or {}).get("competitions") or [{}])[0].get("competitors") or []:
        side = m.home if c.get("homeAway") == "home" else m.away
        teams[str((c.get("team") or {}).get("id"))] = "home" if side is m.home else "away"
        lines = c.get("linescores") or []
        if lines and m.first_half_over:
            try:
                side.half_score = int(float(lines[0].get("displayValue") or lines[0].get("value") or 0))
            except (TypeError, ValueError):
                pass

    events = []
    for e in data.get("keyEvents") or []:
        kind = ((e.get("type") or {}).get("text") or "").strip()
        if not any(k in kind.lower() for k in EVENT_KINDS):
            continue
        events.append({
            "minute": ((e.get("clock") or {}).get("displayValue")) or "",
            "period": int((e.get("period") or {}).get("number") or 0),
            "type": kind,
            "team": teams.get(str((e.get("team") or {}).get("id"))),
            "text": " ".join((e.get("text") or e.get("shortText") or kind).split()),
            "goal": bool(e.get("scoringPlay")),
        })
    if events:
        m.events = events

    stats: dict[str, dict[str, float]] = {}
    reds = {"home": 0, "away": 0}
    for t in (data.get("boxscore") or {}).get("teams") or []:
        side = teams.get(str((t.get("team") or {}).get("id")))
        if side is None:
            continue
        for st in t.get("statistics") or []:
            name = st.get("name")
            if name not in STATS:
                continue
            try:
                value = float(st.get("displayValue") or 0)
            except (TypeError, ValueError):
                continue
            stats.setdefault(STATS[name], {})[side] = value
            if name == "redCards":
                reds[side] = int(value)
    if stats:
        m.stats = stats
        m.home.red_cards, m.away.red_cards = reds["home"], reds["away"]

    comm = [
        {"minute": ((c.get("time") or {}).get("displayValue")) or "", "text": " ".join((c.get("text") or "").split())}
        for c in data.get("commentary") or [] if c.get("text")
    ]
    if comm:
        m.commentary = comm
