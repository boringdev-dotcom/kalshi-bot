"""Reinforcement learning from the agent's own results.

This is a contextual bandit, which is the right-sized tool for the problem:
each trade is one decision in one context with one payoff.

* Entry arms. A context is (cushion above the line, time left, how close the
  game is). Each arm starts from the model's expected return and is pulled
  toward what actually happened as trades settle. When a context keeps losing
  money the posterior goes negative and the agent stops trading it; when it
  keeps paying the agent grows more willing. Thompson sampling picks among
  qualifying strikes so uncertain arms still get tried.
* Exit arms. Each entry is assigned an exit profile (tight / balanced /
  patient) by Thompson sampling, so the agent learns how twitchy to be. A
  profile is judged on what its exits did against holding: once a game is
  final every early exit is graded by its P&L minus what holding would have
  paid, and a trade held to the end scores zero. Profiles whose early sales
  keep giving up winners fall behind and get used less.

Real and simulated results are kept apart. On real markets (paper or live)
only real trades count: practice in the sandbox never moves a real-money
decision. In the simulator the agent learns from simulated trades, so you can
watch the learning work and try playbook changes quickly.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

from ..db import DB
from ..model.totals import distribution
from .policy import BUFFER_BUCKETS, EXIT_PROFILES, MARGIN_BUCKETS, TIME_BUCKETS

PRIOR_STRENGTH = 30.0  # the model's opinion is worth this many trades
MIN_VETO_TRADES = 8  # results cannot overrule the playbook on fewer trades than this
EXIT_PRIOR_STRENGTH = 5.0
RETURN_SD = 0.25  # rough per-trade sd of return per dollar risked


def model_ev(p_model: float, price_cents: float) -> float:
    """Expected return per dollar if held to settlement at the model's probability."""
    price = price_cents / 100.0
    return (p_model - price) / price


class Learner:
    def __init__(self, db: DB, seed: Optional[int] = None, env: str = "real"):
        self.db = db
        self.rng = random.Random(seed)
        self.env = env  # "real" or "sim": which body of evidence to learn from

    # -- storage ---------------------------------------------------------------
    def _arm(self, key: str, kind: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM arms WHERE key=? AND kind=?", [key, kind])
        if row is None:
            self.db.execute("INSERT INTO arms(key, kind) VALUES(?, ?)", [key, kind])
            row = self.db.one("SELECT * FROM arms WHERE key=? AND kind=?", [key, kind])
        return row

    def _effective(self, row: dict[str, Any]) -> tuple[float, float, float]:
        """(n, wins, sum of returns) from the evidence that applies to the current environment."""
        if self.env == "sim":
            return row["sim_n"], row["sim_wins"], row["sim_sum_ret"]
        return row["n"], row["wins"], row["sum_ret"]

    # -- entries ---------------------------------------------------------------
    def entry_view(self, arm: str, p_model: float, price_cents: float) -> dict[str, float]:
        row = self._arm(arm, "entry")
        n, wins, total = self._effective(row)
        prior = model_ev(p_model, price_cents)
        return {
            "ev": (PRIOR_STRENGTH * prior + total) / (PRIOR_STRENGTH + n),
            "ev_model": prior,
            "p_win": (PRIOR_STRENGTH * p_model + wins) / (PRIOR_STRENGTH + n),
            "n": n,
            "n_real": row["n"],
            "n_sim": row["sim_n"],
            "mean_return": total / n if n else 0.0,
        }

    @staticmethod
    def allows(view: dict[str, float], floor: float) -> bool:
        """May this spot be traded? A few bad trades prove nothing, so results
        only veto once there is a real sample behind them."""
        return view["n"] < MIN_VETO_TRADES or view["ev"] >= floor

    def sample_ev(self, arm: str, p_model: float, price_cents: float) -> float:
        view = self.entry_view(arm, p_model, price_cents)
        return self.rng.gauss(view["ev"], RETURN_SD / math.sqrt(PRIOR_STRENGTH + view["n"]))

    # -- exits -----------------------------------------------------------------
    def _edge(self, row: dict[str, Any]) -> tuple[float, float]:
        """(graded trades, sum of P&L minus holding per dollar) for the current environment."""
        if self.env == "sim":
            return row["sim_edge_n"], row["sim_sum_edge"]
        return row["edge_n"], row["sum_edge"]

    def _exit_posterior(self, profile: str) -> tuple[float, float]:
        """Mean and sd of what this profile's exits beat holding by, per dollar. Starts at zero:
        no style is assumed better than holding until results say so."""
        n, total = self._edge(self._arm(profile, "exit"))
        return total / (EXIT_PRIOR_STRENGTH + n), RETURN_SD / math.sqrt(EXIT_PRIOR_STRENGTH + n)

    def grade_exit(self, exit_profile: Optional[str], edge: float, simulated: bool) -> None:
        """One finished trade's P&L minus what holding to the end would have paid, per dollar risked."""
        if not exit_profile:
            return
        self._arm(exit_profile, "exit")
        prefix = "sim_" if simulated else ""
        self.db.execute(
            f"UPDATE arms SET {prefix}edge_n={prefix}edge_n+1, {prefix}sum_edge={prefix}sum_edge+? WHERE key=? AND kind='exit'",
            [edge, exit_profile],
        )

    def rebuild_exit_grades(self, rows: list[dict[str, Any]]) -> int:
        """Grade past trades once, so the styles start from the record already made. Each row needs
        exit_profile, pnl, counterfactual_pnl, cost and simulated."""
        if self.db.one("SELECT 1 FROM arms WHERE kind='exit' AND (edge_n > 0 OR sim_edge_n > 0)"):
            return 0
        n = 0
        for r in rows:
            if r["exit_profile"] and r["cost"] and r["counterfactual_pnl"] is not None:
                self.grade_exit(r["exit_profile"], (r["pnl"] - r["counterfactual_pnl"]) / r["cost"], bool(r["simulated"]))
                n += 1
        return n

    def choose_exit_profile(self) -> str:
        draws = {name: self.rng.gauss(*self._exit_posterior(name)) for name in EXIT_PROFILES}
        return max(draws, key=draws.get)

    # -- feedback --------------------------------------------------------------
    def record(
        self,
        *,
        arm: Optional[str],
        exit_profile: Optional[str],
        ret: float,
        won: bool,
        p_model: float,
        price_cents: float,
        simulated: bool,
    ) -> None:
        """Feed one closed trade back.

        `ret` is realised P&L per dollar risked (what exits did to it included).
        `won` is whether the bet itself came in, i.e. what holding to the final
        would have done, so win rates stay comparable with the price paid. For an
        early exit that is not known yet: pass False and call `credit_win` later.
        """
        won = int(won)
        prefix = "sim_" if simulated else ""
        for key, kind in ((arm, "entry"), (exit_profile, "exit")):
            if not key:
                continue
            self._arm(key, kind)
            self.db.execute(
                f"UPDATE arms SET {prefix}n={prefix}n+1, {prefix}wins={prefix}wins+?, "
                f"{prefix}sum_ret={prefix}sum_ret+?, sum_prior=sum_prior+?, sum_price=sum_price+? "
                "WHERE key=? AND kind=?",
                [won, ret, p_model, price_cents, key, kind],
            )

    def credit_win(self, arm: Optional[str], exit_profile: Optional[str], simulated: bool) -> None:
        """An early exit's game went final and the bet would have won."""
        prefix = "sim_" if simulated else ""
        for key, kind in ((arm, "entry"), (exit_profile, "exit")):
            if key:
                self.db.execute(f"UPDATE arms SET {prefix}wins={prefix}wins+1 WHERE key=? AND kind=?", [key, kind])

    def record_exit_verdict(self, exit_profile: Optional[str], verdict: str) -> None:
        if not exit_profile or verdict not in ("saved", "shaken_out"):
            return
        self._arm(exit_profile, "exit")
        col = "saved" if verdict == "saved" else "shaken"
        self.db.execute(f"UPDATE arms SET {col}={col}+1 WHERE key=? AND kind='exit'", [exit_profile])

    # -- reporting -------------------------------------------------------------
    def arms(self) -> list[dict[str, Any]]:
        rows = {r["key"]: r for r in self.db.query("SELECT * FROM arms WHERE kind='entry'")}
        out = []
        for b_lo, b_hi, b_name in BUFFER_BUCKETS:
            for t_lo, t_hi, t_name in TIME_BUCKETS:
                for m_lo, m_hi, m_name in MARGIN_BUCKETS:
                    key = f"{b_name}|{t_name}|{m_name}"
                    row = rows.get(key)
                    seen = (row["n"] + row["sim_n"]) if row else 0
                    if seen:
                        prior = row["sum_prior"] / seen
                        price = row["sum_price"] / seen
                    else:
                        prior = _typical_p(b_lo, b_hi, t_lo, t_hi, m_lo, m_hi)
                        price = 94.0
                    n_eff, wins_eff, total = self._effective(row) if row else (0.0, 0.0, 0.0)
                    out.append(
                        {
                            "key": key,
                            "label": f"{b_name} pts · {t_name} min · {m_name}",
                            "dims": {"buffer": b_name, "time": t_name, "margin": m_name},
                            # n / wins are the evidence in play for the current environment;
                            # sim_n is practice on the side when looking at real markets.
                            "n": int(n_eff),
                            "wins": int(wins_eff),
                            "sim_n": (row["sim_n"] if row and self.env == "real" else 0),
                            "mean_return": round(total / n_eff, 4) if n_eff else 0.0,
                            "p_win": round((PRIOR_STRENGTH * prior + wins_eff) / (PRIOR_STRENGTH + n_eff), 4),
                            "prior": round(prior, 4),
                            "breakeven": round(price / 100.0, 4),
                        }
                    )
        return out

    def exit_arms(self) -> list[dict[str, Any]]:
        rows = {r["key"]: r for r in self.db.query("SELECT * FROM arms WHERE kind='exit'")}
        posts = {name: self._exit_posterior(name) for name in EXIT_PROFILES}
        picks = dict.fromkeys(EXIT_PROFILES, 0)
        sampler = random.Random(7)
        for _ in range(400):
            draws = {name: sampler.gauss(*posts[name]) for name in EXIT_PROFILES}
            picks[max(draws, key=draws.get)] += 1
        out = []
        for name, meta in EXIT_PROFILES.items():
            row = rows.get(name)
            n_eff, total = self._edge(row) if row else (0.0, 0.0)
            out.append(
                {
                    "key": name,
                    "label": meta["label"],
                    "description": meta["description"],
                    "n": int(n_eff),
                    "mean_return": round(total / n_eff, 4) if n_eff else 0.0,
                    "saved": row["saved"] if row else 0,
                    "shaken_out": row["shaken"] if row else 0,
                    "share": round(picks[name] / 400, 3),
                }
            )
        return out


def _typical_p(b_lo: float, b_hi: float, t_lo: float, t_hi: float, m_lo: float, m_hi: float) -> float:
    """Model win probability at the middle of a bucket, for arms with no trades yet."""
    buffer = (b_lo + min(b_hi, 18)) / 2
    minutes = (t_lo + min(t_hi, 12)) / 2
    margin = (m_lo + min(m_hi, 22)) / 2
    secs = minutes * 60
    total = 228.0 * (1 - secs / 2880)
    dist = distribution(total=total, secs_left=secs, margin=margin, period=4, pregame_total=228.0)
    return dist.p_under(dist.mean + buffer)
