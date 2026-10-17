"""Appointment persistence. Times are stored as ISO strings in clinic-local time."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from app.db import transaction
from app.models.domain import Appointment

ISO_MINUTES = "%Y-%m-%dT%H:%M"


class AppointmentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE: the overlap check and insert cannot interleave with another writer."""
        with transaction(self.conn):
            yield

    def booked_on(self, day: date, provider_id: int | None = None) -> list[Appointment]:
        start = datetime.combine(day, datetime.min.time())
        end = start + timedelta(days=1)
        sql = """
            SELECT * FROM appointments
            WHERE status = 'booked' AND starts_at >= ? AND starts_at < ?
        """
        params: list[object] = [start.strftime(ISO_MINUTES), end.strftime(ISO_MINUTES)]
        if provider_id is not None:
            sql += " AND provider_id = ?"
            params.append(provider_id)
        rows = self.conn.execute(sql + " ORDER BY starts_at", params).fetchall()
        return [_to_domain(row) for row in rows]

    def provider_ids(self) -> list[int]:
        rows = self.conn.execute("SELECT id FROM providers WHERE active = 1 ORDER BY id").fetchall()
        return [row["id"] for row in rows]

    def provider_exists(self, provider_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM providers WHERE id = ? AND active = 1", (provider_id,)
        ).fetchone()
        return row is not None

    def is_closed(self, provider_id: int, day: date) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM provider_closures WHERE provider_id = ? AND day = ?",
            (provider_id, day.isoformat()),
        ).fetchone()
        return row is not None

    def get_by_code(self, confirmation_code: str) -> Appointment | None:
        row = self.conn.execute(
            "SELECT * FROM appointments WHERE confirmation_code = ?", (confirmation_code,)
        ).fetchone()
        return _to_domain(row) if row else None

    def get_by_id(self, appointment_id: int) -> Appointment | None:
        row = self.conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        return _to_domain(row) if row else None

    def get_by_idempotency_key(self, key: str) -> Appointment | None:
        row = self.conn.execute(
            "SELECT * FROM appointments WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return _to_domain(row) if row else None

    def insert(
        self,
        *,
        confirmation_code: str,
        patient_name: str,
        appointment_type: str,
        starts_at: datetime,
        duration_minutes: int,
        idempotency_key: str | None,
        now: datetime,
        provider_id: int = 1,
        customer_id: int | None = None,
    ) -> Appointment:
        stamp = now.isoformat(timespec="seconds")
        cursor = self.conn.execute(
            """
            INSERT INTO appointments (
                confirmation_code, patient_name, appointment_type, starts_at,
                duration_minutes, status, idempotency_key, created_at, updated_at,
                provider_id, customer_id
            ) VALUES (?, ?, ?, ?, ?, 'booked', ?, ?, ?, ?, ?)
            """,
            (
                confirmation_code,
                patient_name,
                appointment_type,
                starts_at.strftime(ISO_MINUTES),
                duration_minutes,
                idempotency_key,
                stamp,
                stamp,
                provider_id,
                customer_id,
            ),
        )
        appointment_id = cursor.lastrowid
        row = self.conn.execute(
            "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
        ).fetchone()
        return _to_domain(row)

    def move(self, appointment_id: int, starts_at: datetime, now: datetime) -> None:
        self.conn.execute(
            "UPDATE appointments SET starts_at = ?, updated_at = ?, revision = revision + 1 "
            "WHERE id = ?",
            (starts_at.strftime(ISO_MINUTES), now.isoformat(timespec="seconds"), appointment_id),
        )

    def set_status(self, appointment_id: int, status: str, now: datetime) -> None:
        self.conn.execute(
            "UPDATE appointments SET status = ?, updated_at = ?, revision = revision + 1 "
            "WHERE id = ?",
            (status, now.isoformat(timespec="seconds"), appointment_id),
        )


def _to_domain(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=row["id"],
        confirmation_code=row["confirmation_code"],
        patient_name=row["patient_name"],
        appointment_type=row["appointment_type"],
        starts_at=datetime.strptime(row["starts_at"], ISO_MINUTES),
        duration_minutes=row["duration_minutes"],
        status=row["status"],
        idempotency_key=row["idempotency_key"],
        revision=row["revision"],
        provider_id=row["provider_id"],
    )
