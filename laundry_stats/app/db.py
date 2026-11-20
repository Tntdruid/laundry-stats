import json
import sqlite3
import threading
from typing import Optional

from config import DB_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    machine      TEXT NOT NULL,     -- machine id (slug of its name)
    type         TEXT NOT NULL,     -- washer | dryer
    started_at   INTEGER NOT NULL,  -- unix seconds, UTC
    ended_at     INTEGER NOT NULL,
    minutes      REAL NOT NULL,
    kwh          REAL NOT NULL,
    cost         REAL,              -- kroner
    price        REAL,              -- average kr/kWh paid
    peak_w       REAL,
    heat_minutes INTEGER,           -- minutes above 1000 W (heating water or air)
    heat_kwh     REAL,
    profile      TEXT NOT NULL DEFAULT '[]',  -- JSON list: average watt per minute
    excluded     INTEGER NOT NULL DEFAULT 0,  -- 1 = started while skip_entity was on (e.g. descaling)
    source       TEXT,              -- live | history
    UNIQUE (machine, started_at)
);
CREATE INDEX IF NOT EXISTS idx_cycles_started ON cycles(started_at);
CREATE INDEX IF NOT EXISTS idx_cycles_machine ON cycles(machine);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

DB_NAME = "laundry_stats.db"
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_DIR / DB_NAME, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def get_meta(key: str) -> Optional[str]:
    rows = query("SELECT value FROM meta WHERE key = ?", [key])
    return rows[0]["value"] if rows else None


def set_meta(key: str, value: str) -> None:
    execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [key, value])


def delete_meta_like(pattern: str) -> None:
    execute("DELETE FROM meta WHERE key LIKE ?", [pattern])


def query(sql: str, params=()) -> list:
    with _lock:
        return [dict(r) for r in connect().execute(sql, params).fetchall()]


def execute(sql: str, params=()) -> None:
    with _lock:
        conn = connect()
        conn.execute(sql, params)
        conn.commit()


CYCLE_COLS = ["machine", "type", "started_at", "ended_at", "minutes", "kwh", "cost", "price", "peak_w",
              "heat_minutes", "heat_kwh", "profile", "excluded", "source"]


def insert_cycle(c: dict) -> Optional[int]:
    """Store a cycle unless one on the same machine already covers that time (a re-read of the history)."""
    with _lock:
        conn = connect()
        clash = conn.execute("SELECT id FROM cycles WHERE machine = ? AND started_at < ? AND ended_at > ?",
                             [c["machine"], c["ended_at"], c["started_at"]]).fetchone()
        if clash:
            return None
        cur = conn.execute(
            f"INSERT INTO cycles ({','.join(CYCLE_COLS)}) VALUES ({','.join('?' * len(CYCLE_COLS))})",
            [json.dumps(c[k]) if k == "profile" else c.get(k) for k in CYCLE_COLS])
        conn.commit()
        return cur.lastrowid


def cycle_rows(sql: str, params=()) -> list:
    """Like query(), with the profile decoded."""
    rows = query(sql, params)
    for r in rows:
        if "profile" in r:
            r["profile"] = json.loads(r["profile"] or "[]")
    return rows
