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
from typing import Any, Callable, Optional

from ..domain import OT_SECONDS, QUARTER_SECONDS, FanDuelOdds, Game, Rung, Team, fmt_clock, now_iso
from ..model.quarters import QUARTER_SHARE, p_no, project_game_margin, project_quarter
from ..model.totals import LINE_EXTRAS, _phi, distribution
from .patterns import build_context

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

    def __init__(self, rng: random.Random, tip_in: float = 0.0, quarters: bool = True):
        SimGame._counter += 1
        self.rng = rng
        self.with_quarters = quarters  # the training gym skips quarter markets for speed
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
        self._rung_noise: dict[Any, float] = {}
        self._rung_spread: dict[Any, int] = {}
        # Players, fouls and runs for the desk. Seeded apart from `rng` so scoring is unchanged.
        self.box = SimBox(self.game, seed=SimGame._counter * 7919) if quarters else None

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
        before, fouled = team.score, False
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
                fouled = True
                team.add_points(self.rng.choices([0, 1, 2], [0.05, 0.3, 0.65])[0], g.period)
            elif self.rng.random() < 0.42:  # trailing team hunting quick threes
                team.add_points(self.rng.choices([2, 3], [0.4, 0.6])[0], g.period)
        elif self.rng.random() < min(0.75, max(0.25, ppp / MEAN_GIVEN_SCORE)):
            pts, weights = zip(*POINTS_GIVEN_SCORE)
            team.add_points(self.rng.choices(pts, weights)[0], g.period)
        if self.box:
            self.box.possession(self._ball_home, team.score - before, fouled)
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
            if self.box:
                self.box.clock(step)
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
            points = g.margin
            trailing.add_points(points, g.period)
            if self.box:
                self.box.possession(trailing is g.home, points, False)
        if self.box:
            self.box.log(None, f"End of {'Q' + str(g.period) if g.period <= 4 else 'OT' + str(g.period - 4)}")
        if g.period >= 4 and g.home.score != g.away.score:
            g.state, g.clock_seconds = "final", 0.0
            if self.box:
                self.box.log(None, "End of game")
            return
        g.period += 1
        g.clock_seconds = float(self._period_len)
        if self.box:
            self.box.rotate()
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
        if self.with_quarters:
            self._quote_quarters()
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

    def _quote_quarters(self) -> None:
        """Synthetic full-game spreads, quarter totals and quarter spreads, priced off the model plus noise."""
        g = self.game
        if not g.spreads:
            for team, other in ((g.away, g.home), (g.home, g.away)):
                g.spreads += [
                    Rung(ticker=f"{g.event_ticker}-S{team.abbr}{math.ceil(line)}", strike=line, kind="spread",
                         team=team.abbr, other_team=other.abbr)
                    for line in (1.5, 3.5, 5.5, 7.5, 9.5, 12.5, 15.5, 18.5)
                ]
        # Their own random stream, so adding them leaves the quarter prices exactly as they were.
        self._spread_rng = getattr(self, "_spread_rng", None) or random.Random(g.event_ticker or g.id)
        self._quote_rungs(g.spreads, 0, project_game_margin(g), self._spread_rng)
        if not g.quarter_markets:
            for q in (1, 2, 3, 4):
                centre = math.floor(QUARTER_SHARE[q] * (g.pregame_total or 229)) + 0.5
                totals = [
                    Rung(ticker=f"{g.event_ticker}-Q{q}T{math.ceil(centre + 2 * i)}", strike=centre + 2 * i, segment=f"q{q}")
                    for i in range(-6, 7)
                ]
                spreads = []
                for team, other, lines in (
                    (g.away, g.home, (1.5, 3.5, 5.5, 7.5, 9.5, 11.5)),
                    (g.home, g.away, (1.5, 3.5, 5.5, 7.5, 9.5, 11.5, 13.5)),
                ):
                    spreads += [
                        Rung(ticker=f"{g.event_ticker}-Q{q}S{team.abbr}{math.ceil(line)}", strike=line, segment=f"q{q}",
                             kind="spread", team=team.abbr, other_team=other.abbr)
                        for line in lines
                    ]
                g.quarter_markets[f"q{q}"] = {"total": totals, "spread": spreads}
        for q in (1, 2, 3, 4):
            proj = project_quarter(g, q)
            for rungs in g.quarter_markets[f"q{q}"].values():
                self._quote_rungs(rungs, q, proj, self.rng)

    def _quote_rungs(self, rungs: list[Rung], q: int, proj: Optional[dict[str, float]], rng: random.Random) -> None:
        g = self.game
        for r in rungs:
            if proj is None:
                value = g.settle_value(r.segment, r.kind, r.team)
                r.yes_bid = r.yes_ask = r.no_bid = r.no_ask = None
                r.result = "yes" if value is not None and value > r.strike else "no"
                continue
            noise = 0.9 * self._rung_noise.get(r.ticker, 0.0) + rng.gauss(0, 0.004)
            self._rung_noise[r.ticker] = noise
            p_yes = 1 - p_no(r, g, q, proj)
            mid = 100 * min(0.995, max(0.005, p_yes + noise + self._mm_bias))
            spread = self._rung_spread.setdefault(r.ticker, rng.choice([2, 2, 3, 4]))
            bid = min(max(int(math.floor(mid - spread / 2 + 0.5)), 0), 99 - spread)
            r.yes_bid = bid if bid >= 1 else None
            r.yes_ask = bid + spread
            r.no_bid = 100 - (bid + spread)
            r.no_ask = 100 - bid if bid >= 1 else None
            r.volume += rng.random()

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
            if sim.box:
                sim.game.context = build_context(sim.game, sim.box.snapshot())
                sim.game.plays = sim.box.plays
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


# ------------------------------------------------------------------------ box score
FIRST = ["Marcus", "Andre", "Tyler", "Jalen", "Devin", "Isaiah", "Malik", "Cole", "Darius", "Evan", "Kobe", "Trey",
         "Jordan", "Caleb", "Miles", "Xavier", "Damon", "Reggie", "Theo", "Quinn", "Luka", "Nico", "Omar", "Felix",
         "Bryce", "Corey", "Elijah", "Grant", "Hassan", "Ivan"]
LAST = ["Hollis", "Okafor", "Brandt", "Mercer", "Vance", "Whitfield", "Castellanos", "Doyle", "Ferreira", "Gaines",
        "Halvorsen", "Ibekwe", "Jarrett", "Kowalski", "Lindqvist", "Marsh", "Nkemelu", "Oyelaran", "Pruitt", "Quarles",
        "Redd", "Sorensen", "Tolliver", "Underwood", "Varga", "Wexler", "Yates", "Zelenko", "Abernathy", "Bellamy",
        "Crowder", "Delacroix", "Ekwueme", "Fontaine", "Galloway", "Hartigan", "Iverson", "Jablonski", "Kessler", "Lattimore"]
USAGE = [1.35, 1.2, 1.05, 0.95, 0.85, 0.85, 0.7, 0.6, 0.45, 0.35]


SHOTS = ["jump shot", "driving layup", "pullup jump shot", "dunk", "floating jump shot", "step back jump shot", "hook shot"]
TURNOVERS = ["bad pass turnover", "lost ball turnover", "traveling", "offensive foul turnover"]


class SimBox:
    """A made-up box score for a practice game: rosters, a rotation, shots and fouls.

    It follows the game's scoring rather than driving it, and has its own random
    numbers, so practice scores and prices are the same with or without it.
    """

    def __init__(self, game: Game, seed: int):
        from .patterns import PlayerLine

        self.game = game
        self.rng = random.Random(seed)
        # Different surnames for everyone in the game, so short names are never ambiguous.
        names = [f"{self.rng.choice(FIRST)} {last}" for last in self.rng.sample(LAST, 20)]
        self.players: dict[str, list[PlayerLine]] = {}
        for t, team in enumerate((game.away, game.home)):
            roster = []
            for i in range(10):
                p = PlayerLine(id=f"{team.abbr}{i}", name=names[t * 10 + i], team=team.abbr, starter=i < 5)
                roster.append(p)
            self.players[team.abbr] = roster
        self.usage = {p.id: USAGE[i] * self.rng.uniform(0.85, 1.15) for r in self.players.values() for i, p in enumerate(r)}
        self.fouls: list[tuple[str, int, float]] = []
        self.scoring: list[tuple[float, str, int]] = []
        self.plays: list[dict[str, Any]] = []
        self._scored: Optional[tuple[str, int]] = None  # points already on the board for the play being logged
        self.out = [(t.abbr, f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}") for t in (game.away, game.home) if self.rng.random() < 0.5]
        self.rotate()

    # -- rotation ------------------------------------------------------------
    def _starters_wanted(self) -> int:
        g = self.game
        period, clock = max(g.period, 1), g.clock_seconds
        if period == 4 and ((g.margin >= 20 and clock <= 360) or (g.margin >= 26 and clock <= 540)):
            return 0  # garbage time
        if period in (1, 3):
            return 5 if clock > 240 else 2
        if period == 2:
            return 2 if clock > 360 else 5
        if period == 4:
            return 2 if clock > 480 else 5
        return 5

    def rotate(self) -> None:
        period = max(self.game.period, 1)
        want = self._starters_wanted()
        for roster in self.players.values():
            def ok(p: Any) -> bool:
                return p.fouls < 6 and not (period <= 3 and p.fouls >= period + 1)

            # When only some starters play, the ones who have played least go in: everyone gets a rest.
            starters = sorted((p for p in roster if p.starter and ok(p)), key=lambda p: (p.minutes, -self.usage[p.id]))[:want]
            bench = sorted((p for p in roster if not p.starter and ok(p)), key=lambda p: -self.usage[p.id])
            lineup = starters + bench[: 5 - len(starters)]
            if len(lineup) < 5:  # foul trouble everywhere: play whoever is left
                spare = [p for p in roster if p not in lineup and p.fouls < 6]
                lineup += spare[: 5 - len(lineup)]
            ids = {p.id for p in lineup}
            if self.game.period >= 1:
                coming = [p for p in lineup if not p.on_court]
                going = [p for p in roster if p.on_court and p.id not in ids]
                for a, b in zip(coming, going):
                    self.log(a.team, f"{a.name} enters the game for {b.name}")
            for p in roster:
                p.on_court = p.id in ids

    def clock(self, seconds: float) -> None:
        for roster in self.players.values():
            for p in roster:
                if p.on_court:
                    p.minutes += seconds / 60.0

    # -- events --------------------------------------------------------------
    def _on(self, abbr: str) -> list[Any]:
        return [p for p in self.players[abbr] if p.on_court]

    def log(self, team: Optional[str], text: str, points: int = 0) -> None:
        g = self.game
        away, home = g.away.score, g.home.score
        if self._scored and not points:  # a foul or miss logged before the points it led to
            away -= self._scored[1] if self._scored[0] == g.away.abbr else 0
            home -= self._scored[1] if self._scored[0] == g.home.abbr else 0
        self.plays.append({"period": max(g.period, 1), "clock": fmt_clock(g.clock_seconds), "team": team, "text": text,
                           "away": away, "home": home, "points": points})

    def _foul(self, abbr: str, kind: str = "personal foul") -> Any:
        g = self.game
        p = self.rng.choice(self._on(abbr))
        p.fouls += 1
        self.fouls.append((abbr, g.period, g.clock_seconds))
        self.log(abbr, f"{p.name} {kind}")
        return p

    def possession(self, offense_home: bool, points: int, fouled: bool) -> None:
        """Book a possession that scored `points` (fouled = a foul-game trip to the line)."""
        g = self.game
        off, dfn = (g.home.abbr, g.away.abbr) if offense_home else (g.away.abbr, g.home.abbr)
        on = self._on(off)
        shooter = self.rng.choices(on, [self.usage[p.id] for p in on])[0]
        me = shooter.name
        self._scored = (off, points)
        if fouled:
            self._foul(dfn, "intentional foul")
            shooter.fta += 2
            shooter.ftm += min(points, 2)
            self.log(off, f"{me} makes {min(points, 2)} of 2 free throws", points)
        elif points == 0:
            if self.rng.random() < 0.85:
                shooter.fga += 1
                three = self.rng.random() < 0.4
                shooter.tpa += three
                self.log(off, f"{me} misses {'three point jumper' if three else self.rng.choice(SHOTS)}")
            else:
                self.log(off, f"{me} {self.rng.choice(TURNOVERS)}")
            if self.rng.random() < 0.15:
                self._foul(dfn)
        elif points == 1:
            self._foul(dfn, "shooting foul")
            shooter.fta += 2
            shooter.ftm += 1
            self.log(off, f"{me} makes 1 of 2 free throws", 1)
        elif points == 2:
            if self.rng.random() < 0.25:
                self._foul(dfn, "shooting foul")
                shooter.fta += 2
                shooter.ftm += 2
                self.log(off, f"{me} makes 2 of 2 free throws", 2)
            else:
                shooter.fga += 1
                shooter.fgm += 1
                self.log(off, f"{me} makes {self.rng.choice(SHOTS)}", 2)
        else:
            shooter.fga += 1
            shooter.fgm += 1
            shooter.tpa += 1
            shooter.tpm += 1
            if points >= 4:
                self._foul(dfn, "shooting foul")
                shooter.fta += 1
                shooter.ftm += 1
                self.log(off, f"{me} makes three point jumper and the free throw (4-point play)", points)
            else:
                self.log(off, f"{me} makes three point jumper", 3)
        self._scored = None
        if points:
            shooter.points += points
            self.scoring.append((g.elapsed, off, points))
            for p in on:
                p.plus_minus += points
            for p in self._on(dfn):
                p.plus_minus -= points
        self.rotate()

    def snapshot(self) -> Any:
        from .patterns import Snapshot

        return Snapshot(
            players=[p for r in self.players.values() for p in r],
            fouls=list(self.fouls),
            scoring=list(self.scoring),
            out=list(self.out),
            source="practice",
            plays=self.plays,
        )
