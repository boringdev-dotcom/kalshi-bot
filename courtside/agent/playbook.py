"""The playbook: the user's strategies as tunable parameters.

Sliders in the UI, the chat agent and plain-language guidance all end up here,
so there is exactly one place that says how the agent trades.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from ..db import DB

Q4_UNDER = "nba_q4_under"


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    help: str
    group: str
    default: float
    min: float
    max: float
    step: float
    unit: str


STRATEGIES: dict[str, dict[str, Any]] = {
    Q4_UNDER: {
        "name": "4th-quarter under",
        "description": (
            "In the fourth quarter, buy the under on a total well above the live betting line: "
            "a high-probability position that pays a few cents on the dollar. Get out for a small "
            "loss if the game starts threatening the number."
        ),
        "specs": [
            Spec("max_minutes_left", "Start looking at", "Begin scanning once this much of Q4 remains.", "entry", 8, 1, 12, 0.5, "min"),
            Spec("min_minutes_left", "Stop opening at", "No new positions inside this much time. Late entries pay little and carry foul/OT risk.", "entry", 2.5, 0, 8, 0.5, "min"),
            Spec("buffer_min", "Minimum cushion", "The strike must sit at least this far above the live line (line 240 → 250+).", "entry", 10, 4, 25, 0.5, "pts"),
            Spec("buffer_max", "Maximum cushion", "Further out than this pays too little to be worth the tail risk.", "entry", 14, 5, 35, 0.5, "pts"),
            Spec("min_price", "Lowest price to pay", "Cheaper than this means the market sees real danger.", "entry", 90, 70, 98, 1, "¢"),
            Spec("max_price", "Highest price to pay", "Above this the payout is too thin (96¢ pays about 4%).", "entry", 96, 80, 99, 1, "¢"),
            Spec("min_edge", "Model veto", "Model win chance minus the price. At -1 the agent follows your rule unless the model thinks you are overpaying by more than a point; raise it to only take trades the model likes.", "entry", -1.0, -5, 8, 0.25, "%"),
            Spec("skip_close_margin", "Skip tight games", "With under 5:00 left, skip games within this many points (fouling and overtime risk).", "entry", 4, 0, 10, 1, "pts"),
            Spec("stake", "Stake per trade", "Dollars put down on each entry. $300 at 94¢ wins about $19.", "sizing", 300, 10, 2000, 10, "$"),
            Spec("min_p_win", "Bail-out win chance", "Sell if the model's chance of winning drops below this.", "exit", 78, 50, 97, 1, "%"),
            Spec("stop_loss", "Stop loss", "Sell if the price falls this many cents below the entry.", "exit", 12, 2, 40, 1, "¢"),
            Spec("max_ot_risk", "Overtime guard", "Sell if overtime becomes this likely and an extra period would break the strike.", "exit", 22, 3, 50, 1, "%"),
            Spec("take_profit", "Take profit at", "Sell early once the bid reaches this. 100 means always hold to settlement.", "exit", 99, 90, 100, 1, "¢"),
        ],
    }
}


class Playbook:
    def __init__(self, db: DB):
        self.db = db

    def _stored(self, strategy_id: str) -> dict[str, Any]:
        return self.db.get(f"playbook:{strategy_id}", {"enabled": True, "params": {}})

    def enabled(self, strategy_id: str) -> bool:
        return bool(self._stored(strategy_id).get("enabled", True))

    def params(self, strategy_id: str) -> dict[str, float]:
        stored = self._stored(strategy_id).get("params", {})
        return {s.key: float(stored.get(s.key, s.default)) for s in STRATEGIES[strategy_id]["specs"]}

    def update(
        self,
        strategy_id: str,
        enabled: Optional[bool] = None,
        params: Optional[dict[str, float]] = None,
    ) -> dict[str, tuple[float, float]]:
        """Apply changes, clamped to each parameter's range. Returns {key: (old, new)}."""
        if strategy_id not in STRATEGIES:
            raise KeyError(f"Unknown strategy '{strategy_id}'")
        stored = self._stored(strategy_id)
        current = self.params(strategy_id)
        specs = {s.key: s for s in STRATEGIES[strategy_id]["specs"]}
        changed: dict[str, tuple[float, float]] = {}
        for key, value in (params or {}).items():
            if key not in specs:
                raise KeyError(f"Unknown parameter '{key}'. Valid: {', '.join(specs)}")
            spec = specs[key]
            value = min(max(float(value), spec.min), spec.max)
            if value != current[key]:
                changed[key] = (current[key], value)
                current[key] = value
        # Keep paired ranges coherent rather than rejecting the edit.
        current["buffer_max"] = max(current["buffer_max"], current["buffer_min"])
        current["max_price"] = max(current["max_price"], current["min_price"])
        current["max_minutes_left"] = max(current["max_minutes_left"], current["min_minutes_left"])
        stored["params"] = current
        if enabled is not None:
            stored["enabled"] = bool(enabled)
        self.db.set(f"playbook:{strategy_id}", stored)
        return changed

    def to_api(self) -> list[dict[str, Any]]:
        out = []
        for sid, meta in STRATEGIES.items():
            values = self.params(sid)
            stats = self.db.one(
                "SELECT COUNT(*) n, COALESCE(SUM(pnl > 0), 0) wins, COALESCE(SUM(pnl), 0) pnl "
                "FROM positions WHERE status='closed' AND training=0 AND strategy_id=?",
                [sid],
            ) or {"n": 0, "wins": 0, "pnl": 0}
            out.append(
                {
                    "id": sid,
                    "name": meta["name"],
                    "description": meta["description"],
                    "enabled": self.enabled(sid),
                    "params": [
                        {**{k: v for k, v in asdict(s).items() if k != "default"}, "value": values[s.key]}
                        for s in meta["specs"]
                    ],
                    "stats": {
                        "trades": stats["n"],
                        "win_rate": round(stats["wins"] / stats["n"], 3) if stats["n"] else 0.0,
                        "pnl": round(stats["pnl"], 2),
                    },
                }
            )
        return out

    def describe(self, strategy_id: str = Q4_UNDER) -> str:
        p = self.params(strategy_id)
        return (
            f"Q4 with {p['min_minutes_left']:g}-{p['max_minutes_left']:g} min left: buy the under "
            f"{p['buffer_min']:g}-{p['buffer_max']:g} pts above the live line at {p['min_price']:g}-{p['max_price']:g}c, "
            f"${p['stake']:g} a trade, model veto at {p['min_edge']:g}% edge. Skip games within {p['skip_close_margin']:g} pts "
            f"under 5:00. Exit if win chance < {p['min_p_win']:g}%, price drops {p['stop_loss']:g}c, "
            f"or OT chance > {p['max_ot_risk']:g}% would break the strike. Take profit at {p['take_profit']:g}c."
        )
