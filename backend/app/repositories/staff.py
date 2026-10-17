"""Staff requests: what the clinic team sees, and the state they move it through.

A request is open, in progress, or resolved. The handoff delivery state (queued, delivered, or
failed) is shown next to it, but the two are separate: a request can be delivered and still open.
Nothing here stores caller free text.
"""

import sqlite3
from datetime import datetime
from typing import Any

STATUSES = ("open", "in_progress", "resolved")
ISO = "%Y-%m-%dT%H:%M:%S"


def list_requests(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.request_id, s.reason, s.status, s.appointment_id, s.created_at,
               s.updated_at, o.state AS handoff_state, o.attempts, o.last_error
        FROM staff_requests s
        LEFT JOIN outbox o ON o.request_id = s.request_id
        ORDER BY s.created_at DESC, s.request_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def set_status(conn: sqlite3.Connection, request_id: str, status: str, now: datetime) -> bool:
    cursor = conn.execute(
        "UPDATE staff_requests SET status = ?, updated_at = ? WHERE request_id = ?",
        (status, now.strftime(ISO), request_id),
    )
    return cursor.rowcount == 1


def set_status_for_reason(
    conn: sqlite3.Connection, reason: str, status: str, now: datetime
) -> None:
    """Move the newest request with this reason to a new state. Used by the demo seed."""
    row = conn.execute(
        "SELECT request_id FROM staff_requests WHERE reason = ? "
        "ORDER BY created_at DESC, request_id DESC LIMIT 1",
        (reason,),
    ).fetchone()
    if row is not None:
        set_status(conn, row["request_id"], status, now)
