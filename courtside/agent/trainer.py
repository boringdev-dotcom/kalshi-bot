"""The training gym: play many simulated fourth quarters at full speed.

Each episode runs the same entry and exit rules the live engine uses, against
the simulator's market, and feeds the outcome to the learner as simulated
(discounted) evidence. Trades made here are stored with training=1 so they
inform calibration but never touch the account or the trade blotter.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Optional

from ..db import DB
from ..domain import now_iso
from ..feeds.sim import SimGame
from ..model.totals import refresh_game
from .learner import Learner
from .memory import MemoryStore
from .playbook import Q4_UNDER, Playbook
from .policy import exit_signal, find_entries, kalshi_fee, size_order

STEP_SECONDS = 10.0


def train(db: DB, playbook: Playbook, learner: Learner, memory: MemoryStore, episodes: int, seed: Optional[int] = None) -> dict[str, Any]:
    rng = random.Random(seed)
    p = playbook.params(Q4_UNDER)
    learner = Learner(learner.db, seed=seed, env="sim")  # practice always learns from practice
    trades: list[dict[str, Any]] = []

    for _ in range(episodes):
        sim = SimGame(rng, quarters=False)
        game = sim.game
        sim.fast_forward(4, 720.0)
        position: Optional[dict[str, Any]] = None
        done: Optional[dict[str, Any]] = None  # at most one trade per game, like the live agent

        while game.state != "final":
            sim.advance(STEP_SECONDS)
            sim.quote()
            refresh_game(game)
            if game.state == "final":
                break
            if position is not None:
                rung = game.rung(position["ticker"])
                signal = exit_signal(
                    side="under", strike=position["strike"], entry_price=position["entry_price"],
                    game=game, rung=rung, p=p, profile=position["exit_profile"],
                )
                if signal:
                    fees = kalshi_fee(position["contracts"], signal.price)
                    position.update(
                        exit_price=signal.price, exit_reason=signal.reason,
                        pnl=round(position["contracts"] * signal.price / 100.0 - fees - position["cost"], 2),
                    )
                    done, position = position, None
            elif done is None:
                found = find_entries(game, p)
                if isinstance(found, list):
                    floor = min(0.0, p["min_edge"] / 100.0) - 0.005
                    viable = [c for c in found if learner.allows(learner.entry_view(c.arm, c.p_model, c.price), floor)]
                    if viable:
                        cand = max(viable, key=lambda c: learner.sample_ev(c.arm, c.p_model, c.price))
                        contracts, cost, fees = size_order(p["stake"], cand.price)
                        if contracts:
                            position = {
                                "game_id": game.id, "game_label": game.label, "ticker": cand.rung.ticker,
                                "strike": cand.rung.strike, "side": "under", "contracts": contracts,
                                "entry_price": cand.price, "cost": cost, "fees": fees, "arm_key": cand.arm,
                                "p_win_entry": round(cand.p_model, 4), "context": cand.context,
                                "exit_profile": learner.choose_exit_profile(),
                            }

        final = game.total
        if position is not None:
            won = final < position["strike"]
            position.update(
                exit_price=100 if won else 0,
                exit_reason="settled_win" if won else "settled_loss",
                pnl=round(position["contracts"] * (1.0 if won else 0.0) - position["cost"], 2),
            )
            position["counterfactual_pnl"] = position["pnl"]
            done = position
        if done is None:
            continue
        if "counterfactual_pnl" not in done:
            held = round(done["contracts"] * (1.0 if final < done["strike"] else 0.0) - done["cost"], 2)
            done["counterfactual_pnl"] = held
            done["exit_verdict"] = "saved" if done["pnl"] > held else "shaken_out"
            learner.record_exit_verdict(done["exit_profile"], done["exit_verdict"])
        done["final_total"] = final
        learner.record(
            arm=done["arm_key"], exit_profile=done["exit_profile"], ret=done["pnl"] / done["cost"],
            won=final < done["strike"],
            p_model=done["p_win_entry"], price_cents=done["entry_price"], simulated=True,
        )
        stamp = now_iso()
        db.insert(
            "positions",
            {**done, "status": "closed", "opened_at": stamp, "closed_at": stamp, "opened_by": "agent",
             "mode": "paper", "simulated": True, "training": True, "strategy_id": Q4_UNDER},
        )
        trades.append(done)

    db.set("sim_episodes", int(db.get("sim_episodes", 0)) + episodes)
    lessons = _summarise(trades, memory) if trades else 0
    wins = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "episodes": episodes,
        "trades": len(trades),
        "win_rate": round(wins / len(trades), 4) if trades else 0.0,
        "pnl": round(sum(t["pnl"] for t in trades), 2),
        "lessons": lessons,
    }


def _summarise(trades: list[dict[str, Any]], memory: MemoryStore) -> int:
    """Turn a training run into a few lessons about where the strategy made and lost money."""
    by_arm: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        by_arm[t["arm_key"]].append(t)
    scored = [
        (arm, len(ts), sum(t["pnl"] for t in ts) / sum(t["cost"] for t in ts), sum(1 for t in ts if t["pnl"] > 0) / len(ts))
        for arm, ts in by_arm.items()
        if len(ts) >= 8
    ]
    made = 0
    if scored:
        for arm, n, ret, win_rate in (max(scored, key=lambda s: s[2]), min(scored, key=lambda s: s[2])):
            buffer, time, margin = arm.split("|")
            verdict = "the best spot" if ret > 0 else "a losing spot"
            memory.add(
                "lesson",
                f"Practice ({len(trades)} simulated trades): {buffer} pts of cushion with {time} min left in a {margin} "
                f"game was {verdict}: {n} trades, {win_rate:.0%} won, {ret:+.1%} per dollar risked.",
                tags=["nba", "q4_under", f"buffer:{buffer}", f"time:{time}", f"margin:{margin}", "training"],
                importance=0.45, simulated=True,
            )
            made += 1
            if len(scored) == 1:
                break
    exits = [t for t in trades if t.get("exit_verdict")]
    if len(exits) >= 5:
        saved = sum(1 for t in exits if t["exit_verdict"] == "saved")
        net = sum(t["pnl"] - t["counterfactual_pnl"] for t in exits)
        memory.add(
            "lesson",
            f"Practice: of {len(exits)} early exits, {saved} avoided a loss and {len(exits) - saved} sold a winner. "
            f"Net effect of exiting versus always holding: {net:+,.0f} dollars.",
            tags=["nba", "q4_under", "exits", "training"],
            importance=0.5, simulated=True,
        )
        made += 1
    return made
