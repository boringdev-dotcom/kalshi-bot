"""Simulated NBA games with a synthetic Kalshi totals ladder and sportsbook line.

This is a sandbox: it lets the desk and the agent run with no live games, and
gives the learner a gym to practise in. It is NOT evidence about real markets.

What is simulated:

* Scoring is possession by possession. Each game has hidden traits the agent
  cannot see directly (true pace and efficiency, how early the trailing team
  starts fouling, how hard a blowout coasts), so the public model is honestly
  wrong in game-specific ways, as it is in real life.
* A tie at the end of regulation goes to a 5-minute overtime.
* The market maker prices each strike off a sharper projection than the
  agent's (it knows a little about the true pace), adds slow-moving noise, quotes a
  1-4c spread, and charges a small premium on far-out overs (the
  favourite/longshot bias). That premium is an assumption of this sandbox.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Optional

from ..domain import OT_SECONDS, QUARTER_SECONDS, FanDuelOdds, Game, Rung, Team, fmt_clock, now_iso
from ..model.totals import LINE_EXTRAS, _phi, distribution

TEAMS = [
    ("ATL", "Atlanta Hawks", "e03a3e"), ("BOS", "Boston Celtics", "007a33"),
    ("BKN", "Brooklyn Nets", "9ea2a2"), ("CHA", "Charlotte Hornets", "00788c"),
    ("CHI", "Chicago Bulls", "ce1141"), ("CLE", "Cleveland Cavaliers", "860038"),
    ("DAL", "Dallas Mavericks", "00538c"), ("DEN", "Denver Nuggets", "fec524"),
    ("DET", "Detroit Pistons", "c8102e"), ("GSW", "Golden State Warriors", "ffc72c"),
    ("HOU", "Houston Rockets", "ce1141"), ("IND", "Indiana Pacers", "fdbb30"),
    ("LAC", "LA Clippers", "c8102e"), ("LAL", "Los Angeles Lakers", "fdb927"),
    ("MEM", "Memphis Grizzlies", "5d76a9"), ("MIA", "Miami Heat", "98002e"),
    ("MIL", "Milwaukee Bucks", "00471b"), ("MIN", "Minnesota Timberwolves", "236192"),
    ("NOP", "New Orleans Pelicans", "b4975a"), ("NYK", "New York Knicks", "f58426"),
    ("OKC", "Oklahoma City Thunder", "007ac1"), ("ORL", "Orlando Magic", "0077c0"),
    ("PHI", "Philadelphia 76ers", "006bb6"), ("PHX", "Phoenix Suns", "e56020"),
    ("POR", "Portland Trail Blazers", "e03a3e"), ("SAC", "Sacramento Kings", "5a2d81"),
    ("SAS", "San Antonio Spurs", "c4ced4"), ("TOR", "Toronto Raptors", "ce1141"),
    ("UTA", "Utah Jazz", "f9a01b"), ("WAS", "Washington Wizards", "e31837"),
]

POINTS_GIVEN_SCORE = [(1, 0.08), (2, 0.60), (3, 0.28), (4, 0.04)]
MEAN_GIVEN_SCORE = sum(p * w for p, w in POINTS_GIVEN_SCORE)
TYING_SHOT = {1: 0.33, 2: 0.30, 3: 0.18}  # chance a 1-3 pt deficit is erased at the horn
TAIL_PREMIUM = 0.028  # extra price on far-out overs (favourite/longshot bias)


def _american(p: float) -> int:
    p = min(max(p, 0.02), 0.98)
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


class SimGame:
    """One simulated game plus the hidden state that drives it."""

    _counter = 0

    def __init__(self, rng: random.Random, tip_in: float = 0.0):
        SimGame._counter += 1
        self.rng = rng
        away, home = rng.sample(TEAMS, 2)
        line = round(rng.gauss(229, 7)) + 0.5
        self.game = Game(
            id=f"sim-{SimGame._counter}",
            home=Team(abbr=home[0], name=home[1], color=home[2]),
            away=Team(abbr=away[0], name=away[1], color=away[2]),
            pregame_total=line,
            simulated=True,
            event_ticker=f"SIM-{away[0]}{home[0]}-{SimGame._counter}",
        )
        # Hidden traits.
        # The line already includes late fouling and overtime, so base scoring sits a little under it.
        self.true_total = rng.gauss(line - LINE_EXTRAS, 5)
        self.possessions = rng.gauss(200, 7)
        self.home_share = 0.5 + rng.gauss(0.008, 0.012)
        self.foul_start = rng.uniform(22, 75)  # seconds left when the trailing team starts fouling
        self.coast = rng.uniform(0.84, 1.0)  # blowout pace multiplier in Q4
        self.hot = 1.0  # slow-moving shooting streak
        self.tip_in = tip_in
        self.final_age = 0.0
        self._ball_home = rng.random() < 0.5
        self._poss_left = self._draw_possession()
        self._mm_bias = 0.0
        self._rung_noise: dict[float, float] = {}
        self._rung_spread: dict[float, int] = {}

    # -- game clock ------------------------------------------------------------
    @property
    def _period_len(self) -> float:
        return QUARTER_SECONDS if self.game.period <= 4 else OT_SECONDS

    def _fouling(self) -> bool:
        g = self.game
        start = self.foul_start if g.period == 4 else self.foul_start * 0.5
        return g.period >= 4 and g.clock_seconds <= start and 1 <= g.margin <= 8

    def _draw_possession(self) -> float:
        g = self.game
        if self._fouling():
            trailing_has_ball = (g.home.score < g.away.score) == self._ball_home
            return self.rng.uniform(5, 10) if trailing_has_ball else self.rng.uniform(3, 7)
        mean = 2880.0 / self.possessions
        if g.period > 4:
            mean *= 1.06  # tired legs: overtime is slower
        if g.period >= 4 and g.margin >= 18:
            mean /= self.coast
        if g.period >= 4 and g.clock_seconds <= 120:
            mean *= 0.88
        return max(4.0, self.rng.gauss(mean, 4.0))

    def _resolve_possession(self) -> None:
        g = self.game
        team = g.home if self._ball_home else g.away
        share = self.home_share if self._ball_home else 1 - self.home_share
        ppp = 2 * share * self.true_total / self.possessions * self.hot
        # Rubber band: trailing teams press and leaders ease off, so margins mean-revert.
        deficit = (g.away.score - g.home.score) if self._ball_home else (g.home.score - g.away.score)
        ppp *= 1.0 + max(-0.12, min(0.12, 0.0045 * deficit))
        if g.period > 4:
            ppp *= 0.9  # and less efficient
        if self._fouling():
            leading_has_ball = (g.home.score > g.away.score) == self._ball_home
            if leading_has_ball:  # sent to the line
                team.score += self.rng.choices([0, 1, 2], [0.05, 0.3, 0.65])[0]
            elif self.rng.random() < 0.42:  # trailing team hunting quick threes
                team.score += self.rng.choices([2, 3], [0.4, 0.6])[0]
        elif self.rng.random() < min(0.75, max(0.25, ppp / MEAN_GIVEN_SCORE)):
            pts, weights = zip(*POINTS_GIVEN_SCORE)
            team.score += self.rng.choices(pts, weights)[0]
        self._ball_home = not self._ball_home
        self.hot = 1.0 + 0.97 * (self.hot - 1.0) + self.rng.gauss(0, 0.006)

    def advance(self, dt: float) -> None:
        g = self.game
        if g.state == "final":
            self.final_age += dt
            return
        if g.state == "pre":
            self.tip_in -= dt
            if self.tip_in > 0:
                return
            dt, g.state, g.period, g.clock_seconds = -self.tip_in, "live", 1, float(QUARTER_SECONDS)
        while dt > 0 and g.state == "live":
            step = min(dt, self._poss_left, g.clock_seconds)
            g.clock_seconds -= step
            self._poss_left -= step
            dt -= step
            if self._poss_left <= 1e-9:
                self._resolve_possession()
                self._poss_left = self._draw_possession()
            if g.clock_seconds <= 1e-9:
                self._end_period()
        g.clock = fmt_clock(g.clock_seconds)

    def _end_period(self) -> None:
        g = self.game
        if g.period >= 4 and 1 <= g.margin <= 3 and self.rng.random() < TYING_SHOT[g.margin] * (1.0 if g.period == 4 else 0.4):
            # The trailing team gets the tying bucket at the horn.
            trailing = g.home if g.home.score < g.away.score else g.away
            trailing.score += g.margin
        if g.period >= 4 and g.home.score != g.away.score:
            g.state, g.clock_seconds = "final", 0.0
            return
        g.period += 1
        g.clock_seconds = float(self._period_len)
        self._poss_left = self._draw_possession()

    def fast_forward(self, period: int, clock: float, observer: Optional[Callable[[Game], None]] = None) -> None:
        """Play the game silently up to (period, clock)."""
        self.tip_in = 0.0
        g = self.game
        while g.state != "final" and (g.period < period or (g.period == period and g.clock_seconds > clock)):
            self.advance(30.0 if g.period < period else min(30.0, max(g.clock_seconds - clock, 0.5)))
            if observer:
                observer(g)

    # -- market ------------------------------------------------------------------
    def quote(self) -> None:
        """Refresh the synthetic ladder and sportsbook line from the current state."""
        g = self.game
        if g.state == "final":
            for r in g.ladder:
                over = g.total > r.strike
                r.yes_bid = r.yes_ask = r.no_bid = r.no_ask = None
                r.result = "yes" if over else "no"
            return
        sharp_prior = 0.8 * (g.pregame_total or 229) + 0.2 * (self.true_total + LINE_EXTRAS)
        dist = distribution(
            total=g.total,
            secs_left=g.seconds_remaining,
            margin=g.margin,
            period=max(g.period, 1),
            pregame_total=sharp_prior,
            ot_secs_left=g.clock_seconds if g.period > 4 else 0.0,
        )
        self._mm_bias = 0.96 * self._mm_bias + self.rng.gauss(0, 0.004)
        self._ensure_ladder(dist.mean)
        tense = g.period >= 4 and g.minutes_left <= 3 and g.margin <= 6
        for r in g.ladder:
            if g.total > r.strike:
                r.yes_bid, r.yes_ask, r.no_bid, r.no_ask = 99, None, None, 1
                continue
            noise = 0.9 * self._rung_noise.get(r.strike, 0.0) + self.rng.gauss(0, 0.003)
            self._rung_noise[r.strike] = noise
            p_over = 1 - dist.p_under(r.strike)
            premium = TAIL_PREMIUM * math.exp(-(((p_over - 0.06) / 0.07) ** 2)) if p_over > 0.004 else 0.0
            mid = 100 * min(0.995, max(0.005, p_over + premium + self._mm_bias + noise))
            spread = self._rung_spread.setdefault(r.strike, self.rng.choice([1, 2, 2, 3])) + (1 if tense else 0)
            bid = int(math.floor(mid - spread / 2 + 0.5))
            bid = min(max(bid, 0), 99 - spread)
            ask = bid + spread
            r.yes_bid = bid if bid >= 1 else None
            r.yes_ask = ask
            r.no_bid = 100 - ask
            r.no_ask = 100 - bid if bid >= 1 else None
            r.volume += self.rng.random() * 3
        self._quote_book(dist.mean)

    def _ensure_ladder(self, mean: float) -> None:
        g = self.game
        if not g.ladder:
            base = math.floor(g.pregame_total or 229) - 20 + 0.5
            g.ladder = [self._rung(base + 2 * i) for i in range(29)]
        while g.ladder[-1].strike < mean + 26:
            g.ladder.append(self._rung(g.ladder[-1].strike + 2))

    def _rung(self, strike: float) -> Rung:
        return Rung(ticker=f"{self.game.event_ticker}-T{math.ceil(strike)}", strike=strike)

    def _quote_book(self, mean: float) -> None:
        g = self.game
        lead = g.home.score - g.away.score
        secs = g.seconds_remaining if g.period <= 4 else g.clock_seconds
        expected_lead = lead + 2.5 * secs / 2880
        p_home = _phi(expected_lead / math.sqrt(0.062 * secs + 1.0))
        g.fanduel = FanDuelOdds(
            total_line=math.floor(mean) + 0.5,
            over_price=-110 + self.rng.choice([-5, 0, 0, 5]),
            under_price=-110 + self.rng.choice([-5, 0, 0, 5]),
            spread=-round(expected_lead * 2) / 2,
            home_ml=_american(p_home),
            away_ml=_american(1 - p_home),
            live=g.state == "live",
            source="sim",
            updated_at=now_iso(),
        )


class SimFeed:
    """A rolling slate of simulated games for the live desk."""

    def __init__(self, n_games: int = 6, seed: Optional[int] = None, observer: Optional[Callable[[Game], None]] = None):
        self.rng = random.Random(seed)
        self.observer = observer
        self.n_games = n_games
        self.sims: list[SimGame] = []
        self.status = {
            name: {"ok": True, "detail": "Simulated", "updated_at": now_iso()}
            for name in ("scores", "kalshi", "fanduel")
        }
        self.reset()

    def reset(self) -> None:
        # Stagger the slate so something is always close to the fourth quarter.
        starts = [(4, 690.0), (3, 300.0), (4, 420.0), (2, 200.0), (3, 660.0), (1, 500.0)]
        self.sims = []
        for i in range(self.n_games):
            sim = SimGame(self.rng)
            period, clock = starts[i % len(starts)]
            sim.fast_forward(period, clock, self.observer)
            sim.quote()
            self.sims.append(sim)

    def step(self, dt: float) -> list[Game]:
        for i, sim in enumerate(self.sims):
            sim.advance(dt)
            sim.quote()
            if sim.game.state == "final" and sim.final_age > 420:
                # Retire the finished game and bring a new one in mid-third-quarter.
                fresh = SimGame(self.rng)
                fresh.fast_forward(3, self.rng.uniform(200, 600), self.observer)
                fresh.quote()
                self.sims[i] = fresh
        order = {"live": 0, "pre": 1, "final": 2}
        return sorted((s.game for s in self.sims), key=lambda g: (order[g.state], g.seconds_remaining, g.id))

    async def aclose(self) -> None:  # symmetry with LiveFeed
        return None
