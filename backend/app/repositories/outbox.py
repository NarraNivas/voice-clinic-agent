"""Staff requests and the CRM outbox. Only handoff state lives here, never caller free text."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

ISO = "%Y-%m-%dT%H:%M:%S"


@dataclass(frozen=True)
class OutboxRow:
    request_id: str
    payload: dict[str, Any]
    state: str
    attempts: int
    next_attempt_at: datetime
    last_error: str | None
    crm_case_ref: str | None


def create_staff_request(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    reason: str,
    appointment_id: int | None,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    """Record a staff request and its queued handoff. Call inside a transaction."""
    stamp = now.strftime(ISO)
    conn.execute(
        "INSERT INTO staff_requests (request_id, reason, appointment_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (request_id, reason, appointment_id, stamp),
    )
    conn.execute(
        """
        INSERT INTO outbox (request_id, payload_json, state, attempts, next_attempt_at, created_at)
        VALUES (?, ?, 'queued', 0, ?, ?)
        """,
        (request_id, json.dumps(payload, sort_keys=True), stamp, stamp),
    )


def get(conn: sqlite3.Connection, request_id: str) -> OutboxRow | None:
    row = conn.execute("SELECT * FROM outbox WHERE request_id = ?", (request_id,)).fetchone()
    return _to_row(row) if row else None


def due(conn: sqlite3.Connection, now: datetime, limit: int) -> list[OutboxRow]:
    rows = conn.execute(
        """
        SELECT * FROM outbox
        WHERE state = 'queued' AND next_attempt_at <= ?
        ORDER BY next_attempt_at, request_id
        LIMIT ?
        """,
        (now.strftime(ISO), limit),
    ).fetchall()
    return [_to_row(row) for row in rows]


def claim(conn: sqlite3.Connection, request_id: str, lease_until: datetime) -> None:
    """Push the next attempt out while a worker is sending. A second worker then skips this row."""
    conn.execute(
        "UPDATE outbox SET next_attempt_at = ? WHERE request_id = ?",
        (lease_until.strftime(ISO), request_id),
    )


def mark_delivered(
    conn: sqlite3.Connection, request_id: str, *, case_ref: str, attempts: int, now: datetime
) -> None:
    conn.execute(
        """
        UPDATE outbox
        SET state = 'delivered', attempts = ?, crm_case_ref = ?, last_error = NULL,
            delivered_at = ?
        WHERE request_id = ?
        """,
        (attempts, case_ref, now.strftime(ISO), request_id),
    )


def mark_retry(
    conn: sqlite3.Connection,
    request_id: str,
    *,
    attempts: int,
    next_attempt_at: datetime,
    error: str,
) -> None:
    conn.execute(
        """
        UPDATE outbox SET attempts = ?, next_attempt_at = ?, last_error = ? WHERE request_id = ?
        """,
        (attempts, next_attempt_at.strftime(ISO), error, request_id),
    )


def mark_failed(conn: sqlite3.Connection, request_id: str, *, attempts: int, error: str) -> None:
    conn.execute(
        "UPDATE outbox SET state = 'failed', attempts = ?, last_error = ? WHERE request_id = ?",
        (attempts, error, request_id),
    )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    result = {"queued": 0, "delivered": 0, "failed": 0}
    for row in conn.execute("SELECT state, COUNT(*) AS n FROM outbox GROUP BY state"):
        result[row["state"]] = row["n"]
    return result


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT o.request_id, o.state, o.attempts, o.next_attempt_at, o.last_error,
               o.crm_case_ref, s.reason
        FROM outbox o JOIN staff_requests s ON s.request_id = o.request_id
        ORDER BY o.created_at DESC, o.request_id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _to_row(row: sqlite3.Row) -> OutboxRow:
    return OutboxRow(
        request_id=row["request_id"],
        payload=json.loads(row["payload_json"]),
        state=row["state"],
        attempts=row["attempts"],
        next_attempt_at=datetime.strptime(row["next_attempt_at"], ISO),
        last_error=row["last_error"],
        crm_case_ref=row["crm_case_ref"],
    )
