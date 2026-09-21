#!/usr/bin/env python3
"""Phase 0 draft: import Kalshi soccer-totals history and match scorelines.

Pulls fills, orders, and settlements from the Kalshi portfolio API (live +
historical), filters to soccer totals, resolves each fill to a FotMob (then
ESPN) historical scoreline, and computes match state at fill time:

    minute, score, rem = strike_goals - current_goals, No price, league

Uses existing repo auth:

    kalshi_bot/kalshi/auth.py  (RSA-PSS request signing)
    kalshi_bot/kalshi/rest.py  (soccer totals series catalogue)

Credentials (Cloud Agent secrets or env):

    KALSHI_API_KEY_ID
    KALSHI_PRIVATE_KEY_PEM

Important signing note: Kalshi portfolio/historical GETs must be signed
against the path only (no query string). Including ``?limit=`` in the
signature returns INCORRECT_API_KEY_SIGNATURE.

Run from the repo root (or with PYTHONPATH pointing at it)::

    uv run python scripts/import_history.py --out-dir data/phase0-out

Artifacts land under --out-dir (default: this script's directory / phase0-out).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode

import requests

# Repo on PYTHONPATH so we reuse production signing, not a copy.
REPO_ROOT = Path(os.environ.get("KALSHI_BOT_REPO", "/workspace"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from kalshi_bot.kalshi.auth import sign_request  # noqa: E402
from kalshi_bot.kalshi.rest import SOCCER_TOTAL_SERIES as SOCCER_SERIES_TICKERS  # noqa: E402

KALSHI_HOST = "https://api.elections.kalshi.com"
FOTMOB_MATCHES = "https://www.fotmob.com/api/data/matches"
FOTMOB_DETAILS = "https://www.fotmob.com/api/data/matchDetails"
ESPN_SCOREBOARD = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
ESPN_SUMMARY = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Series that are soccer totals. Anything matching *TOTAL* is a candidate
# unless it is in NON_SOCCER_TOTAL_SERIES.
NON_SOCCER_TOTAL_SERIES = {
    "KXNBATOTAL",
    "KXNBA1HTOTAL",
    "KXWNBATOTAL",
    "KXNFLTOTAL",
    "KXNHLTOTAL",
    "KXMLBTOTAL",
    "KXNCAAFBTOTAL",
    "KXNCAABTOTAL",
}

# League label + playbook tier from series prefix.
SERIES_LEAGUE: Dict[str, Tuple[str, int]] = {
    "KXEPLTOTAL": ("Premier League", 1),
    "KXEPL1HTOTAL": ("Premier League 1H", 1),
    "KXLALIGATOTAL": ("La Liga", 1),
    "KXSERIEATOTAL": ("Serie A", 1),
    "KXSERIEA1HTOTAL": ("Serie A 1H", 1),
    "KXBUNDESLIGATOTAL": ("Bundesliga", 1),
    "KXLIGUE1TOTAL": ("Ligue 1", 1),
    "KXUCLTOTAL": ("Champions League", 1),
    "KXUCL1HTOTAL": ("Champions League 1H", 1),
    "KXWCTOTAL": ("World Cup", 1),
    "KXWC1HTOTAL": ("World Cup 1H", 1),
    "KXUELTOTAL": ("Europa League", 2),
    "KXUECLTOTAL": ("Conference League", 2),
    "KXMLSTOTAL": ("MLS", 2),
    "KXLIGAMXTOTAL": ("Liga MX", 2),
    "KXEREDIVISIETOTAL": ("Eredivisie", 2),
    "KXLIGAPORTUGALTOTAL": ("Liga Portugal", 2),
    "KXEFLCHAMPIONSHIPTOTAL": ("EFL Championship", 2),
    "KXEFLCUPTOTAL": ("EFL Cup", 2),
    "KXCONMEBOLLIBTOTAL": ("Copa Libertadores", 2),
    "KXCONMEBOLSUDTOTAL": ("Copa Sudamericana", 2),
    "KXBRASILEIROTOTAL": ("Brasileirão", 2),
    "KXBRASILEIROBTOTAL": ("Brasileirão B", 3),
    "KXBRASILEIRO1HTOTAL": ("Brasileirão 1H", 2),
    "KXARGPREMDIVTOTAL": ("Argentine Primera", 2),
    "KXLIGUE2TOTAL": ("Ligue 2", 3),
    "KXSERIEBTOTAL": ("Serie B", 3),
    "KXSCOTTISHPREMTOTAL": ("Scottish Premiership", 2),
    "KXSAUDIPLTOTAL": ("Saudi Pro League", 2),
    "KXCLUBFTOTAL": ("Club Friendlies / CWC", 2),
    "KXNWSLTOTAL": ("NWSL", 3),
    "KXUCLWTOTAL": ("UWCL", 3),
    "KXPERLIGA1TOTAL": ("Peruvian Liga 1", 3),
    "KXDENSUPERLIGATOTAL": ("Danish Superliga", 3),
    "KXAPFDDHTOTAL": ("Argentine Primera División (alt)", 2),
    "KXMYSLTOTAL": ("Malaysia Super League", 3),
    "KXDIMAYORTOTAL": ("Categoría Primera A", 3),
    "KXLVAVIRTOTAL": ("Liga MX / Liga de Expansión", 3),
    "KXJLEAGUETOTAL": ("J1 League", 2),
    "KXTHAIL1TOTAL": ("Thai League 1", 3),
    "KXSUPERLIGTOTAL": ("Süper Lig", 2),
    "KXASEANTOTAL": ("ASEAN / AFF", 3),
    "KXISRNLTOTAL": ("Israeli Premier League", 3),
    "KXIDNSLTOTAL": ("Liga 1 Indonesia", 3),
    "KXSGPPLTOTAL": ("Singapore Premier League", 3),
    "KXUSLCUPTOTAL": ("USL Cup", 3),
    "KXCZEFNLTOTAL": ("Czech First League", 3),
    "KXVENFUTVETOTAL": ("Venezuelan Primera", 3),
    "KXSLGREECETOTAL": ("Super League Greece", 3),
    "KXINTLFRIENDLYTOTAL": ("International Friendly", 3),
    "KXUAEPLTOTAL": ("UAE Pro League", 3),
    "KXEGYPLTOTAL": ("Egyptian Premier League", 3),
    "KXWCTEAMTOTAL": ("World Cup team total", 1),
    "KXFINYLTOTAL": ("Veikkausliiga", 3),
    "KXALLSVENSKANTOTAL": ("Allsvenskan", 3),
    "KXCOPPAITALIATOTAL": ("Coppa Italia", 2),
    "KXUSLTOTAL": ("USL Championship", 3),
}

# FotMob / ESPN name hints for Kalshi 3-letter codes that otherwise collide.
ABBREV_ALIASES: Dict[str, List[str]] = {
    "MUN": ["manchester united", "man united", "man utd"],
    "MCI": ["manchester city", "man city"],
    "ACM": ["milan", "ac milan"],
    "INT": ["internazionale", "inter"],
    "TOT": ["tottenham"],
    "NFO": ["nottingham forest", "forest"],
    "BOU": ["bournemouth"],
    "LFC": ["liverpool"],
    "LEE": ["leeds"],
    "CRY": ["crystal palace"],
    "FUL": ["fulham"],
    "LEC": ["lecce"],
    "JUV": ["juventus"],
    "ATA": ["atalanta"],
    "PAR": ["parma"],
    "GEN": ["genoa"],
    "NIC": ["nice"],
    "LIL": ["lille"],
    "PSG": ["paris saint-germain", "paris sg", "psg"],
    "RMA": ["real madrid"],
    "BAR": ["barcelona"],
    "ATM": ["atletico madrid", "atlético"],
    "BAY": ["bayern"],
    "DOR": ["dortmund"],
    "ARS": ["arsenal"],
    "CHE": ["chelsea"],
    "NEW": ["newcastle"],
    "WHU": ["west ham"],
    "WOL": ["wolves", "wolverhampton"],
    "BRI": ["brighton"],
    "EVE": ["everton"],
    "AVL": ["aston villa"],
    "SOU": ["southampton"],
    "BRE": ["brentford"],
    "IPS": ["ipswich"],
    "LEI": ["leicester"],
    "NAP": ["napoli"],
    "ROM": ["roma"],
    "LAZ": ["lazio"],
    "FIO": ["fiorentina"],
    "BOL": ["bologna"],
    "TOR": ["torino"],
    "UDI": ["udinese"],
    "SAS": ["sassuolo"],
    "CAG": ["cagliari"],
    "VER": ["hellas verona", "verona"],
    "MON": ["monaco"],
    "MAR": ["marseille"],
    "LYO": ["lyon"],
    "REN": ["rennes"],
    "LEN": ["lens"],
    "STR": ["strasbourg"],
    "LAFC": ["los angeles fc", "lafc"],
    "LAG": ["la galaxy", "galaxy"],
}

ESPN_SLUG_BY_SERIES = {
    "KXEPLTOTAL": "eng.1",
    "KXEPL1HTOTAL": "eng.1",
    "KXLALIGATOTAL": "esp.1",
    "KXSERIEATOTAL": "ita.1",
    "KXSERIEA1HTOTAL": "ita.1",
    "KXBUNDESLIGATOTAL": "ger.1",
    "KXLIGUE1TOTAL": "fra.1",
    "KXUCLTOTAL": "uefa.champions",
    "KXUCL1HTOTAL": "uefa.champions",
    "KXUELTOTAL": "uefa.europa",
    "KXMLSTOTAL": "usa.1",
    "KXLIGUE2TOTAL": "fra.2",
    "KXSERIEBTOTAL": "ita.2",
    "KXEFLCHAMPIONSHIPTOTAL": "eng.2",
    "KXSCOTTISHPREMTOTAL": "sco.1",
    "KXEREDIVISIETOTAL": "ned.1",
    "KXLIGAPORTUGALTOTAL": "por.1",
    "KXBRASILEIROTOTAL": "bra.1",
    "KXNWSLTOTAL": "usa.nwsl",
}

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


# ---------------------------------------------------------------------------
# Kalshi client
# ---------------------------------------------------------------------------

class KalshiClient:
    def __init__(self, key_id: str, pem: str, host: str = KALSHI_HOST):
        self.key_id = key_id
        self.pem = pem
        self.host = host.rstrip("/")
        self.session = requests.Session()

    def signed_get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET with RSA-PSS signature over the path only (no query string)."""
        ts = str(int(time.time() * 1000))
        signature = sign_request(self.pem, ts, "GET", path)
        headers = {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Accept": "application/json",
        }
        url = self.host + path
        r = self.session.get(url, headers=headers, params=params or {}, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"GET {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def paginate(self, path: str, list_key: str, extra: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        pages = 0
        while True:
            params = {"limit": 200}
            if extra:
                params.update(extra)
            if cursor:
                params["cursor"] = cursor
            data = self.signed_get(path, params)
            batch = data.get(list_key) or []
            items.extend(batch)
            cursor = data.get("cursor") or ""
            pages += 1
            print(f"  {path} page {pages} +{len(batch)} total={len(items)}")
            if not cursor or not batch or pages > 250:
                break
        return items

    def get_market(self, ticker: str) -> Optional[Dict[str, Any]]:
        try:
            data = self.signed_get(f"/trade-api/v2/markets/{ticker}")
            return data.get("market") or data
        except RuntimeError:
            try:
                data = self.signed_get(f"/trade-api/v2/historical/markets/{ticker}")
                return data.get("market") or data
            except RuntimeError:
                return None

    def get_event(self, event_ticker: str) -> Optional[Dict[str, Any]]:
        try:
            data = self.signed_get(f"/trade-api/v2/events/{event_ticker}")
            return data.get("event") or data
        except RuntimeError:
            return None


# ---------------------------------------------------------------------------
# Scoreline clients
# ---------------------------------------------------------------------------

def _http_get_json(url: str, params: Optional[Dict[str, Any]] = None, retries: int = 3) -> Optional[Any]:
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=BROWSER_HEADERS, params=params, timeout=30)
            if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
                return r.json()
            last = f"{r.status_code} {r.text[:120]}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(0.4 * (i + 1))
    print(f"  scoreline miss {url} {last}")
    return None


def fotmob_matches_for_date(yyyymmdd: str) -> List[Dict[str, Any]]:
    data = _http_get_json(FOTMOB_MATCHES, {"date": yyyymmdd})
    if not data:
        return []
    out = []
    for league in data.get("leagues") or []:
        for match in league.get("matches") or []:
            rec = dict(match)
            rec["_league_name"] = league.get("name")
            rec["_league_id"] = league.get("id")
            rec["_ccode"] = league.get("ccode")
            out.append(rec)
        # small courtesy pause not needed per league
    return out


def fotmob_match_details(match_id: int) -> Optional[Dict[str, Any]]:
    return _http_get_json(FOTMOB_DETAILS, {"matchId": match_id})


def espn_scoreboard(slug: str, yyyymmdd: str) -> List[Dict[str, Any]]:
    data = _http_get_json(ESPN_SCOREBOARD.format(slug=slug), {"dates": yyyymmdd})
    if not data:
        return []
    return data.get("events") or []


def espn_summary(slug: str, event_id: str) -> Optional[Dict[str, Any]]:
    return _http_get_json(ESPN_SUMMARY.format(slug=slug), {"event": event_id})


# ---------------------------------------------------------------------------
# Parsing / matching
# ---------------------------------------------------------------------------

def parse_ticker(ticker: str) -> Dict[str, Any]:
    """Parse KXSERIEATOTAL-26SEP20JUVATA-4 style soccer total tickers."""
    parts = (ticker or "").split("-")
    series = parts[0] if parts else ""
    date_teams = parts[1] if len(parts) > 1 else ""
    strike_raw = parts[-1] if len(parts) > 2 else ""
    m = re.match(r"^(\d{2})([A-Z]{3})(\d{2})([A-Z0-9]+)$", date_teams)
    year = month = day = None
    home_abbr = away_abbr = None
    teams_blob = date_teams
    if m:
        yy, mon, dd, teams = m.groups()
        year = 2000 + int(yy)
        month = MONTHS.get(mon)
        day = int(dd)
        teams_blob = teams
        if len(teams) == 6:
            home_abbr, away_abbr = teams[:3], teams[3:]
        elif len(teams) == 8:
            home_abbr, away_abbr = teams[:4], teams[4:]
        else:
            # try 3+rest
            home_abbr, away_abbr = teams[:3], teams[3:]
    strike_n = None
    sm = re.search(r"(\d+)$", strike_raw)
    if sm:
        strike_n = int(sm.group(1))
    # suffix N => Over (N-0.5). rem-to-over uses integer N.
    over_line = (strike_n - 0.5) if strike_n is not None else None
    kickoff_date = None
    if year and month and day:
        kickoff_date = f"{year:04d}-{month:02d}-{day:02d}"
        yyyymmdd = f"{year:04d}{month:02d}{day:02d}"
    else:
        yyyymmdd = None
    is_1h = "1H" in series
    return {
        "series": series,
        "date_teams": date_teams,
        "strike_n": strike_n,
        "over_line": over_line,
        "home_abbr": home_abbr,
        "away_abbr": away_abbr,
        "teams_blob": teams_blob,
        "kickoff_date": kickoff_date,
        "yyyymmdd": yyyymmdd,
        "is_1h": is_1h,
    }


def is_soccer_total_ticker(ticker: str) -> bool:
    t = (ticker or "").upper()
    if "TOTAL" not in t:
        return False
    series = t.split("-")[0]
    if series in NON_SOCCER_TOTAL_SERIES:
        return False
    if any(x in series for x in ("NBA", "WNBA", "NFL", "NHL", "MLB", "NCAAF", "NCAAB", "BTC")):
        return False
    return True


def league_for_series(series: str, event: Optional[Dict[str, Any]] = None) -> Tuple[str, int]:
    if series in SERIES_LEAGUE:
        return SERIES_LEAGUE[series]
    meta = (event or {}).get("product_metadata") or {}
    name = meta.get("competition") or series
    # default: known top-flight words -> tier 1, else 3
    upper = name.upper()
    if any(k in upper for k in ("PREMIER LEAGUE", "LA LIGA", "SERIE A", "BUNDESLIGA", "LIGUE 1", "CHAMPIONS", "WORLD CUP")):
        return name, 1
    return name, 3


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    for junk in (
        " fc", " cf", " afc", " sc", " united", " city", " club",
        " de ", " the ", " football",
    ):
        s = s.replace(junk, " ")
    return re.sub(r"\s+", " ", s).strip()


def _name_score(query: str, candidate: str) -> float:
    q, c = _norm(query), _norm(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.92
    return SequenceMatcher(None, q, c).ratio()


def parse_event_teams(event: Optional[Dict[str, Any]], market: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    title = ""
    if event:
        title = event.get("title") or event.get("sub_title") or ""
    if market and not title:
        title = market.get("title") or ""
    # "Milan vs Lecce: First Half Total" / "Will over 3.5 goals be scored?"
    m = re.split(r"\s+vs\.?\s+", title, maxsplit=1, flags=re.I)
    if len(m) == 2:
        home = re.split(r"[:\-(]", m[0], maxsplit=1)[0].strip()
        away = re.split(r"[:\-(]", m[1], maxsplit=1)[0].strip()
        if home and away and "over" not in home.lower():
            return home, away
    return None, None


def match_fotmob(
    parsed: Dict[str, Any],
    home: Optional[str],
    away: Optional[str],
    day_matches: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not day_matches:
        return None
    best = None
    best_score = 0.0
    queries_home = [home] if home else []
    queries_away = [away] if away else []
    for abbr, bucket in ((parsed.get("home_abbr"), queries_home), (parsed.get("away_abbr"), queries_away)):
        if abbr and abbr in ABBREV_ALIASES:
            bucket.extend(ABBREV_ALIASES[abbr])
        if abbr:
            bucket.append(abbr)
    for m in day_matches:
        mh = m.get("home") or {}
        ma = m.get("away") or {}
        names_h = [mh.get("name"), mh.get("longName"), mh.get("shortName")]
        names_a = [ma.get("name"), ma.get("longName"), ma.get("shortName")]
        hs = max((_name_score(q, n or "") for q in queries_home for n in names_h), default=0.0)
        as_ = max((_name_score(q, n or "") for q in queries_away for n in names_a), default=0.0)
        # also try swapped (Kalshi sometimes lists away first)
        hs2 = max((_name_score(q, n or "") for q in queries_home for n in names_a), default=0.0)
        as2 = max((_name_score(q, n or "") for q in queries_away for n in names_h), default=0.0)
        score = max(hs + as_, hs2 + as2)
        if score > best_score:
            best_score = score
            best = m
    if best is not None and best_score >= 1.3:
        best = dict(best)
        best["_match_score"] = round(best_score, 3)
        return best
    return None


def extract_fotmob_goals(details: Dict[str, Any]) -> List[Dict[str, Any]]:
    events = (
        ((details.get("content") or {}).get("matchFacts") or {}).get("events") or {}
    )
    rows = events.get("events") if isinstance(events, dict) else events
    goals = []
    if not isinstance(rows, list):
        return goals
    for ev in rows:
        if (ev.get("type") or "").lower() != "goal":
            continue
        minute = ev.get("time")
        added = ev.get("overloadTime") or 0
        try:
            minute_f = float(minute) + (float(added) / 1.0 if added else 0)
        except (TypeError, ValueError):
            continue
        ns = ev.get("newScore") or [ev.get("homeScore"), ev.get("awayScore")]
        goals.append({
            "minute": minute_f,
            "period": ((ev.get("shotmapEvent") or {}).get("period")) or None,
            "home": int(ns[0]) if ns and ns[0] is not None else None,
            "away": int(ns[1]) if ns and len(ns) > 1 and ns[1] is not None else None,
            "is_home": ev.get("isHome"),
            "player": (ev.get("player") or {}).get("name") or ev.get("nameStr"),
        })
    goals.sort(key=lambda g: g["minute"])
    return goals


def extract_espn_goals(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    goals = []
    for ev in summary.get("keyEvents") or []:
        typ = (ev.get("type") or {})
        if (typ.get("type") or "").lower() != "goal" and not ev.get("scoringPlay"):
            continue
        if (typ.get("type") or "").lower() not in ("goal", ""):
            if not ev.get("scoringPlay"):
                continue
        clock = ev.get("clock") or {}
        disp = clock.get("displayValue") or ""
        mm = re.match(r"(\d+)(?:'\+(\d+))?", disp.replace(" ", ""))
        if not mm:
            # seconds value / 60
            try:
                minute_f = float(clock.get("value") or 0) / 60.0
            except (TypeError, ValueError):
                continue
        else:
            minute_f = int(mm.group(1)) + (int(mm.group(2)) if mm.group(2) else 0)
        goals.append({
            "minute": minute_f,
            "period": (ev.get("period") or {}).get("number"),
            "home": None,
            "away": None,
            "is_home": None,
            "player": ev.get("shortText"),
        })
    goals.sort(key=lambda g: g["minute"])
    return goals


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_fotmob_local(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def soccer_minute_at(
    fill_dt: datetime,
    kickoff_utc: Optional[datetime],
    fotmob_match: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], str]:
    """Return (soccer_minute, phase) at fill time."""
    if not fill_dt:
        return None, "unknown"
    status = (fotmob_match or {}).get("status") or {}
    halfs = status.get("halfs") or {}
    ko = kickoff_utc or parse_iso(status.get("utcTime"))
    if ko is None:
        return None, "unknown"

    # Convert FotMob local half-start strings using offset implied by listed kickoff.
    local_ko = parse_fotmob_local((fotmob_match or {}).get("time"))
    offset = timedelta(0)
    if local_ko is not None and ko is not None:
        # local_ko is naive; treat as same wall-clock as utc + offset
        offset = local_ko - ko.replace(tzinfo=None)

    def local_to_utc(s: Optional[str]) -> Optional[datetime]:
        loc = parse_fotmob_local(s)
        if loc is None:
            return None
        return (loc - offset).replace(tzinfo=timezone.utc)

    fh = local_to_utc(halfs.get("firstHalfStarted"))
    sh = local_to_utc(halfs.get("secondHalfStarted"))
    fill = fill_dt.astimezone(timezone.utc)

    if fh and fill < fh - timedelta(minutes=1):
        return 0.0, "prekick"
    if fh:
        if sh is None or fill < sh:
            elapsed = (fill - fh).total_seconds() / 60.0
            if elapsed <= 50:
                return max(0.0, elapsed), "1H"
            return 45.0, "HT"
        elapsed2 = (fill - sh).total_seconds() / 60.0
        return 45.0 + max(0.0, elapsed2), "2H"

    # Fallback: scheduled kickoff + 15 min HT after 48'
    elapsed = (fill - ko).total_seconds() / 60.0
    if elapsed < -1:
        return 0.0, "prekick"
    if elapsed < 0:
        return 0.0, "kickoff"
    if elapsed <= 48:
        return elapsed, "1H"
    if elapsed <= 63:
        return 45.0, "HT"
    return 45.0 + (elapsed - 60.0), "2H"


def goals_before(goals: List[Dict[str, Any]], minute: Optional[float], is_1h: bool) -> Tuple[int, int, int]:
    """Return (home, away, total) goals strictly before `minute`."""
    h = a = t = 0
    if minute is None:
        return 0, 0, 0
    for g in goals:
        gm = g.get("minute")
        if gm is None or gm > minute + 1e-6:
            continue
        if is_1h and gm > 45.5:
            continue
        t += 1
        if g.get("home") is not None and g.get("away") is not None:
            h, a = g["home"], g["away"]
        elif g.get("is_home") is True:
            h += 1
        elif g.get("is_home") is False:
            a += 1
    if h + a != t and not any(g.get("home") is not None for g in goals):
        h, a = t, 0  # unknown split
    return h, a, t


def fp_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def classify_fill_role(fill: Dict[str, Any]) -> str:
    action = (fill.get("action") or "").lower()
    side = (fill.get("side") or fill.get("outcome_side") or "").lower()
    if action == "buy" and side == "no":
        return "buy_no"
    if action == "sell" and side == "no":
        return "sell_no"
    if action == "buy" and side == "yes":
        return "buy_yes"
    if action == "sell" and side == "yes":
        return "sell_yes"
    return f"{action}_{side}" or "unknown"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def pull_kalshi(client: KalshiClient) -> Dict[str, Any]:
    print("Fetching historical cutoff…")
    try:
        cutoff = client.signed_get("/trade-api/v2/historical/cutoff")
    except Exception as exc:  # noqa: BLE001
        cutoff = {"error": str(exc)}
    print("  cutoff", cutoff)

    print("Live fills")
    fills = client.paginate("/trade-api/v2/portfolio/fills", "fills")
    print("Historical fills")
    try:
        hfills = client.paginate("/trade-api/v2/historical/fills", "fills")
    except Exception as exc:  # noqa: BLE001
        print("  historical fills failed:", exc)
        hfills = []
    print("Live orders")
    orders = client.paginate("/trade-api/v2/portfolio/orders", "orders")
    print("Historical orders")
    try:
        horders = client.paginate("/trade-api/v2/historical/orders", "orders")
    except Exception as exc:  # noqa: BLE001
        print("  historical orders failed:", exc)
        horders = []
    print("Settlements")
    settlements = client.paginate("/trade-api/v2/portfolio/settlements", "settlements")

    # de-dupe fills by fill_id
    seen = set()
    all_fills = []
    for f in fills + hfills:
        fid = f.get("fill_id") or f.get("trade_id")
        if fid in seen:
            continue
        seen.add(fid)
        all_fills.append(f)
    seen_o = set()
    all_orders = []
    for o in orders + horders:
        oid = o.get("order_id")
        if oid in seen_o:
            continue
        seen_o.add(oid)
        all_orders.append(o)

    return {
        "cutoff": cutoff,
        "fills": all_fills,
        "orders": all_orders,
        "settlements": settlements,
        "counts": {
            "live_fills": len(fills),
            "historical_fills": len(hfills),
            "fills_deduped": len(all_fills),
            "live_orders": len(orders),
            "historical_orders": len(horders),
            "orders_deduped": len(all_orders),
            "settlements": len(settlements),
        },
    }


def enrich_and_match(
    client: KalshiClient,
    raw: Dict[str, Any],
    cache_dir: Path,
    sleep_s: float = 0.05,
) -> Dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    fills = [f for f in raw["fills"] if is_soccer_total_ticker(f.get("ticker") or "")]
    orders = [o for o in raw["orders"] if is_soccer_total_ticker(o.get("ticker") or "")]
    settlements = [s for s in raw["settlements"] if is_soccer_total_ticker(s.get("ticker") or "")]
    print(f"Soccer totals: {len(fills)} fills, {len(orders)} orders, {len(settlements)} settlements")

    tickers = sorted({f.get("ticker") for f in fills if f.get("ticker")})
    events_needed = set()
    markets: Dict[str, Any] = {}
    events: Dict[str, Any] = {}

    mcache = cache_dir / "markets.json"
    ecache = cache_dir / "events.json"
    if mcache.exists():
        markets = json.loads(mcache.read_text())
    if ecache.exists():
        events = json.loads(ecache.read_text())

    for i, t in enumerate(tickers):
        if t not in markets or not markets[t]:
            markets[t] = client.get_market(t)
            time.sleep(sleep_s)
        ev = (markets[t] or {}).get("event_ticker")
        if ev:
            events_needed.add(ev)
        if (i + 1) % 50 == 0:
            print(f"  markets {i+1}/{len(tickers)}")
    mcache.write_text(json.dumps(markets))

    for i, ev in enumerate(sorted(events_needed)):
        if ev not in events or not events[ev]:
            events[ev] = client.get_event(ev)
            time.sleep(sleep_s)
        if (i + 1) % 50 == 0:
            print(f"  events {i+1}/{len(events_needed)}")
    ecache.write_text(json.dumps(events))

    # Unique dates
    parsed_by_ticker = {t: parse_ticker(t) for t in tickers}
    dates = sorted({p["yyyymmdd"] for p in parsed_by_ticker.values() if p.get("yyyymmdd")})
    print(f"Unique match dates: {len(dates)}")

    dcache = cache_dir / "fotmob_days"
    dcache.mkdir(exist_ok=True)
    fotmob_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for i, d in enumerate(dates):
        fp = dcache / f"{d}.json"
        if fp.exists():
            fotmob_by_date[d] = json.loads(fp.read_text())
        else:
            rows = fotmob_matches_for_date(d)
            fp.write_text(json.dumps(rows))
            fotmob_by_date[d] = rows
            time.sleep(0.08)
        if (i + 1) % 20 == 0:
            print(f"  fotmob days {i+1}/{len(dates)}")

    # Match each ticker to a fixture
    details_cache = cache_dir / "fotmob_details"
    details_cache.mkdir(exist_ok=True)
    fixture_by_ticker: Dict[str, Any] = {}
    details_by_id: Dict[str, Any] = {}
    match_stats = Counter()

    for t in tickers:
        p = parsed_by_ticker[t]
        mkt = markets.get(t)
        ev = events.get((mkt or {}).get("event_ticker") or "")
        home, away = parse_event_teams(ev, mkt)
        day = fotmob_by_date.get(p.get("yyyymmdd") or "", [])
        fm = match_fotmob(p, home, away, day)
        if fm:
            match_stats["fotmob"] += 1
            mid = fm.get("id")
            fixture_by_ticker[t] = {
                "source": "fotmob",
                "match_id": mid,
                "home": (fm.get("home") or {}).get("name"),
                "away": (fm.get("away") or {}).get("name"),
                "league": fm.get("_league_name"),
                "kickoff_utc": (fm.get("status") or {}).get("utcTime"),
                "final": (fm.get("status") or {}).get("scoreStr"),
                "home_score": (fm.get("home") or {}).get("score"),
                "away_score": (fm.get("away") or {}).get("score"),
                "match_score": fm.get("_match_score"),
                "raw_status": fm.get("status"),
                "time_local": fm.get("time"),
            }
            if mid is not None:
                key = str(mid)
                dfp = details_cache / f"{key}.json"
                if key not in details_by_id:
                    if dfp.exists():
                        details_by_id[key] = json.loads(dfp.read_text())
                    else:
                        det = fotmob_match_details(int(mid))
                        dfp.write_text(json.dumps(det))
                        details_by_id[key] = det
                        time.sleep(0.08)
        else:
            # ESPN fallback
            slug = ESPN_SLUG_BY_SERIES.get(p["series"])
            if slug and p.get("yyyymmdd"):
                evs = espn_scoreboard(slug, p["yyyymmdd"])
                best = None
                best_s = 0.0
                for evn in evs:
                    name = evn.get("name") or evn.get("shortName") or ""
                    s = 0.0
                    if home:
                        s += _name_score(home, name)
                    if away:
                        s += _name_score(away, name)
                    if s > best_s:
                        best_s, best = s, evn
                if best and best_s >= 0.9:
                    match_stats["espn"] += 1
                    eid = best.get("id")
                    summary = espn_summary(slug, eid) if eid else None
                    comps = (best.get("competitions") or [{}])[0]
                    scores = {c.get("homeAway"): c for c in comps.get("competitors") or []}
                    fixture_by_ticker[t] = {
                        "source": "espn",
                        "match_id": eid,
                        "home": (scores.get("home") or {}).get("team", {}).get("displayName"),
                        "away": (scores.get("away") or {}).get("team", {}).get("displayName"),
                        "league": slug,
                        "kickoff_utc": best.get("date"),
                        "final": None,
                        "home_score": (scores.get("home") or {}).get("score"),
                        "away_score": (scores.get("away") or {}).get("score"),
                        "match_score": best_s,
                        "espn_slug": slug,
                    }
                    if summary:
                        details_by_id[f"espn:{eid}"] = summary
                else:
                    match_stats["unmatched"] += 1
                    fixture_by_ticker[t] = {"source": None, "reason": "no_scoreline"}
            else:
                match_stats["unmatched"] += 1
                fixture_by_ticker[t] = {"source": None, "reason": "no_scoreline"}

    print("Fixture match:", dict(match_stats))

    # Annotate fills
    sett_by_ticker = {s.get("ticker"): s for s in settlements}
    annotated = []
    for f in fills:
        t = f.get("ticker")
        p = parsed_by_ticker.get(t) or parse_ticker(t)
        mkt = markets.get(t) or {}
        ev = events.get(mkt.get("event_ticker") or "") or {}
        fx = fixture_by_ticker.get(t) or {}
        league_name, tier = league_for_series(p["series"], ev)
        if fx.get("league") and not SERIES_LEAGUE.get(p["series"]):
            league_name = fx["league"]
        fill_dt = parse_iso(f.get("created_time"))
        goals: List[Dict[str, Any]] = []
        fotmob_m = None
        if fx.get("source") == "fotmob" and fx.get("match_id") is not None:
            det = details_by_id.get(str(fx["match_id"]))
            if det:
                goals = extract_fotmob_goals(det)
                fotmob_m = {
                    "status": fx.get("raw_status") or (det.get("header") or {}).get("status") or {},
                    "time": fx.get("time_local"),
                }
        elif fx.get("source") == "espn":
            det = details_by_id.get(f"espn:{fx.get('match_id')}")
            if det:
                goals = extract_espn_goals(det)
        kickoff = parse_iso(fx.get("kickoff_utc"))
        minute, phase = soccer_minute_at(fill_dt, kickoff, fotmob_m)
        # 1H markets: clamp displayed minute for rem to first-half goals only
        h, a, tot = goals_before(goals, minute, bool(p.get("is_1h")))
        strike_n = p.get("strike_n")
        rem = (strike_n - tot) if strike_n is not None else None
        no_px = fp_float(f.get("no_price_dollars"))
        yes_px = fp_float(f.get("yes_price_dollars"))
        if no_px <= 0 and yes_px > 0:
            no_px = 1.0 - yes_px
        role = classify_fill_role(f)
        sett = sett_by_ticker.get(t) or {}
        annotated.append({
            "fill_id": f.get("fill_id") or f.get("trade_id"),
            "order_id": f.get("order_id"),
            "ticker": t,
            "created_time": f.get("created_time"),
            "role": role,
            "action": f.get("action"),
            "side": f.get("side"),
            "outcome_side": f.get("outcome_side"),
            "count": fp_float(f.get("count_fp") or f.get("count")),
            "no_price": no_px,
            "no_price_cents": round(no_px * 100.0, 2),
            "yes_price": yes_px,
            "fee": fp_float(f.get("fee_cost")),
            "is_taker": f.get("is_taker"),
            "series": p["series"],
            "league": league_name,
            "tier": tier,
            "is_1h": bool(p.get("is_1h")),
            "over_line": p.get("over_line"),
            "strike_n": strike_n,
            "event_title": ev.get("title"),
            "home": fx.get("home") or parse_event_teams(ev, mkt)[0],
            "away": fx.get("away") or parse_event_teams(ev, mkt)[1],
            "kickoff_utc": fx.get("kickoff_utc"),
            "scoreline_source": fx.get("source"),
            "match_id": fx.get("match_id"),
            "final_score": fx.get("final") or (
                f"{fx.get('home_score')}-{fx.get('away_score')}"
                if fx.get("home_score") is not None else None
            ),
            "minute": None if minute is None else round(float(minute), 2),
            "phase": phase,
            "score_home": h,
            "score_away": a,
            "goals": tot,
            "rem": rem,
            "goal_minutes": [g["minute"] for g in goals],
            "market_result": sett.get("market_result") or mkt.get("result"),
            "expiration_value": mkt.get("expiration_value"),
            "settled_time": sett.get("settled_time"),
        })

    return {
        "fills": annotated,
        "orders": orders,
        "settlements": settlements,
        "markets": {k: _slim_market(v) for k, v in markets.items()},
        "events": {k: _slim_event(v) for k, v in events.items()},
        "fixtures": fixture_by_ticker,
        "match_stats": dict(match_stats),
        "parsed": parsed_by_ticker,
    }


def _slim_market(m: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not m:
        return m
    keys = (
        "ticker", "title", "yes_sub_title", "no_sub_title", "event_ticker",
        "status", "result", "expiration_value", "close_time", "expiration_time",
        "expected_expiration_time", "open_time",
    )
    return {k: m.get(k) for k in keys}


def _slim_event(e: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not e:
        return e
    return {
        "event_ticker": e.get("event_ticker"),
        "title": e.get("title"),
        "sub_title": e.get("sub_title"),
        "series_ticker": e.get("series_ticker"),
        "product_metadata": e.get("product_metadata"),
    }


def realized_pnl_by_ticker(
    fills: List[Dict[str, Any]],
    settlements: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Cashflow P&L per market: buy costs, sell proceeds, settlement payout, fees."""
    by_t: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fills:
        by_t[f["ticker"]].append(f)
    sett = {s.get("ticker"): s for s in settlements}
    out = {}
    for t, rows in by_t.items():
        cash = 0.0
        fees = 0.0
        no_pos = 0.0
        yes_pos = 0.0
        for f in sorted(rows, key=lambda x: x.get("created_time") or ""):
            c = f["count"]
            fees += f.get("fee") or 0.0
            role = f["role"]
            if role == "buy_no":
                cash -= f["no_price"] * c
                no_pos += c
            elif role == "sell_no":
                cash += f["no_price"] * c
                no_pos -= c
            elif role == "buy_yes":
                cash -= f["yes_price"] * c
                yes_pos += c
            elif role == "sell_yes":
                cash += f["yes_price"] * c
                yes_pos -= c
        s = sett.get(t) or {}
        revenue = fp_float(s.get("revenue")) / 100.0  # cents -> dollars
        # Complete sets (equal yes+no inventory) redeem at $1/pair; Kalshi
        # omits that collateral return from `revenue`.
        pairs = 0.0
        if s:
            pairs = min(fp_float(s.get("no_count_fp")), fp_float(s.get("yes_count_fp")))
            revenue += pairs
        result = s.get("market_result") or rows[0].get("market_result")
        if not s and result in ("yes", "no"):
            if result == "yes":
                revenue = max(yes_pos, 0.0) * 1.0
            else:
                revenue = max(no_pos, 0.0) * 1.0
        # Official remaining-inventory P&L (preferred for reports):
        if s:
            official = (
                revenue
                - fp_float(s.get("no_total_cost_dollars"))
                - fp_float(s.get("yes_total_cost_dollars"))
                - fp_float(s.get("fee_cost"))
            )
        else:
            official = cash + revenue - fees
        cash += revenue
        cash -= fees
        out[t] = {
            "ticker": t,
            "pnl": round(official, 4),
            "pnl_cashflow": round(cash, 4),
            "fees": round(fees, 4),
            "revenue": round(revenue, 4),
            "complete_set_pairs": round(pairs, 4),
            "n_fills": len(rows),
            "result": result,
            "league": rows[0].get("league"),
            "tier": rows[0].get("tier"),
            "over_line": rows[0].get("over_line"),
        }
    return out


def classify_exit_trigger(entry: Dict[str, Any], exit_row: Optional[Dict[str, Any]]) -> str:
    goals = entry.get("goal_minutes") or []
    entry_min = entry.get("minute")
    if exit_row is None:
        return "settlement"
    exit_min = exit_row.get("minute")
    if entry_min is not None and exit_min is not None:
        scored = [g for g in goals if entry_min < g <= exit_min + 0.05]
        if scored:
            return "goal"
        if (exit_min - entry_min) >= 8:
            return "time"
        return "price"
    if exit_row.get("created_time") and entry.get("settled_time"):
        return "unknown_flatten"
    return "unknown"


def analyze(enriched: Dict[str, Any]) -> Dict[str, Any]:
    fills = enriched["fills"]
    entries = [f for f in fills if f["role"] == "buy_no"]
    exits = [f for f in fills if f["role"] in ("sell_no", "buy_yes")]
    pnl = realized_pnl_by_ticker(fills, enriched["settlements"])

    by_t = defaultdict(list)
    for f in fills:
        by_t[f["ticker"]].append(f)

    rounds = []
    for t, rows in by_t.items():
        rows = sorted(rows, key=lambda x: x.get("created_time") or "")
        pending: List[Dict[str, Any]] = []
        for f in rows:
            if f["role"] == "buy_no":
                pending.append(f)
            elif f["role"] in ("sell_no", "buy_yes") and pending:
                e = pending.pop(0)
                rounds.append({
                    "ticker": t,
                    "entry": e,
                    "exit": f,
                    "trigger": classify_exit_trigger(e, f),
                    "league": e.get("league"),
                    "tier": e.get("tier"),
                    "entry_minute": e.get("minute"),
                    "entry_rem": e.get("rem"),
                    "entry_price": e.get("no_price"),
                    "entry_size": e.get("count"),
                    "matched": e.get("scoreline_source") is not None,
                })
        for e in pending:
            rounds.append({
                "ticker": t,
                "entry": e,
                "exit": None,
                "trigger": "settlement",
                "league": e.get("league"),
                "tier": e.get("tier"),
                "entry_minute": e.get("minute"),
                "entry_rem": e.get("rem"),
                "entry_price": e.get("no_price"),
                "entry_size": e.get("count"),
                "matched": e.get("scoreline_source") is not None,
            })

    def bucket_minute(m: Optional[float]) -> str:
        if m is None:
            return "unknown"
        if m <= 0:
            return "prekick"
        if m > 120:
            return "postFT/parse_err"
        if m < 45:
            return "00-44"
        if m < 60:
            return "45-59"
        if m < 70:
            return "60-69"
        if m < 80:
            return "70-79"
        if m < 90:
            return "80-89"
        return "90-120"

    def bucket_rem(r: Optional[int]) -> str:
        if r is None:
            return "unknown"
        if r <= 0:
            return "rem<=0"
        if r == 1:
            return "rem=1"
        if r == 2:
            return "rem=2"
        if r == 3:
            return "rem=3"
        return "rem>=4"

    def bucket_px(p: Optional[float]) -> str:
        if p is None:
            return "unknown"
        c = p * 100
        if c < 70:
            return "<70c"
        if c < 80:
            return "70-79c"
        if c < 85:
            return "80-84c"
        if c < 90:
            return "85-89c"
        if c < 95:
            return "90-94c"
        return "95-100c"

    def dist(rows: List[Dict[str, Any]], key_fn) -> Dict[str, Any]:
        c = Counter(key_fn(r) for r in rows)
        return dict(c.most_common())

    # P&L by pattern using market-level P&L attributed to first entry buckets
    first_entry = {}
    for r in rounds:
        first_entry.setdefault(r["ticker"], r)

    def pnl_by(key_fn) -> Dict[str, Dict[str, float]]:
        acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "n": 0, "markets": 0})
        for t, r in first_entry.items():
            k = key_fn(r)
            acc[k]["pnl"] += pnl.get(t, {}).get("pnl", 0.0)
            acc[k]["n"] += 1
            acc[k]["markets"] += 1
        return {k: {"pnl": round(v["pnl"], 2), "n": v["n"]} for k, v in acc.items()}

    matched_entries = [e for e in entries if e.get("scoreline_source")]
    return {
        "n_soccer_fills": len(fills),
        "n_entries_buy_no": len(entries),
        "n_exits": len(exits),
        "n_markets": len(by_t),
        "n_rounds": len(rounds),
        "n_entries_matched": len(matched_entries),
        "match_rate": round(len(matched_entries) / max(len(entries), 1), 3),
        "roles": dict(Counter(f["role"] for f in fills)),
        "entry_minute": dist(matched_entries, lambda e: bucket_minute(e.get("minute"))),
        "entry_rem": dist(matched_entries, lambda e: bucket_rem(e.get("rem"))),
        "entry_price": dist(entries, lambda e: bucket_px(e.get("no_price"))),
        "entry_tier": dist(entries, lambda e: f"tier{e.get('tier')}"),
        "entry_league": dist(entries, lambda e: e.get("league") or "unknown"),
        "entry_size_summary": _size_summary(entries),
        "exit_triggers": dist(rounds, lambda r: r["trigger"]),
        "pnl_total": round(sum(v["pnl"] for v in pnl.values()), 2),
        "pnl_fees": round(sum(v["fees"] for v in pnl.values()), 2),
        "pnl_by_result": _pnl_group(pnl, lambda v: v.get("result") or "unknown"),
        "pnl_by_tier": _pnl_group(pnl, lambda v: f"tier{v.get('tier')}"),
        "pnl_by_league": _pnl_group(pnl, lambda v: v.get("league") or "unknown"),
        "pnl_by_entry_minute": pnl_by(lambda r: bucket_minute(r.get("entry_minute"))),
        "pnl_by_entry_rem": pnl_by(lambda r: bucket_rem(r.get("entry_rem"))),
        "pnl_by_entry_price": pnl_by(lambda r: bucket_px(r.get("entry_price"))),
        "pnl_by_exit_trigger": _pnl_from_rounds(rounds, pnl),
        "entry_minute_quantiles": _quantiles([e.get("minute") for e in matched_entries if e.get("minute") is not None]),
        "entry_rem_quantiles": _quantiles([e.get("rem") for e in matched_entries if e.get("rem") is not None]),
        "entry_price_quantiles": _quantiles([e.get("no_price") * 100 for e in entries if e.get("no_price")]),
        "entry_size_quantiles": _quantiles([e.get("count") for e in entries if e.get("count")]),
        "win_markets": sum(1 for v in pnl.values() if v["pnl"] > 0),
        "lose_markets": sum(1 for v in pnl.values() if v["pnl"] < 0),
        "flat_markets": sum(1 for v in pnl.values() if v["pnl"] == 0),
    }


def _size_summary(entries: List[Dict[str, Any]]) -> Dict[str, float]:
    xs = [e["count"] for e in entries if e.get("count")]
    if not xs:
        return {}
    return {
        "n": len(xs),
        "sum": round(sum(xs), 2),
        "mean": round(sum(xs) / len(xs), 2),
        "min": round(min(xs), 2),
        "max": round(max(xs), 2),
    }


def _quantiles(xs: List[float]) -> Dict[str, float]:
    if not xs:
        return {}
    s = sorted(xs)
    def q(p):
        i = int(round((len(s) - 1) * p))
        return round(float(s[i]), 2)
    return {"n": len(s), "p10": q(0.10), "p25": q(0.25), "p50": q(0.50), "p75": q(0.75), "p90": q(0.90)}


def _pnl_group(pnl: Dict[str, Dict[str, Any]], key_fn) -> Dict[str, Dict[str, float]]:
    acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "n": 0})
    for v in pnl.values():
        k = key_fn(v)
        acc[k]["pnl"] += v["pnl"]
        acc[k]["n"] += 1
    return {k: {"pnl": round(v["pnl"], 2), "n": v["n"]} for k, v in sorted(acc.items(), key=lambda kv: -abs(kv[1]["pnl"]))}


def _pnl_from_rounds(rounds, pnl) -> Dict[str, Dict[str, float]]:
    # attribute each market's P&L to its dominant exit trigger
    trig = {}
    c = Counter()
    for r in rounds:
        trig.setdefault(r["ticker"], r["trigger"])
        c[r["trigger"]] += 1
    acc: Dict[str, Dict[str, float]] = defaultdict(lambda: {"pnl": 0.0, "n_markets": 0, "n_rounds": 0})
    for t, tr in trig.items():
        acc[tr]["pnl"] += pnl.get(t, {}).get("pnl", 0.0)
        acc[tr]["n_markets"] += 1
    for tr, n in c.items():
        acc[tr]["n_rounds"] = n
        acc[tr]["pnl"] = round(acc[tr]["pnl"], 2)
    return dict(acc)


def propose_playbook(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Seed playbook thresholds from observed entry medians and profitable buckets."""
    mq = stats.get("entry_minute_quantiles") or {}
    rq = stats.get("entry_rem_quantiles") or {}
    pq = stats.get("entry_price_quantiles") or {}
    sq = stats.get("entry_size_quantiles") or {}
    pnl_rem = stats.get("pnl_by_entry_rem") or {}
    pnl_px = stats.get("pnl_by_entry_price") or {}
    pnl_min = stats.get("pnl_by_entry_minute") or {}

    # Profitable buckets from this run (used as report annotations only).
    good_rem = [k for k, v in pnl_rem.items() if v.get("pnl", 0) > 0 and k not in ("unknown",)]
    good_px = [k for k, v in pnl_px.items() if v.get("pnl", 0) > 0]
    good_min = [k for k, v in pnl_min.items() if v.get("pnl", 0) > 0 and k not in ("unknown", "prekick", "postFT/parse_err")]

    return {
        "entry_no_price_min_cents": 80,
        "entry_no_price_max_cents": 92,
        "entry_min_minute": 60,
        "entry_max_minute": 92,
        "entry_max_rem": 2,
        "flatten_on_goal": True,
        "flatten_if_rem_drops_to": 1,
        "flatten_if_no_price_drops_cents": 12,
        "no_reentry_after_stop": True,
        "max_contracts_per_match": int(min(sq.get("p75") or 150, 250)),
        "max_contracts_per_day": int(min((sq.get("p75") or 150) * 4, 800)),
        "preferred_tiers": [1, 2],
        "skip_1h_until_more_sample": True,
        "paper_mode_default": True,
        "observed_medians": {
            "minute": mq.get("p50"),
            "rem": rq.get("p50"),
            "no_cents": pq.get("p50"),
            "size": sq.get("p50"),
        },
        "profitable_buckets": {
            "rem": good_rem,
            "price": good_px,
            "minute": good_min,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 0 Kalshi soccer-totals history import")
    parser.add_argument(
        "--out-dir",
        default=str(Path(__file__).resolve().parent / "phase0-out"),
        help="Directory for JSON artifacts",
    )
    parser.add_argument("--skip-pull", action="store_true", help="Reuse raw.json in out-dir")
    parser.add_argument("--skip-match", action="store_true", help="Reuse enriched.json")
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    key_id = os.environ.get("KALSHI_API_KEY_ID")
    pem = os.environ.get("KALSHI_PRIVATE_KEY_PEM")
    if pem:
        pem = pem.replace("\\n", "\n")
    gaps: List[str] = []

    raw_path = out / "raw.json"
    if args.skip_pull and raw_path.exists():
        raw = json.loads(raw_path.read_text())
    else:
        if not key_id or not pem:
            gaps.append("Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PEM")
            raw = {"fills": [], "orders": [], "settlements": [], "counts": {}, "cutoff": None}
        else:
            try:
                client = KalshiClient(key_id, pem)
                raw = pull_kalshi(client)
            except Exception as exc:  # noqa: BLE001
                gaps.append(f"Kalshi pull failed: {exc}")
                raw = {"fills": [], "orders": [], "settlements": [], "counts": {}, "cutoff": None, "error": str(exc)}
                client = None  # type: ignore
        raw_path.write_text(json.dumps(raw))
        print("wrote", raw_path)

    client = None
    if key_id and pem:
        client = KalshiClient(key_id, pem)

    enr_path = out / "enriched.json"
    if args.skip_match and enr_path.exists():
        enriched = json.loads(enr_path.read_text())
    else:
        if client is None:
            gaps.append("Cannot match scorelines without Kalshi market metadata (no credentials)")
            enriched = {
                "fills": [], "orders": [], "settlements": [],
                "markets": {}, "events": {}, "fixtures": {},
                "match_stats": {}, "parsed": {},
            }
        else:
            try:
                enriched = enrich_and_match(client, raw, out / "cache")
            except Exception as exc:  # noqa: BLE001
                gaps.append(f"Enrich/match failed: {exc}")
                enriched = {
                    "fills": [], "orders": raw.get("orders") or [],
                    "settlements": raw.get("settlements") or [],
                    "markets": {}, "events": {}, "fixtures": {},
                    "match_stats": {"error": str(exc)}, "parsed": {},
                }
        # write a slimmer enriched (fills + stats, not huge details)
        slim = {
            "fills": enriched.get("fills"),
            "settlements": [
                {
                    "ticker": s.get("ticker"),
                    "event_ticker": s.get("event_ticker"),
                    "market_result": s.get("market_result"),
                    "no_count_fp": s.get("no_count_fp"),
                    "no_total_cost_dollars": s.get("no_total_cost_dollars"),
                    "yes_count_fp": s.get("yes_count_fp"),
                    "yes_total_cost_dollars": s.get("yes_total_cost_dollars"),
                    "revenue": s.get("revenue"),
                    "fee_cost": s.get("fee_cost"),
                    "settled_time": s.get("settled_time"),
                }
                for s in (enriched.get("settlements") or [])
            ],
            "fixtures": enriched.get("fixtures"),
            "match_stats": enriched.get("match_stats"),
            "markets": enriched.get("markets"),
            "events": enriched.get("events"),
        }
        enr_path.write_text(json.dumps(slim))
        print("wrote", enr_path)
        # keep full object for analyze
        if "parsed" not in enriched:
            enriched = {**enriched, **slim}

    stats = analyze(enriched)
    playbook = propose_playbook(stats)
    unmatched = stats["n_entries_buy_no"] - stats["n_entries_matched"]
    if unmatched:
        gaps.append(f"{unmatched} buy-No entries had no FotMob/ESPN scoreline")
    if stats["n_soccer_fills"] == 0:
        gaps.append("No soccer-total fills in the pulled history")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kalshi_counts": raw.get("counts"),
        "cutoff": raw.get("cutoff"),
        "known_soccer_series_in_repo": SOCCER_SERIES_TICKERS,
        "stats": stats,
        "playbook": playbook,
        "gaps": gaps,
        "sample_entries": [
            {k: e.get(k) for k in (
                "ticker", "created_time", "home", "away", "league", "tier",
                "minute", "phase", "score_home", "score_away", "goals", "rem",
                "over_line", "no_price_cents", "count", "scoreline_source",
                "final_score", "market_result",
            )}
            for e in (enriched.get("fills") or [])
            if e.get("role") == "buy_no"
        ][:25],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({
        "counts": raw.get("counts"),
        "stats_head": {k: stats[k] for k in (
            "n_soccer_fills", "n_entries_buy_no", "n_entries_matched",
            "match_rate", "pnl_total", "win_markets", "lose_markets",
        ) if k in stats},
        "entry_minute": stats.get("entry_minute"),
        "entry_rem": stats.get("entry_rem"),
        "entry_price": stats.get("entry_price"),
        "exit_triggers": stats.get("exit_triggers"),
        "playbook": playbook,
        "gaps": gaps,
        "out": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
