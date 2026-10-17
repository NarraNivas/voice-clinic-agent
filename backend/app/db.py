"""SQLite connection, versioned schema migrations, and the transaction helper.

Migrations are plain SQL and Python functions, applied in order and recorded in
`schema_migrations`. Before the first upgrade of an existing file, the file is copied to a
`.before-vN.bak` sibling, so an upgrade can always be undone by hand.
"""

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """BEGIN IMMEDIATE, so a read-check-write sequence cannot interleave with another writer."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection. Autocommit mode, so write transactions are explicit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --- migration 1: the original tables ---------------------------------------------------

_V1_BASE = """
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


def _run_script(conn: sqlite3.Connection, script: str) -> None:
    """Run a multi-statement script inside the current transaction.

    `executescript` would commit any open transaction first, so the statements run one by one.
    The scripts here contain no semicolons inside strings or triggers, which keeps this simple.
    """
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    for statement in "\n".join(lines).split(";"):
        if statement.strip():
            conn.execute(statement)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split(maxsplit=1)[0]
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _migrate_v1(conn: sqlite3.Connection) -> None:
    _run_script(conn, _V1_BASE)


# --- migration 2: revisions, replayable outcomes, and older escalation rows -------------


def _migrate_v2(conn: sqlite3.Connection) -> None:
    # Every change to an appointment bumps its revision. A preview is bound to the revision
    # the caller reviewed, so a stale preview cannot act on a changed booking.
    _add_column(conn, "appointments", "revision INTEGER NOT NULL DEFAULT 0")
    _add_column(conn, "pending_confirmations", "preview_revision INTEGER NOT NULL DEFAULT 0")
    # A confirmed token stores its outcome, so a retry after a lost reply can be answered.
    _add_column(conn, "pending_confirmations", "result_json TEXT")
    # Earlier builds stored a free-text summary on escalations. The column is removed so
    # caller text cannot be written there.
    if "summary" in _columns(conn, "escalations"):
        _run_script(
            conn,
            """
            CREATE TABLE escalations_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            );
            INSERT INTO escalations_v2 (id, reason, status, created_at)
                SELECT id, reason, status, created_at FROM escalations;
            DROP TABLE escalations;
            ALTER TABLE escalations_v2 RENAME TO escalations;
            """,
        )


# --- migration 3: staff requests and the CRM outbox ------------------------------------

_V3_OUTBOX = """
CREATE TABLE IF NOT EXISTS staff_requests (
    request_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    appointment_id INTEGER,
    created_at TEXT NOT NULL
);

-- One row per handoff. Written in the same transaction as the staff request it belongs to.
CREATE TABLE IF NOT EXISTS outbox (
    request_id TEXT PRIMARY KEY REFERENCES staff_requests (request_id),
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'delivered', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    crm_case_ref TEXT,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_due ON outbox (state, next_attempt_at);
"""


def _migrate_v3(conn: sqlite3.Connection) -> None:
    _run_script(conn, _V3_OUTBOX)


# --- migration 4: providers, customers, closures, and staff request states -------------

_V4_SCHEDULING = """
CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO providers (id, name) VALUES (1, 'Dr. Ada Lin'), (2, 'Dr. Sam Okafor');

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- A whole day when a provider does not take bookings.
CREATE TABLE IF NOT EXISTS provider_closures (
    provider_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (provider_id, day)
);
"""


def _migrate_v4(conn: sqlite3.Connection) -> None:
    _run_script(conn, _V4_SCHEDULING)
    # Existing bookings belong to the first provider. Provider selection is optional on the
    # tool contract, so older calls keep working unchanged.
    _add_column(conn, "appointments", "provider_id INTEGER NOT NULL DEFAULT 1")
    _add_column(conn, "appointments", "customer_id INTEGER")
    _add_column(conn, "staff_requests", "status TEXT NOT NULL DEFAULT 'open'")
    _add_column(conn, "staff_requests", "updated_at TEXT")
    # The provider a preview chose is stored with its token, so a retry uses the same provider.
    _add_column(conn, "pending_confirmations", "provider_id INTEGER")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_appointments_provider "
        "ON appointments (provider_id, starts_at)"
    )


MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "original tables", _migrate_v1),
    (2, "revisions, replayable outcomes, escalation cleanup", _migrate_v2),
    (3, "staff requests and CRM outbox", _migrate_v3),
    (4, "providers, customers, closures, staff states", _migrate_v4),
]
LATEST_VERSION = MIGRATIONS[-1][0]


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    return {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(path: Path) -> list[int]:
    """Bring the database at `path` up to the latest schema. Returns the versions applied."""
    existed_with_data = path.exists() and path.stat().st_size > 0
    conn = connect(path)
    try:
        applied = _applied_versions(conn)
        pending = [m for m in MIGRATIONS if m[0] not in applied]
        if not pending:
            return []
        if existed_with_data:
            backup = path.with_name(f"{path.name}.before-v{pending[0][0]}.bak")
            if not backup.exists():
                shutil.copy2(path, backup)
        for version, description, apply in pending:
            with transaction(conn):
                apply(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, description, applied_at) "
                    "VALUES (?, ?, ?)",
                    (version, description, datetime.now(UTC).isoformat(timespec="seconds")),
                )
        return [version for version, _, _ in pending]
    finally:
        conn.close()


def init_db(path: Path) -> None:
    """Create or upgrade the database. Safe to call on every start."""
    migrate(path)
