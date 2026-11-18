"""SQLite persistence: one file, one connection, a lock around writes."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- One row per position, open or closed. A closed position is a "trade".
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  status TEXT NOT NULL DEFAULT 'open',
  game_id TEXT NOT NULL,
  game_label TEXT NOT NULL,
  ticker TEXT NOT NULL,
  strike REAL NOT NULL,
  side TEXT NOT NULL,
  segment TEXT NOT NULL DEFAULT 'game',
  kind TEXT NOT NULL DEFAULT 'total',
  team TEXT,
  label TEXT,
  contracts INTEGER NOT NULL,
  entry_price INTEGER NOT NULL,
  cost REAL NOT NULL,
  fees REAL NOT NULL DEFAULT 0,
  opened_at TEXT NOT NULL,
  opened_by TEXT NOT NULL,
  mode TEXT NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  training INTEGER NOT NULL DEFAULT 0,
  strategy_id TEXT,
  exit_profile TEXT,
  arm_key TEXT,
  p_win_entry REAL NOT NULL DEFAULT 0,
  context TEXT NOT NULL DEFAULT '{}',
  memory_ids TEXT NOT NULL DEFAULT '[]',
  exit_price INTEGER,
  closed_at TEXT,
  pnl REAL,
  exit_reason TEXT,
  counterfactual_pnl REAL,
  exit_verdict TEXT,
  final_total INTEGER
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status, training);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  game_id TEXT,
  game_label TEXT,
  kind TEXT NOT NULL,
  ticker TEXT,
  headline TEXT NOT NULL,
  reasoning TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  data TEXT NOT NULL DEFAULT '{}',
  source TEXT NOT NULL DEFAULT 'rules',
  memory_ids TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  text TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  importance REAL NOT NULL DEFAULT 0.5,
  support INTEGER NOT NULL DEFAULT 0,
  against INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'agent',
  simulated INTEGER NOT NULL DEFAULT 0,
  trade_id INTEGER,
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  uses INTEGER NOT NULL DEFAULT 0
);

-- Learner statistics. kind = 'entry' | 'exit'. Real and simulated evidence
-- are kept apart so simulated practice can be down-weighted.
CREATE TABLE IF NOT EXISTS arms (
  key TEXT NOT NULL,
  kind TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  wins INTEGER NOT NULL DEFAULT 0,
  sum_ret REAL NOT NULL DEFAULT 0,
  sim_n INTEGER NOT NULL DEFAULT 0,
  sim_wins INTEGER NOT NULL DEFAULT 0,
  sim_sum_ret REAL NOT NULL DEFAULT 0,
  sum_prior REAL NOT NULL DEFAULT 0,
  sum_price REAL NOT NULL DEFAULT 0,
  saved INTEGER NOT NULL DEFAULT 0,
  shaken INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (key, kind)
);

CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  ts TEXT NOT NULL,
  tools TEXT NOT NULL DEFAULT '[]'
);

-- The shadow book: quarter markets the agent watched but did not trade.
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  game_id TEXT NOT NULL,
  game_label TEXT NOT NULL,
  simulated INTEGER NOT NULL DEFAULT 0,
  segment TEXT NOT NULL,
  kind TEXT NOT NULL,
  ticker TEXT NOT NULL,
  team TEXT,
  strike REAL NOT NULL,
  checkpoint TEXT NOT NULL,
  yes_ask INTEGER NOT NULL,
  no_ask INTEGER NOT NULL,
  p_yes REAL NOT NULL,
  outcome_yes INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (ticker, checkpoint)
);
CREATE INDEX IF NOT EXISTS idx_observations_game ON observations(game_id, segment);

CREATE TABLE IF NOT EXISTS equity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  book TEXT NOT NULL,
  equity REAL NOT NULL
);
"""

# Columns added after a database may already exist: (table, column, definition).
MIGRATIONS = [
    ("positions", "segment", "TEXT NOT NULL DEFAULT 'game'"),
    ("positions", "kind", "TEXT NOT NULL DEFAULT 'total'"),
    ("positions", "team", "TEXT"),
    ("positions", "label", "TEXT"),
]

JSON_COLUMNS = {"context", "memory_ids", "data", "tags", "tools"}
BOOL_COLUMNS = {"simulated", "training", "pinned"}


class DB:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            for table, column, definition in MIGRATIONS:
                have = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # -- generic -----------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, tuple(params))
            return cur.lastrowid or 0

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(sql, tuple(params)).fetchall()
        return [_decode(r) for r in rows]

    def one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def insert(self, table: str, row: dict[str, Any]) -> int:
        cols = list(row)
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        return self.execute(sql, [_encode(c, row[c]) for c in cols])

    def update(self, table: str, row_id: int, fields: dict[str, Any]) -> None:
        if not fields:
            return
        sets = ",".join(f"{c}=?" for c in fields)
        self.execute(
            f"UPDATE {table} SET {sets} WHERE id=?",
            [_encode(c, v) for c, v in fields.items()] + [row_id],
        )

    # -- key/value ---------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", [key])
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [key, json.dumps(value)],
        )


def _encode(col: str, value: Any) -> Any:
    if col in JSON_COLUMNS:
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _decode(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for col in out:
        if col in JSON_COLUMNS and isinstance(out[col], str):
            out[col] = json.loads(out[col])
        elif col in BOOL_COLUMNS and out[col] is not None:
            out[col] = bool(out[col])
    return out
