"""Quarter markets (and full-game spreads): where does one quarter's total and margin finish?

Same idea as the full-game model, one quarter at a time:

    quarter total  = points so far this quarter + scoring rate x seconds left
    quarter margin = margin so far this quarter + the favourite's edge x seconds left

each with a spread that shrinks to nothing as the clock runs out. Kalshi's
fourth-quarter markets exclude overtime, so there is no overtime branch here,
but a close fourth still gets the late foul-game boost.

Quarters are not equal shares of a game. First quarters run a little hot and
fourths a little cold (starters rest, the clock gets milked), so each quarter
takes its own share of the pregame total. The shares are league-level
starting points, like the rest of the model's constants.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ..domain import QUARTER_SECONDS, REG_SECONDS, Game, Rung
from .totals import (
    LATE_BASE,
    LATE_BOOST,
    LATE_EXTRA_SD,
    LATE_WINDOW,
    LEAGUE_TOTAL,
    MARGIN_VAR_PER_SEC,
    PRIOR_WEIGHT_SECONDS,
    VAR_PER_SEC,
    implied_total,
    _phi,
    p_close_at_late_window,
)

# Share of the pregame total scored in each quarter (the remainder is overtime).
QUARTER_SHARE = {1: 0.256, 2: 0.254, 3: 0.250, 4: 0.236}
PREGAME_SD = 2.0  # how unsure the pregame total leaves a quarter's scoring level, in points
MIN_SD = 0.35


def _home_edge_per_second(game: Game) -> float:
    """Points per second the home side is expected to gain, from the sportsbook spread."""
    spread = game.fanduel.spread if game.fanduel and game.fanduel.spread is not None else None
    if spread is None:
        return 1.5 / REG_SECONDS  # ordinary home-court edge
    return -spread / REG_SECONDS  # spread -4.5 means the home side is 4.5 better over a game


def project_quarter(game: Game, q: int) -> Optional[dict[str, float]]:
    """Mean and spread of quarter q's final total and home-minus-away margin. None once final."""
    status = game.quarter_status(q)
    if status == "final":
        return None
    secs = game.quarter_seconds_left(q)
    home_pts, away_pts = game.quarter_points(q)

    pregame = game.pregame_total or LEAGUE_TOTAL
    prior_rate = QUARTER_SHARE[q] * pregame / QUARTER_SECONDS
    # Lean a little on how this game has actually been scoring, as the full-game model does.
    elapsed = game.elapsed if game.state == "live" else 0.0
    if elapsed > 0 and game.period <= 4:
        played = sum(QUARTER_SHARE[i] for i in range(1, game.period)) + QUARTER_SHARE[game.period] * (
            1 - max(game.clock_seconds, 0.0) / QUARTER_SECONDS
        )
        expected_so_far = played * pregame
        pace = game.total / expected_so_far if expected_so_far > 0 else 1.0
        w = elapsed / (elapsed + PRIOR_WEIGHT_SECONDS)
        rate = prior_rate * (1 - w + w * pace)
    else:
        rate = prior_rate

    total_var = VAR_PER_SEC * secs
    remaining = rate * secs
    if q == 4:
        # The end of a close fourth is a foul game. Margin here is the game's margin.
        closeness = p_close_at_late_window(game.margin, game.seconds_remaining) if status == "live" else 0.35
        late = min(secs, LATE_WINDOW)
        remaining = rate * (secs - late) + rate * late * (1.0 + LATE_BASE + LATE_BOOST * closeness)
        total_var += closeness * (LATE_EXTRA_SD * late / LATE_WINDOW) ** 2
    if status == "upcoming":
        total_var += PREGAME_SD**2

    return {
        "total_mean": round(home_pts + away_pts + remaining, 1),
        "total_sd": round(max(math.sqrt(total_var), MIN_SD), 2),
        "margin_mean": round(home_pts - away_pts + _home_edge_per_second(game) * secs, 2),
        "margin_sd": round(max(math.sqrt(MARGIN_VAR_PER_SEC * secs), MIN_SD), 2),
    }


def p_no(rung: Rung, game: Game, q: int, proj: Optional[dict[str, float]]) -> float:
    """Probability the NO side of a quarter market (or a full-game spread) wins (under, or 'does not cover')."""
    if proj is None:
        value = game.settle_value(rung.segment, rung.kind, rung.team)
        return 1.0 if value is not None and value < rung.strike else 0.0
    if rung.kind == "total":
        home_pts, away_pts = game.quarter_points(q)
        if home_pts + away_pts > rung.strike:
            return 0.0
        return _phi((rung.strike - proj["total_mean"]) / proj["total_sd"])
    sign = 1.0 if rung.team == game.home.abbr else -1.0
    return _phi((rung.strike - sign * proj["margin_mean"]) / proj["margin_sd"])


def project_game_margin(game: Game) -> Optional[dict[str, float]]:
    """Mean and spread of the full game's final home-minus-away margin. None once final.

    Kalshi's full-game spreads count overtime, so in overtime the margin keeps
    moving over the overtime clock; at the end of a tied fourth the bell curve
    is centred on zero and simply waits for overtime to pull it apart.
    """
    if game.state == "final":
        return None
    secs = game.seconds_remaining if game.period <= 4 else max(game.clock_seconds, 0.0)
    now = game.home.score - game.away.score if game.state == "live" else 0
    return {
        "margin_mean": round(now + _home_edge_per_second(game) * secs, 2),
        "margin_sd": round(max(math.sqrt(MARGIN_VAR_PER_SEC * secs), MIN_SD), 2),
    }


def price_game_spreads(game: Game) -> None:
    """Reprice the full-game spread markets in place."""
    proj = project_game_margin(game)
    game.margin_projection = proj
    for r in game.spreads:
        r.p_under = round(p_no(r, game, 0, proj), 4)
        r.edge_under = round(r.p_under - r.no_ask / 100.0, 4) if r.no_ask else None
        r.edge_over = round((1 - r.p_under) - r.yes_ask / 100.0, 4) if r.yes_ask else None


def refresh_quarters(game: Game) -> None:
    """Recompute each quarter's projection and reprice its markets in place."""
    view: list[dict[str, Any]] = []
    for q in (1, 2, 3, 4):
        segment = f"q{q}"
        proj = project_quarter(game, q)
        home_pts, away_pts = game.quarter_points(q)
        view.append(
            {
                "segment": segment,
                "label": f"Q{q}",
                "status": game.quarter_status(q),
                "home_points": home_pts,
                "away_points": away_pts,
                "seconds_remaining": round(game.quarter_seconds_left(q)),
                "projection": proj,
            }
        )
        for rungs in game.quarter_markets.get(segment, {}).values():
            for r in rungs:
                r.p_under = round(p_no(r, game, q, proj), 4)
                r.edge_under = round(r.p_under - r.no_ask / 100.0, 4) if r.no_ask else None
                r.edge_over = round((1 - r.p_under) - r.yes_ask / 100.0, 4) if r.yes_ask else None
    game.quarter_view = view


def implied_quarter_total(rungs: list[Rung]) -> Optional[float]:
    """The quarter total Kalshi's own prices put at 50/50."""
    return implied_total(sorted(rungs, key=lambda r: r.strike))


def implied_margin(rungs: list[Rung], home: str) -> Optional[float]:
    """The home margin (home minus away) Kalshi's spread prices put at 50/50.

    A rung backing the home team by `strike` says P(margin > strike) = mid. A rung backing
    the away team by `strike` says P(margin < -strike) = mid, so P(margin > -strike) = 1 - mid.
    """
    pts = sorted(
        (r.strike, (r.yes_bid + r.yes_ask) / 200.0) if r.team == home else (-r.strike, 1 - (r.yes_bid + r.yes_ask) / 200.0)
        for r in rungs
        if r.yes_bid and r.yes_ask and r.team
    )
    for (lo_x, lo_p), (hi_x, hi_p) in zip(pts, pts[1:]):
        if lo_p >= 0.5 >= hi_p and lo_p != hi_p:
            return round((lo_x + (lo_p - 0.5) / (lo_p - hi_p) * (hi_x - lo_x)) * 2) / 2
    return None
