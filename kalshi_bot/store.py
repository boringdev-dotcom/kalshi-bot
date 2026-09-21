"""SQLite journal for games, events, memory, trades, and LLM cost."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id TEXT PRIMARY KEY,
    kalshi_event_ticker TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    league TEXT,
    league_tier INTEGER,
    kickoff_ts INTEGER,
    status TEXT NOT NULL DEFAULT 'upcoming',
    fotmob_id TEXT,
    espn_id TEXT,
    home_goals INTEGER DEFAULT 0,
    away_goals INTEGER DEFAULT 0,
    minute INTEGER DEFAULT 0,
    phase TEXT DEFAULT 'upcoming',
    red_cards INTEGER DEFAULT 0,
    prematch_json TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    series_ticker TEXT,
    strike REAL,
    title TEXT,
    no_bid INTEGER,
    no_ask INTEGER,
    no_depth INTEGER,
    yes_bid INTEGER,
    yes_ask INTEGER,
    rem REAL,
    last_verdict TEXT,
    FOREIGN KEY(game_id) REFERENCES games(id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    minute INTEGER,
    payload_json TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_memory (
    game_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    notes TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (game_id, agent)
);

CREATE TABLE IF NOT EXISTS agent_verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    event_id INTEGER,
    agent TEXT NOT NULL,
    market_ticker TEXT,
    verdict TEXT,
    size_hint INTEGER,
    reason TEXT,
    raw_json TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key TEXT UNIQUE NOT NULL,
    game_id TEXT NOT NULL,
    market_ticker TEXT NOT NULL,
    event_id INTEGER,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    count INTEGER NOT NULL,
    price INTEGER,
    paper INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    kalshi_order_id TEXT,
    reason TEXT,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    market_ticker TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    side TEXT NOT NULL,
    count INTEGER NOT NULL,
    avg_price INTEGER,
    paper INTEGER NOT NULL DEFAULT 1,
    stopped INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT,
    agent TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS control (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL,
    event_id INTEGER,
    agent TEXT NOT NULL,
    market_ticker TEXT,
    action TEXT NOT NULL,
    size INTEGER,
    price INTEGER,
    rem REAL,
    reason TEXT,
    paper INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
"""


def _now() -> int:
    return int(time.time())


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                event_id INTEGER,
                agent TEXT NOT NULL,
                market_ticker TEXT,
                action TEXT NOT NULL,
                size INTEGER,
                price INTEGER,
                rem REAL,
                reason TEXT,
                paper INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
            """
        )

    def close(self) -> None:
        self._conn.close()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def get_control(self, key: str, default: Optional[str] = None) -> Optional[str]:
        rows = self._query("SELECT value FROM control WHERE key = ?", (key,))
        if not rows:
            return default
        return rows[0]["value"]

    def set_control(self, key: str, value: str) -> None:
        self._execute(
            "INSERT INTO control(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def is_paused(self) -> bool:
        return self.get_control("trading_paused", "false") == "true"

    def is_paper(self) -> bool:
        return self.get_control("paper_mode", "true") != "false"

    def set_paused(self, paused: bool) -> None:
        self.set_control("trading_paused", "true" if paused else "false")

    def set_paper(self, paper: bool) -> None:
        self.set_control("paper_mode", "true" if paper else "false")

    def pause_reason(self) -> Optional[str]:
        return self.get_control("pause_reason")

    def set_pause_reason(self, reason: Optional[str]) -> None:
        if reason:
            self.set_control("pause_reason", reason)
        else:
            self._execute("DELETE FROM control WHERE key=?", ("pause_reason",))

    def add_decision(self, row: dict[str, Any]) -> int:
        cur = self._execute(
            """
            INSERT INTO decisions(
                game_id, event_id, agent, market_ticker, action,
                size, price, rem, reason, paper, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["game_id"],
                row.get("event_id"),
                row.get("agent") or "kalshi",
                row.get("market_ticker"),
                row["action"],
                row.get("size") or 0,
                row.get("price"),
                row.get("rem"),
                row.get("reason") or "",
                1 if row.get("paper", True) else 0,
                _now(),
            ),
        )
        return int(cur.lastrowid)

    def decisions_for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM decisions WHERE game_id=? ORDER BY id", (game_id,))

    def recent_decisions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))

    def replay_games(self) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM games WHERE id LIKE 'REPLAY-%' OR status='replay' ORDER BY updated_at DESC"
        )
        return [self._hydrate_game(row) for row in rows]

    def clear_game_journal(self, game_id: str) -> None:
        for table in ("decisions", "orders", "positions", "events", "agent_verdicts", "agent_memory"):
            self._execute(f"DELETE FROM {table} WHERE game_id=?", (game_id,))

    def upsert_game(self, game: dict[str, Any]) -> None:
        now = _now()
        existing = self.get_game(game["id"])
        created = existing["created_at"] if existing else now
        self._execute(
            """
            INSERT INTO games(
                id, kalshi_event_ticker, home_team, away_team, league, league_tier,
                kickoff_ts, status, fotmob_id, espn_id, home_goals, away_goals,
                minute, phase, red_cards, prematch_json, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                kalshi_event_ticker=excluded.kalshi_event_ticker,
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                league=excluded.league,
                league_tier=excluded.league_tier,
                kickoff_ts=excluded.kickoff_ts,
                status=excluded.status,
                fotmob_id=COALESCE(excluded.fotmob_id, games.fotmob_id),
                espn_id=COALESCE(excluded.espn_id, games.espn_id),
                home_goals=excluded.home_goals,
                away_goals=excluded.away_goals,
                minute=excluded.minute,
                phase=excluded.phase,
                red_cards=excluded.red_cards,
                prematch_json=COALESCE(excluded.prematch_json, games.prematch_json),
                updated_at=excluded.updated_at
            """,
            (
                game["id"],
                game.get("kalshi_event_ticker"),
                game["home_team"],
                game["away_team"],
                game.get("league"),
                game.get("league_tier"),
                game.get("kickoff_ts"),
                game.get("status", "upcoming"),
                game.get("fotmob_id"),
                game.get("espn_id"),
                game.get("home_goals", 0),
                game.get("away_goals", 0),
                game.get("minute", 0),
                game.get("phase", "upcoming"),
                game.get("red_cards", 0),
                json.dumps(game["prematch"]) if game.get("prematch") is not None else game.get("prematch_json"),
                created,
                now,
            ),
        )

    def update_game_state(self, game_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k}=?" for k in fields)
        self._execute(
            f"UPDATE games SET {assignments} WHERE id=?",
            tuple(fields.values()) + (game_id,),
        )

    def set_prematch(self, game_id: str, prematch: dict[str, Any]) -> None:
        self.update_game_state(game_id, prematch_json=json.dumps(prematch))

    def get_game(self, game_id: str) -> Optional[dict[str, Any]]:
        rows = self._query("SELECT * FROM games WHERE id=?", (game_id,))
        if not rows:
            return None
        return self._hydrate_game(rows[0])

    def list_games(self, status: Optional[str] = None, upcoming_before: Optional[int] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM games"
        params: list[Any] = []
        clauses: list[str] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if upcoming_before is not None:
            clauses.append("kickoff_ts<=?")
            params.append(upcoming_before)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY kickoff_ts ASC"
        return [self._hydrate_game(row) for row in self._query(sql, tuple(params))]

    def upcoming_games(self, now_ts: Optional[int] = None, horizon_hours: int = 6) -> list[dict[str, Any]]:
        now_ts = now_ts or _now()
        until = now_ts + horizon_hours * 3600
        rows = self._query(
            """
            SELECT * FROM games
            WHERE status IN ('upcoming', 'live')
              AND kickoff_ts IS NOT NULL
              AND kickoff_ts >= ?
              AND kickoff_ts <= ?
            ORDER BY kickoff_ts ASC
            """,
            (now_ts - 3600, until),
        )
        return [self._hydrate_game(row) for row in rows]

    def live_games(self) -> list[dict[str, Any]]:
        return [self._hydrate_game(row) for row in self._query("SELECT * FROM games WHERE status='live' ORDER BY kickoff_ts")]

    def _hydrate_game(self, row: dict[str, Any]) -> dict[str, Any]:
        game = dict(row)
        raw = game.get("prematch_json")
        game["prematch"] = json.loads(raw) if raw else None
        game["markets"] = self.markets_for_game(game["id"])
        return game

    def upsert_market(self, market: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO markets(
                ticker, game_id, series_ticker, strike, title, no_bid, no_ask,
                no_depth, yes_bid, yes_ask, rem, last_verdict
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticker) DO UPDATE SET
                game_id=excluded.game_id,
                series_ticker=excluded.series_ticker,
                strike=excluded.strike,
                title=excluded.title,
                no_bid=excluded.no_bid,
                no_ask=excluded.no_ask,
                no_depth=excluded.no_depth,
                yes_bid=excluded.yes_bid,
                yes_ask=excluded.yes_ask,
                rem=excluded.rem,
                last_verdict=COALESCE(excluded.last_verdict, markets.last_verdict)
            """,
            (
                market["ticker"],
                market["game_id"],
                market.get("series_ticker"),
                market.get("strike"),
                market.get("title"),
                market.get("no_bid"),
                market.get("no_ask"),
                market.get("no_depth"),
                market.get("yes_bid"),
                market.get("yes_ask"),
                market.get("rem"),
                market.get("last_verdict"),
            ),
        )

    def markets_for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM markets WHERE game_id=? ORDER BY strike", (game_id,))

    def get_market(self, ticker: str) -> Optional[dict[str, Any]]:
        rows = self._query("SELECT * FROM markets WHERE ticker=?", (ticker,))
        return rows[0] if rows else None

    def add_event(self, game_id: str, event_type: str, minute: int, payload: dict[str, Any]) -> int:
        cur = self._execute(
            "INSERT INTO events(game_id, event_type, minute, payload_json, created_at) VALUES(?,?,?,?,?)",
            (game_id, event_type, minute, json.dumps(payload), _now()),
        )
        return int(cur.lastrowid)

    def events_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM events WHERE game_id=? ORDER BY id", (game_id,))
        for row in rows:
            row["payload"] = json.loads(row["payload_json"]) if row.get("payload_json") else {}
        return rows

    def events_since(self, last_id: int) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM events WHERE id>? ORDER BY id", (last_id,))
        for row in rows:
            row["payload"] = json.loads(row["payload_json"]) if row.get("payload_json") else {}
        return rows

    def latest_event_id(self) -> int:
        rows = self._query("SELECT COALESCE(MAX(id), 0) AS max_id FROM events")
        return int(rows[0]["max_id"]) if rows else 0

    def get_memory(self, game_id: str, agent: str) -> str:
        rows = self._query(
            "SELECT notes FROM agent_memory WHERE game_id=? AND agent=?",
            (game_id, agent),
        )
        return rows[0]["notes"] if rows else ""

    def set_memory(self, game_id: str, agent: str, notes: str) -> None:
        self._execute(
            """
            INSERT INTO agent_memory(game_id, agent, notes, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(game_id, agent) DO UPDATE SET notes=excluded.notes, updated_at=excluded.updated_at
            """,
            (game_id, agent, notes, _now()),
        )

    def add_verdict(
        self,
        game_id: str,
        agent: str,
        event_id: Optional[int],
        market_ticker: Optional[str],
        verdict: Optional[str],
        size_hint: Optional[int],
        reason: str,
        raw: Any,
    ) -> None:
        self._execute(
            """
            INSERT INTO agent_verdicts(
                game_id, event_id, agent, market_ticker, verdict, size_hint, reason, raw_json, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                game_id,
                event_id,
                agent,
                market_ticker,
                verdict,
                size_hint,
                reason,
                json.dumps(raw),
                _now(),
            ),
        )
        if market_ticker and verdict:
            self._execute(
                "UPDATE markets SET last_verdict=? WHERE ticker=?",
                (verdict, market_ticker),
            )

    def verdicts_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM agent_verdicts WHERE game_id=? ORDER BY id",
            (game_id,),
        )
        for row in rows:
            row["raw"] = json.loads(row["raw_json"]) if row.get("raw_json") else None
        return rows

    def latest_verdicts(self, game_id: str, agent: str = "pundit") -> dict[str, dict[str, Any]]:
        rows = self._query(
            """
            SELECT * FROM agent_verdicts
            WHERE game_id=? AND agent=?
            ORDER BY id DESC
            """,
            (game_id, agent),
        )
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            ticker = row.get("market_ticker")
            if ticker and ticker not in latest:
                latest[ticker] = row
        return latest

    def find_order(self, idempotency_key: str) -> Optional[dict[str, Any]]:
        rows = self._query("SELECT * FROM orders WHERE idempotency_key=?", (idempotency_key,))
        return rows[0] if rows else None

    def add_order(self, order: dict[str, Any]) -> int:
        cur = self._execute(
            """
            INSERT INTO orders(
                idempotency_key, game_id, market_ticker, event_id, side, action,
                count, price, paper, status, kalshi_order_id, reason, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order["idempotency_key"],
                order["game_id"],
                order["market_ticker"],
                order.get("event_id"),
                order["side"],
                order["action"],
                order["count"],
                order.get("price"),
                1 if order.get("paper", True) else 0,
                order.get("status", "submitted"),
                order.get("kalshi_order_id"),
                order.get("reason"),
                _now(),
            ),
        )
        return int(cur.lastrowid)

    def orders_for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM orders WHERE game_id=? ORDER BY id", (game_id,))

    def orders_today(self, day_start_ts: int) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM orders WHERE created_at>=? ORDER BY id", (day_start_ts,))

    def upsert_position(self, position: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO positions(market_ticker, game_id, side, count, avg_price, paper, stopped, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(market_ticker) DO UPDATE SET
                game_id=excluded.game_id,
                side=excluded.side,
                count=excluded.count,
                avg_price=excluded.avg_price,
                paper=excluded.paper,
                stopped=excluded.stopped,
                updated_at=excluded.updated_at
            """,
            (
                position["market_ticker"],
                position["game_id"],
                position.get("side", "no"),
                position["count"],
                position.get("avg_price"),
                1 if position.get("paper", True) else 0,
                1 if position.get("stopped") else 0,
                _now(),
            ),
        )

    def get_position(self, ticker: str) -> Optional[dict[str, Any]]:
        rows = self._query("SELECT * FROM positions WHERE market_ticker=?", (ticker,))
        return rows[0] if rows else None

    def positions_for_game(self, game_id: str) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM positions WHERE game_id=?", (game_id,))

    def open_positions(self) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM positions WHERE count>0 ORDER BY updated_at DESC")

    def add_llm_cost(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        game_id: Optional[str] = None,
    ) -> None:
        self._execute(
            """
            INSERT INTO llm_costs(game_id, agent, model, input_tokens, output_tokens, cost_usd, created_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (game_id, agent, model, input_tokens, output_tokens, cost_usd, _now()),
        )

    def costs(self, since_ts: Optional[int] = None, game_id: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM llm_costs"
        clauses: list[str] = []
        params: list[Any] = []
        if since_ts is not None:
            clauses.append("created_at>=?")
            params.append(since_ts)
        if game_id:
            clauses.append("game_id=?")
            params.append(game_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC"
        return self._query(sql, tuple(params))

    def cost_summary(self, since_ts: Optional[int] = None) -> dict[str, Any]:
        rows = self.costs(since_ts=since_ts)
        by_game: dict[str, dict[str, Any]] = {}
        total = 0.0
        tokens_in = 0
        tokens_out = 0
        for row in rows:
            total += row["cost_usd"] or 0
            tokens_in += row["input_tokens"] or 0
            tokens_out += row["output_tokens"] or 0
            gid = row.get("game_id") or "unassigned"
            bucket = by_game.setdefault(
                gid,
                {"game_id": gid, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            bucket["calls"] += 1
            bucket["input_tokens"] += row["input_tokens"] or 0
            bucket["output_tokens"] += row["output_tokens"] or 0
            bucket["cost_usd"] += row["cost_usd"] or 0
        return {
            "calls": len(rows),
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "cost_usd": round(total, 6),
            "by_game": list(by_game.values()),
            "rows": rows,
        }
