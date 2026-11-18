"""Pure decision rules: when to open a position and when to get out.

No I/O here. The live engine and the training gym both call these, so what
the agent practises is exactly what it does with money on the line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from ..domain import Game, Rung
from ..model.totals import OT_MEAN, implied_total

BUFFER_BUCKETS = [(0, 8, "<8"), (8, 10, "8-10"), (10, 12, "10-12"), (12, 15, "12-15"), (15, 99, "15+")]
TIME_BUCKETS = [(9, 12.01, "9-12"), (6, 9, "6-9"), (3, 6, "3-6"), (0, 3, "0-3")]
MARGIN_BUCKETS = [(0, 6, "close"), (6, 15, "mid"), (15, 999, "blowout")]

# Exit profiles scale the playbook's exit thresholds. The learner works out
# which one actually makes money.
EXIT_PROFILES = {
    "tight": {"p_shift": 5.0, "stop_mult": 0.7, "label": "Tight", "description": "Bails early: win-chance floor +5 pts, stop 30% closer."},
    "balanced": {"p_shift": 0.0, "stop_mult": 1.0, "label": "Balanced", "description": "Uses the playbook's exit thresholds as set."},
    "patient": {"p_shift": -6.0, "stop_mult": 1.5, "label": "Patient", "description": "Rides out wobbles: floor -6 pts, stop 50% wider."},
}


def _bucket(value: float, buckets: list[tuple[float, float, str]]) -> str:
    for lo, hi, name in buckets:
        if lo <= value < hi:
            return name
    return buckets[-1][2]


def arm_key(buffer: float, minutes_left: float, margin: float) -> str:
    return "|".join(
        [_bucket(buffer, BUFFER_BUCKETS), _bucket(minutes_left, TIME_BUCKETS), _bucket(margin, MARGIN_BUCKETS)]
    )


def kalshi_fee(contracts: int, price_cents: float) -> float:
    """Kalshi taker fee in dollars: 7% of contracts x P x (1 - P), rounded up to a cent."""
    p = price_cents / 100.0
    return math.ceil(0.07 * contracts * p * (1 - p) * 100 - 1e-9) / 100.0


def size_order(stake: float, price_cents: int) -> tuple[int, float, float]:
    """Contracts affordable for `stake`, plus (cost incl. fees, fees)."""
    contracts = int(stake // (price_cents / 100.0))
    while contracts > 0:
        fees = kalshi_fee(contracts, price_cents)
        cost = contracts * price_cents / 100.0 + fees
        if cost <= stake + 1e-9:
            return contracts, round(cost, 2), fees
        contracts -= 1
    return 0, 0.0, 0.0


@dataclass
class Candidate:
    rung: Rung
    price: int
    p_model: float
    edge: float
    buffer: float
    reference: float
    reference_source: str
    arm: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Skip:
    code: str
    headline: str
    reasoning: str
    data: dict[str, Any] = field(default_factory=dict)


def reference_line(game: Game) -> tuple[Optional[float], str]:
    """The 'betting line' the cushion is measured from.

    Live FanDuel when we have it; otherwise the 50/50 point of the Kalshi
    ladder, which tracks the sportsbook total closely; the model as a last resort.
    """
    fd = game.fanduel
    if fd and fd.live and fd.total_line is not None:
        return fd.total_line, "sim book" if fd.source == "sim" else "FanDuel live"
    implied = implied_total(game.ladder)
    if implied is not None:
        return implied, "Kalshi-implied line"
    if game.projection:
        return game.projection.mean, "model projection"
    return None, ""


def find_entries(game: Game, p: dict[str, float]) -> list[Candidate] | Skip | None:
    """Qualifying unders for the Q4 strategy, best edge first.

    Returns None when the game is simply not in the window (nothing worth
    logging), a Skip when it is in the window but fails a rule, or candidates.
    """
    if not game.in_fourth:
        return None
    mins = game.minutes_left
    if mins > p["max_minutes_left"] or mins < p["min_minutes_left"]:
        return None
    ref, ref_source = reference_line(game)
    if ref is None or not game.ladder:
        return Skip("no_data", f"{game.label}: no line or markets yet", "Waiting for a reference line and a Kalshi ladder.")

    base = {"line": ref, "clock": "End of Q3" if game.at_q3_end else f"Q4 {game.clock}", "margin": game.margin, "total": game.total}
    if mins < 5 and game.margin <= p["skip_close_margin"]:
        return Skip(
            "close_game",
            f"Pass on {game.label}: {game.margin}-pt game with {game.q4_clock} left",
            f"Inside 5:00 a game within {p['skip_close_margin']:g} points tends to end in fouls, quick threes "
            f"and sometimes overtime, which is exactly what breaks an under. Staying out.",
            {**base, "ot_chance": f"{(game.projection.p_ot if game.projection else 0):.0%}"},
        )

    in_band = [r for r in game.ladder if p["buffer_min"] <= r.strike - ref <= p["buffer_max"]]
    priced = [r for r in in_band if r.no_ask is not None and p["min_price"] <= r.no_ask <= p["max_price"]]
    if not priced:
        if in_band:
            quotes = ", ".join(f"{r.strike:g} @ {r.no_ask}c" if r.no_ask else f"{r.strike:g} no offer" for r in in_band[:4])
            why = f"Unders {p['buffer_min']:g}-{p['buffer_max']:g} pts above {ref:g} are priced outside {p['min_price']:g}-{p['max_price']:g}c ({quotes})."
        else:
            why = f"No Kalshi strike sits {p['buffer_min']:g}-{p['buffer_max']:g} pts above the {ref_source} of {ref:g}."
        return Skip("no_price", f"{game.label}: nothing at the right price", why, base)

    out: list[Candidate] = []
    for r in priced:
        edge = r.p_under - r.no_ask / 100.0
        buffer = r.strike - ref
        out.append(
            Candidate(
                rung=r,
                price=r.no_ask,
                p_model=r.p_under,
                edge=edge,
                buffer=buffer,
                reference=ref,
                reference_source=ref_source,
                arm=arm_key(buffer, mins, game.margin),
                context={
                    "period": game.period,
                    "clock": game.q4_clock,
                    "minutes_left": round(mins, 2),
                    "total": game.total,
                    "margin": game.margin,
                    "line": ref,
                    "line_source": ref_source,
                    "buffer": round(buffer, 1),
                    "projection": game.projection.mean if game.projection else None,
                    "p_ot": game.projection.p_ot if game.projection else None,
                    "pace": game.projection.pace if game.projection else None,
                    "pregame_total": game.pregame_total,
                },
            )
        )
    out.sort(key=lambda c: c.edge, reverse=True)
    best = out[0]
    if best.edge * 100 < p["min_edge"]:
        return Skip(
            "no_edge",
            f"{game.label}: under {best.rung.strike:g} at {best.price}c is overpriced",
            f"The model gives it a {best.p_model:.1%} chance, so paying {best.price}c is an edge of "
            f"{best.edge * 100:+.1f}%. The playbook's floor is {p['min_edge']:g}%.",
            {**base, "strike": best.rung.strike, "price": f"{best.price}c", "model": f"{best.p_model:.1%}"},
        )
    return [c for c in out if c.edge * 100 >= p["min_edge"]]


@dataclass
class ExitSignal:
    reason: str  # risk_exit | stop_loss | take_profit
    headline: str
    reasoning: str
    price: int
    data: dict[str, Any] = field(default_factory=dict)


def position_p_win(side: str, rung: Rung) -> float:
    return rung.p_under if side == "under" else 1.0 - rung.p_under


def exit_signal(
    *,
    side: str,
    strike: float,
    entry_price: int,
    game: Game,
    rung: Rung,
    p: dict[str, float],
    profile: str = "balanced",
) -> Optional[ExitSignal]:
    """Should an open position be sold right now? None means hold."""
    bid = rung.bid(side)
    if bid is None or game.state != "live":
        return None
    prof = EXIT_PROFILES.get(profile, EXIT_PROFILES["balanced"])
    p_win = position_p_win(side, rung)
    floor = min(97.0, p["min_p_win"] + prof["p_shift"]) / 100.0
    stop = p["stop_loss"] * prof["stop_mult"]
    label = f"{game.label} {side} {strike:g}"
    data = {"bid": f"{bid}c", "entry": f"{entry_price}c", "win_chance": f"{p_win:.0%}", "clock": "End of Q3" if game.at_q3_end else f"Q{game.period} {game.clock}" if game.period <= 4 else "OT", "margin": game.margin}

    if p["take_profit"] < 100 and bid >= p["take_profit"] and bid > entry_price:
        return ExitSignal(
            "take_profit",
            f"Locking in {label} at {bid}c",
            f"The bid reached {bid}c. The last cent is not worth the leftover overtime tail, so taking the win now.",
            bid,
            data,
        )
    if p_win < floor:
        return ExitSignal(
            "risk_exit",
            f"Getting out of {label}: win chance down to {p_win:.0%}",
            f"The model's chance of this finishing {side} {strike:g} fell to {p_win:.0%}, under the {floor:.0%} floor "
            f"({profile} exit). Total is {game.total} with {game.q4_clock} left in a {game.margin}-pt game. "
            f"Selling at {bid}c against a {entry_price}c entry for a small loss instead of risking the whole stake.",
            bid,
            data,
        )
    if entry_price - bid >= stop:
        return ExitSignal(
            "stop_loss",
            f"Stop hit on {label}: bid {bid}c",
            f"The market marked this down {entry_price - bid}c from the {entry_price}c entry, past the {stop:g}c stop "
            f"({profile} exit). The market is seeing more danger than the model ({p_win:.0%}); respecting it.",
            bid,
            data,
        )
    proj = game.projection
    if side == "under" and proj and game.period == 4 and proj.p_ot * 100 >= p["max_ot_risk"]:
        if proj.mean + (1 - proj.p_ot) * OT_MEAN > strike:
            return ExitSignal(
                "risk_exit",
                f"Getting out of {label}: overtime risk {proj.p_ot:.0%}",
                f"A {game.margin}-pt game with {game.q4_clock} left has about a {proj.p_ot:.0%} chance of overtime, and an "
                f"extra period (~{OT_MEAN:.0f} pts) would push the total past {strike:g}. Selling at {bid}c.",
                bid,
                {**data, "ot_chance": f"{proj.p_ot:.0%}"},
            )
    return None
