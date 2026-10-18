"""Aggregates for the analytics dashboard. Counts and sums only: no names, no caller text.

Booking filters (provider, appointment type, date range) apply to the appointment queries.
The staff and handoff figures come from the request queue and are not filtered by them.
"""

import sqlite3
from typing import Any

WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _filters(
    provider_id: int | None,
    appointment_type: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if provider_id is not None:
        clauses.append("a.provider_id = ?")
        params.append(provider_id)
    if appointment_type is not None:
        clauses.append("a.appointment_type = ?")
        params.append(appointment_type)
    if date_from is not None:
        clauses.append("substr(a.starts_at, 1, 10) >= ?")
        params.append(date_from)
    if date_to is not None:
        clauses.append("substr(a.starts_at, 1, 10) <= ?")
        params.append(date_to)
    where = " AND ".join(clauses) if clauses else "1 = 1"
    return where, params


def dashboard(
    conn: sqlite3.Connection,
    *,
    provider_id: int | None = None,
    appointment_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    where, params = _filters(provider_id, appointment_type, date_from, date_to)

    totals = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               COALESCE(SUM(a.status = 'booked'), 0) AS booked,
               COALESCE(SUM(a.status = 'cancelled'), 0) AS cancelled,
               COALESCE(SUM(CASE WHEN a.status = 'booked' THEN a.duration_minutes END), 0)
                   AS booked_minutes
        FROM appointments a WHERE {where}
        """,
        params,
    ).fetchone()

    by_day = conn.execute(
        f"""
        SELECT substr(a.starts_at, 1, 10) AS day,
               SUM(a.status = 'booked') AS booked,
               SUM(a.status = 'cancelled') AS cancelled
        FROM appointments a WHERE {where}
        GROUP BY day ORDER BY day
        """,
        params,
    ).fetchall()

    by_type = conn.execute(
        f"""
        SELECT a.appointment_type AS name,
               SUM(a.status = 'booked') AS booked,
               SUM(a.status = 'cancelled') AS cancelled,
               COALESCE(SUM(CASE WHEN a.status = 'booked' THEN a.duration_minutes END), 0)
                   AS booked_minutes
        FROM appointments a WHERE {where}
        GROUP BY a.appointment_type ORDER BY booked DESC, name
        """,
        params,
    ).fetchall()

    by_provider = conn.execute(
        f"""
        SELECT p.id AS provider_id, p.name AS name,
               SUM(a.status = 'booked') AS booked,
               SUM(a.status = 'cancelled') AS cancelled,
               COALESCE(SUM(CASE WHEN a.status = 'booked' THEN a.duration_minutes END), 0)
                   AS booked_minutes
        FROM providers p
        LEFT JOIN appointments a ON a.provider_id = p.id AND {where}
        GROUP BY p.id ORDER BY p.id
        """,
        params,
    ).fetchall()

    heat = conn.execute(
        f"""
        SELECT CAST(strftime('%w', a.starts_at) AS INTEGER) AS weekday,
               CAST(substr(a.starts_at, 12, 2) AS INTEGER) AS hour,
               COUNT(*) AS booked
        FROM appointments a WHERE {where} AND a.status = 'booked'
        GROUP BY weekday, hour
        """,
        params,
    ).fetchall()

    staff = conn.execute(
        """
        SELECT s.reason AS reason, s.status AS status, COUNT(*) AS n
        FROM staff_requests s GROUP BY s.reason, s.status
        """
    ).fetchall()

    handoff = conn.execute(
        """
        SELECT COALESCE(o.state, 'not_queued') AS state, COUNT(*) AS n
        FROM staff_requests s LEFT JOIN outbox o ON o.request_id = s.request_id
        GROUP BY state
        """
    ).fetchall()

    booked = int(totals["booked"])
    cancelled = int(totals["cancelled"])
    cancel_rate = round(100 * cancelled / (booked + cancelled), 1) if booked + cancelled else 0.0

    return {
        "filters": {
            "provider_id": provider_id,
            "appointment_type": appointment_type,
            "date_from": date_from,
            "date_to": date_to,
        },
        "totals": {
            "appointments": int(totals["total"]),
            "booked": booked,
            "cancelled": cancelled,
            "cancel_rate": cancel_rate,
            "booked_minutes": int(totals["booked_minutes"]),
        },
        "by_day": [dict(row) for row in by_day],
        "by_type": [dict(row) for row in by_type],
        "by_provider": [dict(row) for row in by_provider],
        "heatmap": [
            {
                "weekday": WEEKDAYS[row["weekday"]],
                "weekday_index": row["weekday"],
                "hour": row["hour"],
                "booked": row["booked"],
            }
            for row in heat
        ],
        "staff": {
            "by_reason": [dict(row) for row in staff],
            "handoff": [dict(row) for row in handoff],
        },
    }
