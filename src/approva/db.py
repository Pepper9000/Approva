"""SQLite persistence helpers for requests, seed data, and tool records."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import yaml

from approva import config

DDL = """
CREATE TABLE IF NOT EXISTS employees(
  id TEXT PRIMARY KEY, name TEXT, email TEXT, role TEXT,
  manager_id TEXT, department TEXT);
CREATE TABLE IF NOT EXISTS vendors(
  name TEXT PRIMARY KEY, status TEXT, last_review TEXT);
CREATE TABLE IF NOT EXISTS requests(
  id TEXT PRIMARY KEY, requester_id TEXT, raw_text TEXT, status TEXT,
  created_at TEXT, updated_at TEXT, plan_json TEXT, parsed_json TEXT,
  policy_json TEXT, risk_json TEXT, decision_json TEXT, brief_json TEXT,
  annual_cost REAL, vendor_status TEXT, pipeline_tier TEXT,
  degraded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, role TEXT,
  approver_id TEXT, verdict TEXT, comment TEXT, ts TEXT,
  UNIQUE(request_id, role));
CREATE TABLE IF NOT EXISTS audit_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, ts TEXT,
  agent TEXT, step TEXT, status TEXT, summary TEXT, detail_json TEXT,
  latency_ms INTEGER, tokens_in INTEGER, tokens_out INTEGER,
  prev_hash TEXT, hash TEXT, body_json TEXT);
CREATE TABLE IF NOT EXISTS tool_calls(
  idem_key TEXT PRIMARY KEY, request_id TEXT, tool TEXT, args_json TEXT,
  ok INTEGER, ref_id TEXT, message TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS tickets(
  id TEXT PRIMARY KEY, queue TEXT, title TEXT, body TEXT, status TEXT,
  request_id TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS licenses(
  id TEXT PRIMARY KEY, vendor TEXT, item TEXT, seats INTEGER,
  requester_id TEXT, start_date TEXT, request_id TEXT);
CREATE TABLE IF NOT EXISTS ledger(
  id TEXT PRIMARY KEY, kind TEXT, payee TEXT, amount_inr REAL,
  category TEXT, requester_id TEXT, request_id TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, recipient TEXT,
  subject TEXT, body TEXT, delivered INTEGER, request_id TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS component_health(
  id INTEGER PRIMARY KEY AUTOINCREMENT, component TEXT, ts TEXT,
  ok INTEGER, latency_ms INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS id_sequences(prefix TEXT PRIMARY KEY, next_value INTEGER NOT NULL);
"""

TRANSACTIONAL_TABLES = (
    "requests", "approvals", "audit_events", "tool_calls", "tickets",
    "licenses", "ledger", "outbox", "id_sequences",
)


def _database(path: str | Path | None = None) -> Path:
    """Return the database path and create its parent directory."""
    target = Path(path) if path is not None else config.database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def connection(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open a configured SQLite connection for one operation."""
    conn = sqlite3.connect(_database(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | Path | None = None) -> None:
    """Create all application tables if they do not exist."""
    with connection(path) as conn:
        conn.executescript(DDL)


def seed_from_yaml(path: str | Path | None = None, db_path: str | Path | None = None) -> None:
    """Insert the configured employees and vendors without duplicating rows."""
    seed_path = Path(path) if path is not None else config.data_path("seed.yaml")
    with seed_path.open(encoding="utf-8") as seed_file:
        seed = yaml.safe_load(seed_file) or {}
    init_db(db_path)
    with connection(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO employees(id,name,email,role,manager_id,department) "
            "VALUES(:id,:name,:email,:role,:manager_id,:department)",
            seed.get("employees", []),
        )
        conn.executemany(
            "INSERT OR REPLACE INTO vendors(name,status,last_review) VALUES(:name,:status,:last_review)",
            seed.get("vendors", []),
        )


def get_request(request_id: str, db_path: str | Path | None = None) -> dict | None:
    """Fetch a request row as a dictionary, or return None when absent."""
    with connection(db_path) as conn:
        row = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
    return dict(row) if row else None


def save_request(request_id: str, db_path: str | Path | None = None, **fields: object) -> None:
    """Insert or update only recognized request fields."""
    allowed = {row[1] for row in _request_columns(db_path)} - {"id"}
    values = {key: value for key, value in fields.items() if key in allowed}
    values["id"] = request_id
    columns = list(values)
    updates = ",".join(f"{column}=excluded.{column}" for column in columns if column != "id")
    placeholders = ",".join(f":{column}" for column in columns)
    with connection(db_path) as conn:
        conn.execute(
            f"INSERT INTO requests ({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            values,
        )


def _request_columns(db_path: str | Path | None) -> list[sqlite3.Row]:
    """Return the current requests table column metadata."""
    init_db(db_path)
    with connection(db_path) as conn:
        return conn.execute("PRAGMA table_info(requests)").fetchall()


def get_approvals(request_id: str, db_path: str | Path | None = None) -> list[dict]:
    """Return approvals for a request in insertion order."""
    with connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE request_id=? ORDER BY id", (request_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def next_id(prefix: str, db_path: str | Path | None = None) -> str:
    """Allocate the next sequential human-readable identifier for a prefix."""
    with connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT next_value FROM id_sequences WHERE prefix=?", (prefix,)).fetchone()
        value = row[0] if row else 1
        conn.execute(
            "INSERT INTO id_sequences(prefix,next_value) VALUES(?,?) "
            "ON CONFLICT(prefix) DO UPDATE SET next_value=excluded.next_value",
            (prefix, value + 1),
        )
    return f"{prefix}-{value:04d}"


def reset_demo(db_path: str | Path | None = None) -> None:
    """Clear transactional demo data and reseed reference tables."""
    init_db(db_path)
    with connection(db_path) as conn:
        for table in TRANSACTIONAL_TABLES:
            conn.execute(f"DELETE FROM {table}")
    seed_from_yaml(db_path=db_path)