"""The agent's long-term memory.

Three kinds of memory, all in one table:

* guidance - standing instructions from the user, in their own words.
* lesson   - something the agent concluded from results (its own reflection).
* episode  - a compact record of one trade and how it ended.

Before each decision the agent recalls the memories that match the situation
(same cushion, clock, game state, teams). After the trade settles, every
memory that was recalled for it is credited or debited by the outcome, so
advice that keeps being followed into losses loses its standing, and advice
that keeps working gains it.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..db import DB
from ..domain import now_iso

WORD = re.compile(r"[a-z0-9]+")
STOP = set("the a an and or of to in on at for with is it this that be was were will if as by from not".split())


def _tokens(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 1}


def confidence(row: dict[str, Any]) -> float:
    """Beta-style score. The user's word starts with more standing than the agent's guesses."""
    head_start = 3 if row["source"] == "user" else 1
    return (row["support"] + head_start) / (row["support"] + row["against"] + head_start + 1)


def to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "text": row["text"],
        "tags": row["tags"],
        "importance": round(row["importance"], 3),
        "confidence": round(confidence(row), 3),
        "support": row["support"],
        "against": row["against"],
        "pinned": row["pinned"],
        "source": row["source"],
        "simulated": row["simulated"],
        "trade_id": row["trade_id"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "uses": row["uses"],
    }


class MemoryStore:
    def __init__(self, db: DB):
        self.db = db

    def add(
        self,
        kind: str,
        text: str,
        *,
        tags: Iterable[str] = (),
        importance: float = 0.5,
        source: str = "agent",
        simulated: bool = False,
        trade_id: Optional[int] = None,
        pinned: bool = False,
    ) -> dict[str, Any]:
        row_id = self.db.insert(
            "memories",
            {
                "kind": kind,
                "text": text.strip(),
                "tags": sorted(set(tags)),
                "importance": min(max(importance, 0.0), 1.0),
                "source": source,
                "simulated": simulated,
                "trade_id": trade_id,
                "pinned": pinned,
                "created_at": now_iso(),
            },
        )
        return self.get(row_id)

    def get(self, memory_id: int) -> Optional[dict[str, Any]]:
        row = self.db.one("SELECT * FROM memories WHERE id=?", [memory_id])
        return to_api(row) if row else None

    def list(self, kind: Optional[str] = None, q: Optional[str] = None, limit: int = 300) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM memories", []
        if kind:
            sql += " WHERE kind=?"
            params.append(kind)
        rows = self.db.query(sql + " ORDER BY pinned DESC, id DESC LIMIT ?", params + [limit])
        if q:
            want = _tokens(q)
            rows = [r for r in rows if want & (_tokens(r["text"]) | {t.lower() for t in r["tags"]})]
        return [to_api(r) for r in rows]

    def update(self, memory_id: int, fields: dict[str, Any]) -> Optional[dict[str, Any]]:
        allowed = {k: v for k, v in fields.items() if k in ("pinned", "text", "importance", "tags") and v is not None}
        self.db.update("memories", memory_id, allowed)
        return self.get(memory_id)

    def delete(self, memory_id: int) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", [memory_id])

    def recall(self, tags: Iterable[str], text: str = "", k: int = 6, touch: bool = True) -> list[dict[str, Any]]:
        """The memories most relevant to a situation, best first.

        Relevance is tag overlap plus word overlap, weighted by how important
        and how well-supported the memory is. Pinned guidance always comes along.
        """
        want_tags = {t.lower() for t in tags}
        want_words = _tokens(text)
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in self.db.query("SELECT * FROM memories WHERE kind != 'episode' OR pinned = 1"):
            overlap = len(want_tags & {t.lower() for t in row["tags"]})
            words = len(want_words & _tokens(row["text"]))
            always = row["pinned"] or (row["kind"] == "guidance" and not row["tags"])
            if not (overlap or words or always):
                continue
            age_days = (now - datetime.fromisoformat(row["created_at"])).total_seconds() / 86400
            score = (
                2.0 * overlap
                + 0.6 * min(words, 5)
                + (2.5 if row["pinned"] else 0.0)
                + (1.5 if row["kind"] == "guidance" else 0.0)
            ) * (0.4 + row["importance"]) * (0.4 + confidence(row)) * (0.7 + 0.3 / (1 + age_days / 30))
            if row["simulated"]:
                score *= 0.6
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = [row for _, row in scored[:k]]
        if touch and chosen:
            marks = ",".join("?" * len(chosen))
            self.db.execute(
                f"UPDATE memories SET uses=uses+1, last_used_at=? WHERE id IN ({marks})",
                [now_iso()] + [r["id"] for r in chosen],
            )
        return [to_api(r) for r in chosen]

    def reinforce(self, memory_ids: Iterable[int], positive: bool) -> None:
        ids = list(memory_ids)
        if not ids:
            return
        col = "support" if positive else "against"
        marks = ",".join("?" * len(ids))
        self.db.execute(f"UPDATE memories SET {col}={col}+1 WHERE id IN ({marks})", ids)


def situation_tags(*, arm: str, home: str, away: str, p_ot: float = 0.0, pace_gap: float = 0.0, extra: Iterable[str] = ()) -> list[str]:
    """Tags describing a game situation, used both to store and to recall memories."""
    buffer, time, margin = arm.split("|")
    tags = ["nba", "q4_under", f"buffer:{buffer}", f"time:{time}", f"margin:{margin}", home.lower(), away.lower()]
    if margin == "close":
        tags.append("close_game")
    if margin == "blowout":
        tags.append("blowout")
    if p_ot >= 0.05:
        tags.append("ot_risk")
    if pace_gap >= 10:
        tags.append("hot_pace")
    if pace_gap <= -10:
        tags.append("slow_pace")
    if time == "0-3":
        tags.append("late")
    return tags + list(extra)
