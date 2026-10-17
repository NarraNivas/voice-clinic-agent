"""SQLite connection and schema setup."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    confirmation_code TEXT NOT NULL UNIQUE,
    patient_name TEXT NOT NULL,
    appointment_type TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('booked', 'cancelled')),
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appointments_starts_at ON appointments (starts_at);

CREATE TABLE IF NOT EXISTS pending_confirmations (
    token_hash TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    details_digest TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Reason only. Caller free text is never stored here.
CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection. Autocommit mode, so write transactions are explicit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
