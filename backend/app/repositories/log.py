"""Interaction log and escalation queue.

Stores outcomes and internal references only: no transcripts, no caller free text,
no patient names, and no confirmation codes. Appointments are referenced by numeric id.
"""

import sqlite3
from datetime import datetime


def record_interaction(
    conn: sqlite3.Connection,
    *,
    channel: str,
    tool_name: str,
    outcome: str,
    summary: str,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO interactions (channel, tool_name, outcome, summary, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (channel, tool_name, outcome, summary[:300], now.isoformat(timespec="seconds")),
    )


def recent_interactions(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT channel, tool_name, outcome, summary, created_at
        FROM interactions ORDER BY id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def record_escalation(conn: sqlite3.Connection, *, reason: str, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO escalations (reason, created_at) VALUES (?, ?)",
        (reason, now.isoformat(timespec="seconds")),
    )
    return int(cursor.lastrowid or 0)
