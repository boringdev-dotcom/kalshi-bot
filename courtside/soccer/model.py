"""Goals model: where does a match finish?

Each side's goals are Poisson, independent of the other's. Before kickoff, each side's
expected goals are fitted to the bookmaker's odds (DraftKings, via ESPN): the total
line sets how many goals, the 1X2 prices set who scores them. Without odds, Kalshi's
own winner and total prices are used, and failing that the league's average.

In play, what is still to come is that expectation scaled by the share of the match
left. Goals come a little more often late (tired legs, chasing teams), so the share is
weighted toward the end, and each half runs a couple of minutes past its 45 for
stoppage time. A red card cuts the short side's rate and lifts the other side's.

These are league-level starting points, like the NBA model's constants: good enough
to price every line consistently, not a claim to beat the market on their own.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from .domain import Match, SMarket, outcome_yes

HALF_END = (47.0, 95.0)  # expected match minute each half ends, stoppage time included
LATE_TILT = 0.4  # the scoring rate at 90' is this much higher than at kickoff
RED_OWN = 0.75  # a side's scoring rate per red card it has
RED_OTHER = 1.2  # the other side's rate per red card the first one has
MAX_GOALS = 12
DEFAULT_HOME_SHARE = 0.55


def _weight(a: float, b: float) -> float:
    """Scoring weight of match minutes a..b (rate 1 + LATE_TILT * t/90)."""
    if b <= a:
        return 0.0
    return (b - a) + LATE_TILT / 180.0 * (b * b - a * a)


FIRST_HALF = _weight(0.0, HALF_END[0])
SECOND_HALF = _weight(45.0, HALF_END[1])
FULL = FIRST_HALF + SECOND_HALF


def remaining_share(match: Match, segment: str) -> float:
    """Share of the whole match's expected goals still to come within a segment."""
    if match.state == "pre":
        return 1.0 if segment == "match" else FIRST_HALF / FULL
    if match.state == "final" or (segment == "1h" and match.first_half_over):
        return 0.0
    t = match.minute
    if match.halftime:
        return SECOND_HALF / FULL if segment == "match" else 0.0
    if match.period <= 1:
        # Past the expected end of the half, allow for about one more minute of play.
        first = _weight(t, HALF_END[0]) if t < HALF_END[0] - 1 else _weight(t, t + 1) * 0.6
        if segment == "1h":
            return first / FULL
        return (first + SECOND_HALF) / FULL
    rest = _weight(t, HALF_END[1]) if t < HALF_END[1] - 1 else _weight(t, t + 1) * 0.6
    return rest / FULL


def poisson(lam: float, k: int) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def _pmf(lam: float) -> list[float]:
    return [poisson(lam, k) for k in range(MAX_GOALS + 1)]


def grid(lam_home: float, lam_away: float) -> list[tuple[int, int, float]]:
    """(home goals, away goals, probability) for goals still to come."""
    ph, pa = _pmf(max(lam_home, 1e-9)), _pmf(max(lam_away, 1e-9))
    return [(i, j, ph[i] * pa[j]) for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)]


def results(lam_home: float, lam_away: float) -> tuple[float, float, float]:
    """P(home win), P(draw), P(away win) from scratch."""
    h = d = a = 0.0
    for i, j, p in grid(lam_home, lam_away):
        if i > j:
            h += p
        elif i == j:
            d += p
        else:
            a += p
    return h, d, a


def p_total_over(lam: float, line: float) -> float:
    return 1.0 - sum(poisson(lam, k) for k in range(int(math.floor(line)) + 1))


def _bisect(f, lo: float, hi: float, target: float, steps: int = 40) -> float:
    """x in [lo, hi] with f(x) = target, for f increasing."""
    for _ in range(steps):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def fit(p_home: float, p_away: float, total: Optional[float] = None) -> tuple[float, float]:
    """Expected goals for each side matching a 1X2 price and an expected total."""
    total = total or 2.7
    edge = p_home - p_away

    def edge_at(share: float) -> float:
        h, _, a = results(total * share, total * (1 - share))
        return h - a

    share = _bisect(edge_at, 0.03, 0.97, edge)
    return total * share, total * (1 - share)


def total_from_line(line: float, p_over: float) -> float:
    """Expected goals that put P(total > line) at p_over."""
    return _bisect(lambda lam: p_total_over(lam, line), 0.3, 7.0, min(max(p_over, 0.02), 0.98))


def american_to_p(odds: Any) -> Optional[float]:
    try:
        o = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def devig(*ps: Optional[float]) -> Optional[list[float]]:
    if any(p is None for p in ps):
        return None
    s = sum(ps)  # type: ignore[arg-type]
    return [p / s for p in ps] if s > 0 else None  # type: ignore[operator]


def prior_from_odds(odds: dict[str, Any]) -> Optional[tuple[float, float]]:
    """Pre-match expected goals from ESPN's odds block (moneyline 1X2 and the total)."""
    ml = odds.get("moneyline") or {}
    pick = lambda side: ((ml.get(side) or {}).get("close") or (ml.get(side) or {}).get("open") or {}).get("odds")  # noqa: E731
    three = devig(american_to_p(pick("home")), american_to_p(pick("draw")), american_to_p(pick("away")))
    if not three:
        return None
    total = None
    line = odds.get("overUnder")
    tot = odds.get("total") or {}
    over = ((tot.get("over") or {}).get("close") or {}).get("odds")
    under = ((tot.get("under") or {}).get("close") or {}).get("odds")
    pair = devig(american_to_p(over), american_to_p(under))
    if line is not None and pair:
        total = total_from_line(float(line), pair[0])
    elif line is not None:
        total = float(line)
    return fit(three[0], three[2], total)


def _mid(m: SMarket) -> Optional[float]:
    if m.yes_bid and m.yes_ask:
        return (m.yes_bid + m.yes_ask) / 200.0
    return None


def prior_from_kalshi(markets: list[SMarket]) -> Optional[tuple[float, float]]:
    """Pre-match expected goals from Kalshi's own full-match winner and total prices."""
    win = {m.outcome: _mid(m) for m in markets if m.segment == "match" and m.kind == "winner"}
    three = devig(win.get("home"), win.get("tie"), win.get("away"))
    if not three:
        return None
    totals = sorted((m for m in markets if m.segment == "match" and m.kind == "total" and _mid(m) is not None),
                    key=lambda m: abs((_mid(m) or 0) - 0.5))
    total = total_from_line(totals[0].strike or 2.5, _mid(totals[0]) or 0.5) if totals else None
    return fit(three[0], three[2], total)


def remaining_goals(match: Match, segment: str) -> tuple[float, float]:
    """Expected goals still to come for each side in a segment."""
    lam_h, lam_a = match.lam_home or 1.4, match.lam_away or 1.2
    share = remaining_share(match, segment)
    rh = lam_h * share * RED_OWN**match.home.red_cards * RED_OTHER**match.away.red_cards
    ra = lam_a * share * RED_OWN**match.away.red_cards * RED_OTHER**match.home.red_cards
    return rh, ra


def price(match: Match) -> None:
    """Set the model's probability on every market, and the match projection."""
    cache: dict[str, list[tuple[int, int, float]]] = {}
    for seg in ("match", "1h"):
        cache[seg] = grid(*remaining_goals(match, seg))
    for m in match.markets:
        settled = match.settles_yes(m)
        if settled is not None:
            m.p_yes = 1.0 if settled else 0.0
            continue
        h, a = match.segment_score(m.segment)
        m.p_yes = round(sum(p for i, j, p in cache[m.segment] if outcome_yes(m, h + i, a + j)), 4)

    proj: dict[str, Any] = {}
    for seg in ("match", "1h"):
        rh, ra = remaining_goals(match, seg)
        h, a = match.segment_score(seg)
        ph = pd = pa = 0.0
        for i, j, p in cache[seg]:
            if h + i > a + j:
                ph += p
            elif h + i == a + j:
                pd += p
            else:
                pa += p
        proj[seg] = {"home_goals": round(h + rh, 2), "away_goals": round(a + ra, 2), "total": round(h + a + rh + ra, 2),
                     "p_home": round(ph, 3), "p_draw": round(pd, 3), "p_away": round(pa, 3)}
    match.projection = proj
