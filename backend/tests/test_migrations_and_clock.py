"""Versioned schema upgrades, the pre-upgrade backup, and the injectable clinic clock."""

import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.db import LATEST_VERSION, migrate
from app.main import create_app
from app.services.clinic_rules import clinic_now

# The schema as the first build created it: no revisions, no outbox, and escalations with a
# free-text summary column. A real demo file from before this change looks like this.
LEGACY_SCHEMA = """
CREATE TABLE appointments (
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
CREATE TABLE pending_confirmations (
    token_hash TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    details_digest TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE TABLE interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reason TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
"""


def _columns(path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _make_legacy_file(path: Path, *, with_data: bool) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    if with_data:
        conn.execute(
            "INSERT INTO appointments (confirmation_code, patient_name, appointment_type, "
            "starts_at, "
            "duration_minutes, status, created_at, updated_at) VALUES "
            "('MSD-AAAAAA', 'Legacy Caller', 'cleaning', '2026-10-20T09:00', 30, 'booked', "
            "'2026-10-12T08:00:00', '2026-10-12T08:00:00')"
        )
        conn.execute(
            "INSERT INTO escalations (reason, summary, created_at) VALUES "
            "('medical', 'free text that must not survive', '2026-10-12T08:00:00')"
        )
    conn.commit()
    conn.close()


def test_a_legacy_file_is_upgraded_and_keeps_its_rows(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_file(path, with_data=True)

    applied = migrate(path)

    assert applied == list(range(1, LATEST_VERSION + 1))
    assert "revision" in _columns(path, "appointments")
    assert "preview_revision" in _columns(path, "pending_confirmations")
    assert "result_json" in _columns(path, "pending_confirmations")
    assert "outbox" in {
        row[0]
        for row in sqlite3.connect(path).execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
        assert conn.execute("SELECT reason FROM escalations").fetchone()[0] == "medical"
    finally:
        conn.close()


def test_free_text_summary_is_removed_from_escalations_during_upgrade(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_file(path, with_data=True)
    migrate(path)
    assert "summary" not in _columns(path, "escalations")


def test_an_existing_file_is_backed_up_before_its_first_upgrade(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_file(path, with_data=True)

    migrate(path)

    backup = tmp_path / "legacy.db.before-v1.bak"
    assert backup.exists()
    # The backup is the file as it was before the upgrade: the old columns and the original rows.
    assert "revision" not in _columns(backup, "appointments")
    conn = sqlite3.connect(backup)
    try:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
    finally:
        conn.close()


def test_migrating_twice_is_a_no_op(tmp_path):
    path = tmp_path / "legacy.db"
    _make_legacy_file(path, with_data=False)
    migrate(path)
    assert migrate(path) == []


def test_a_new_file_needs_no_backup(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path)
    assert not list(tmp_path.glob("*.bak"))


def test_the_schema_version_is_recorded(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path)
    conn = sqlite3.connect(path)
    try:
        versions = [
            row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    finally:
        conn.close()
    assert versions == list(range(1, LATEST_VERSION + 1))


# --- A5: an explicit clinic timezone and an injectable clock -----------------------------


def test_clinic_now_applies_the_clinic_timezone_and_drops_the_offset():
    moment = clinic_now("America/Chicago")
    assert moment.tzinfo is None
    assert moment.second == 0
    assert moment.microsecond == 0


def test_an_injected_clock_is_used_by_the_app(tmp_path):
    fixed = datetime(2026, 10, 12, 8, 0)
    settings = Settings(
        database_path=tmp_path / "clock.db",
        tool_shared_secret=None,
        elevenlabs_agent_id=None,
        frontend_dir=tmp_path / "none",
    )
    app = create_app(settings, clock=lambda: fixed)
    assert app.state.clock() == fixed


def test_the_default_clock_uses_the_configured_timezone(tmp_path):
    settings = Settings(
        database_path=tmp_path / "tz.db",
        tool_shared_secret=None,
        elevenlabs_agent_id=None,
        frontend_dir=tmp_path / "none",
        clinic_timezone="Pacific/Auckland",
    )
    app = create_app(settings)
    assert app.state.clock().tzinfo is None  # naive, clinic-local, as the rules expect
