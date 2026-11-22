"""Live NBA total-points model.

Answers one question: given the score, the clock and the margin, what is the
distribution of the final total? Everything the agent does (fair value for each
Kalshi strike, edge, win probability of an open position, risk flags) is read
off this distribution.

The final total is modelled as

    final = current + remaining_regulation_points (+ overtime_points with prob p_ot)

* The remaining scoring rate shrinks the game's observed pace toward a prior
  (the pregame total), trusting the game more as it goes on.
* The last two minutes of a close game score faster per second of game clock
  (intentional fouls, timeouts, quick threes), so the rate is boosted by the
  probability that the game is still close when it gets there.
* Overtime is the tail that kills unders: a tie after regulation adds about 21
  points. p_ot comes from the margin distribution at the buzzer.

The constants are reasonable league-level starting points, not fitted values;
the learner corrects for where they are off by tracking realised outcomes.
"""

from __future__ import annotations

import math
from typing import Optional

from ..domain import REG_SECONDS, Game, Projection, Risk, Rung

LEAGUE_TOTAL = 228.0
VAR_PER_SEC = 0.12  # total-points variance per game second (sd ~18.5 over a game)
MARGIN_VAR_PER_SEC = 0.07  # margin variance per game second (sd ~14 over a game)
# How much the pregame total outweighs this game's own pace. Scoring through
# three quarters is mostly luck around a sharp closing line, so the prior is
# worth several games of evidence: at the end of Q3 observed pace gets ~18%.
PRIOR_WEIGHT_SECONDS = 10000.0
LATE_WINDOW = 120.0
LATE_BASE = 0.12  # every game speeds up a little inside two minutes
LATE_BOOST = 0.42  # and a close one much more: fouls, timeouts, quick threes
CLOSE_MARGIN = 8.0
TIE_PLAY_FACTOR = 1.8  # teams trailing late play for the tie, fattening P(tie)
# Points a pregame total already bakes in for late fouling and overtime; the
# underlying scoring rate is the line minus this.
LINE_EXTRAS = 3.5
OT_MEAN = 24.5  # one overtime is ~21 points; this allows for the occasional second one
OT_SD = 9.5
LATE_EXTRA_SD = 3.5  # extra spread when the last two minutes turn into a foul game
MARKET_BLEND = 0.5  # weight on a live sportsbook total when one is available


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float, sd: float) -> float:
    return math.exp(-0.5 * (x / sd) ** 2) / (sd * math.sqrt(2.0 * math.pi))


def p_close_at_late_window(margin: float, secs_left: float) -> float:
    """Probability the margin is within CLOSE_MARGIN when two minutes remain."""
    until = secs_left - LATE_WINDOW
    if until <= 0:
        return 1.0 if margin <= CLOSE_MARGIN else max(0.0, 1.0 - (margin - CLOSE_MARGIN) / 6.0)
    sd = math.sqrt(MARGIN_VAR_PER_SEC * until)
    return _phi((CLOSE_MARGIN - margin) / sd) - _phi((-CLOSE_MARGIN - margin) / sd)


def p_overtime(margin: float, secs_left: float) -> float:
    if secs_left <= 0:
        return 1.0 if margin == 0 else 0.0
    sd = math.sqrt(MARGIN_VAR_PER_SEC * secs_left)
    return min(0.9, _pdf(margin, sd) * TIE_PLAY_FACTOR)


class TotalDist:
    """Distribution of the final total as a small mixture of normals.

    Each branch is (weight, mean, sd). In regulation there are three:
    the game is not close late; it is close late (fouls, no overtime); it goes
    to overtime. Keeping them separate, instead of one averaged bell curve,
    is what gives the right tail its real weight, and the right tail is the
    only thing that hurts an under.
    """

    def __init__(self, branches: list[tuple[float, float, float]], p_ot: float, current: float, pace: float):
        self.branches = [(w, mu, max(sd, 0.35)) for w, mu, sd in branches if w > 1e-9]
        self.p_ot = p_ot
        self.current = current
        self.pace = pace

    @property
    def mean(self) -> float:
        return sum(w * mu for w, mu, _ in self.branches)

    @property
    def sd(self) -> float:
        mean = self.mean
        return math.sqrt(max(sum(w * (sd**2 + mu**2) for w, mu, sd in self.branches) - mean**2, 0.0))

    def p_under(self, strike: float) -> float:
        if self.current > strike:
            return 0.0
        return sum(w * _phi((strike - mu) / sd) for w, mu, sd in self.branches)

    def shifted(self, delta: float) -> "TotalDist":
        return TotalDist([(w, max(mu + delta, self.current), sd) for w, mu, sd in self.branches], self.p_ot, self.current, self.pace)

    def projection(self) -> Projection:
        return Projection(mean=round(self.mean, 1), sd=round(self.sd, 1), p_ot=round(self.p_ot, 3), pace=round(self.pace, 1))


def distribution(
    total: float,
    secs_left: float,
    margin: float,
    period: int = 4,
    pregame_total: Optional[float] = None,
    market_line: Optional[float] = None,
    ot_secs_left: float = 0.0,
) -> TotalDist:
    prior_rate = ((pregame_total or LEAGUE_TOTAL) - LINE_EXTRAS) / REG_SECONDS

    if period > 4:
        # Regulation is over; the current overtime remains, and maybe another.
        mu = total + prior_rate * 1.1 * ot_secs_left
        sd = math.sqrt(VAR_PER_SEC * 1.3 * ot_secs_left + 1.0)
        again = p_overtime(margin, ot_secs_left)
        branches = [(1 - again, mu, sd), (again, mu + OT_MEAN, math.sqrt(sd**2 + OT_SD**2))]
        return TotalDist(branches, again, total, total / 53 * 48)

    elapsed = REG_SECONDS - secs_left
    if elapsed <= 0:
        mu = pregame_total or LEAGUE_TOTAL
        return TotalDist([(1.0, mu, math.sqrt(VAR_PER_SEC * REG_SECONDS))], 0.06, total, mu)

    observed_rate = total / elapsed
    w = elapsed / (elapsed + PRIOR_WEIGHT_SECONDS)
    rate = w * observed_rate + (1 - w) * prior_rate

    closeness = p_close_at_late_window(margin, secs_left)
    p_ot = min(p_overtime(margin, secs_left), closeness)
    late = min(secs_left, LATE_WINDOW)
    normal = secs_left - late
    blowout_drag = 0.95 if (period >= 4 and margin >= 18) else 1.0

    calm_mu = total + rate * blowout_drag * (normal + late * (1.0 + LATE_BASE))
    calm_sd = math.sqrt(VAR_PER_SEC * secs_left)
    tense_mu = calm_mu + rate * late * LATE_BOOST
    tense_sd = math.sqrt(calm_sd**2 + (LATE_EXTRA_SD * late / LATE_WINDOW) ** 2)
    dist = TotalDist(
        [
            (1 - closeness, calm_mu, calm_sd),
            (closeness - p_ot, tense_mu, tense_sd),
            (p_ot, tense_mu + OT_MEAN, math.sqrt(tense_sd**2 + OT_SD**2)),
        ],
        p_ot,
        total,
        observed_rate * REG_SECONDS,
    )
    if market_line is not None and secs_left > 0:
        # A live sportsbook total already prices pace, fouls and OT. Pull our
        # all-in mean toward it rather than trusting either alone.
        dist = dist.shifted(MARKET_BLEND * (market_line - dist.mean))
    return dist


def game_distribution(game: Game) -> Optional[TotalDist]:
    if game.state == "final":
        return None
    line = game.fanduel.total_line if (game.fanduel and game.fanduel.live) else None
    return distribution(
        total=game.total,
        secs_left=game.seconds_remaining,
        margin=game.margin,
        period=max(game.period, 1),
        pregame_total=game.pregame_total,
        market_line=line if game.state == "live" else None,
        ot_secs_left=game.clock_seconds if game.period > 4 else 0.0,
    )


def assess_risk(game: Game, dist: Optional[TotalDist]) -> Risk:
    """Game-level flags for anyone holding an under."""
    if game.state != "live" or dist is None:
        return Risk()
    flags: list[str] = []
    level = "low"
    mins = game.minutes_left
    if game.period > 4:
        flags.append("overtime is being played, which adds points fast")
        level = "high"
    elif game.period == 4:
        if dist.p_ot >= 0.12:
            flags.append(f"about a {dist.p_ot:.0%} chance of overtime ({game.margin}-point game, {game.clock} left), and overtime adds 20-plus points")
            level = "high"
        elif dist.p_ot >= 0.05:
            flags.append(f"about a {dist.p_ot:.0%} chance of overtime")
            level = "medium"
        if mins <= 3 and game.margin <= 6:
            flags.append(f"a {game.margin}-point game inside the last 3:00, so expect fouls and fast scoring")
            level = "high" if game.margin <= 3 else max(level, "medium", key=_rank)
    if dist.pace >= (game.pregame_total or LEAGUE_TOTAL) + 14:
        flags.append(f"scoring is running hot, on pace for {dist.pace:.0f} against {game.pregame_total or LEAGUE_TOTAL:.0f} expected")
        level = max(level, "medium", key=_rank)
    return Risk(level=level, flags=flags)


def _rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}[level]


def price_ladder(game: Game, dist: Optional[TotalDist]) -> None:
    """Fill model probability and edge on every rung in place."""
    for r in game.ladder:
        _price_rung(r, game, dist)


def _price_rung(r: Rung, game: Game, dist: Optional[TotalDist]) -> None:
    if dist is None:
        r.p_under = 1.0 if game.total < r.strike else 0.0
    else:
        r.p_under = round(dist.p_under(r.strike), 4)
    r.edge_under = round(r.p_under - r.no_ask / 100.0, 4) if r.no_ask else None
    r.edge_over = round((1 - r.p_under) - r.yes_ask / 100.0, 4) if r.yes_ask else None


def implied_total(ladder: list[Rung]) -> Optional[float]:
    """The total the Kalshi ladder itself implies: the strike priced at 50/50."""
    pts = [(r.strike, (r.yes_bid + r.yes_ask) / 2.0) for r in ladder if r.yes_bid and r.yes_ask]
    for (lo_strike, lo_mid), (hi_strike, hi_mid) in zip(pts, pts[1:]):
        if lo_mid >= 50 >= hi_mid and lo_mid != hi_mid:
            return round(lo_strike + (lo_mid - 50) / (lo_mid - hi_mid) * (hi_strike - lo_strike), 1)
    return None


def refresh_game(game: Game) -> Optional[TotalDist]:
    """Recompute projection, risk and ladder pricing for a game."""
    from .quarters import price_game_spreads, refresh_quarters  # here to avoid a circular import

    dist = game_distribution(game)
    game.projection = dist.projection() if dist else None
    game.risk = assess_risk(game, dist)
    price_ladder(game, dist)
    price_game_spreads(game)
    refresh_quarters(game)
    return dist
