"""Create a seeded, disposable demo database.

    cd backend && .venv/bin/python -m demo_data.seed                  # data/demo/clinic-demo.db
    cd backend && .venv/bin/python -m demo_data.seed --db PATH        # PATH must sit in data/demo/

The command refuses to overwrite a file it did not create. Use `demo_data.reset` to rebuild a
database that it did create. Every booking is written through the real booking rules, so the
data obeys the same constraints as live bookings.
"""

import argparse
import random
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from datetime import date, datetime, time, timedelta
from pathlib import Path

from app.config import BACKEND_DIR
from app.db import connect, init_db
from app.models.schemas import BookingRequest, CancelRequest
from app.repositories import staff as staff_repo
from app.repositories.appointments import AppointmentRepository
from app.services.booking import AppointmentService
from app.services.errors import ApiError
from app.services.escalation import escalate

DEMO_ROOT = BACKEND_DIR / "data" / "demo"
DEFAULT_DB = DEMO_ROOT / "clinic-demo.db"
MARKER_KEY = "fictional_demo_database"
SEED = 20261017
BASE_DATE = date(2026, 10, 19)  # a Monday. The seeded clock reads 08:00 on this day.
TOTAL_BOOKINGS = 60
CANCELLED_TARGET = 8
CLOSED_PROVIDER = 2
CLOSED_OFFSET_DAYS = 4

# Thirty invented customers. Some names are deliberately close, so matching is tested.
CUSTOMERS = [
    "Maria Lopez",
    "Maria Lopes",
    "Daniel Kim",
    "Danielle Kim",
    "Sam Patel",
    "Sam Patell",
    "Aisha Brown",
    "Kenji Sato",
    "Olivia Reyes",
    "Mateo Silva",
    "Priya Nair",
    "Liam Walsh",
    "Chloe Moreau",
    "Samuel Okafor",
    "Hana Ito",
    "Omar Haddad",
    "Grace Quinn",
    "Ethan Brandt",
    "Lucia Ortega",
    "Noah Ivanova",
    "Amara Nwosu",
    "Jonah Pierce",
    "Elena Costa",
    "Tomas Varga",
    "Rosa Delgado",
    "Felix Anders",
    "Yara Nasser",
    "Ben Adler",
    "Ines Moretti",
    "Victor Chan",
]

# Callers with no customer record. Their bookings have no customer id.
NEW_CALLERS = ["Walter Hale", "Ruth Mensah", "Theo Laurent", "Ava Lindqvist"]

# Named fixtures. The tests check each one against the database this command produces.
FIXTURES: dict[str, str] = {
    "full_morning_provider_1": "Provider 1 is fully booked from 09:00 to 12:30 on base day + 2.",
    "provider_2_closed": "Provider 2 is closed on base day + 4, so offers no slots that day.",
    "notice_window_change": "A late cancellation on base day is refused and queued for the clinic.",
    "similar_names": "Maria Lopez and Maria Lopes both have bookings, with different codes.",
    "new_caller": "A caller with no customer record has a booking with no customer id.",
    "cancelled_history": "Several historical bookings are cancelled, and their slots are free.",
    "staff_states": "The staff queue holds one request each in open, in progress, and resolved.",
}

Service = Callable[[datetime], AppointmentService]


def is_marked(path: Path) -> bool:
    """True only for a database this command created."""
    if not path.exists():
        return False
    conn = connect(path)
    try:
        _marker_table(conn)
        row = conn.execute(
            "SELECT value FROM demo_database WHERE key = ?", (MARKER_KEY,)
        ).fetchone()
        return row is not None and row["value"] == "true"
    finally:
        conn.close()


def check_location(path: Path, root: Path = DEMO_ROOT) -> Path:
    """Only a .db file inside the demo folder may be seeded or reset."""
    resolved = path.resolve()
    if resolved.suffix != ".db" or root.resolve() not in resolved.parents:
        raise ValueError(f"refusing {resolved}: demo databases must be .db files inside {root}")
    return resolved


def seed(
    path: Path = DEFAULT_DB, *, root: Path = DEMO_ROOT, base: date = BASE_DATE
) -> dict[str, int]:
    """Create the seeded database. Never overwrites an existing file."""
    target = check_location(path, root)
    if target.exists():
        raise FileExistsError(f"{target} exists. Use demo_data.reset to rebuild it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    init_db(target)
    conn = connect(target)
    try:
        _marker_table(conn)
        with conn:
            conn.execute("INSERT INTO demo_database (key, value) VALUES (?, 'true')", (MARKER_KEY,))
            conn.execute("INSERT INTO demo_database (key, value) VALUES ('seed', ?)", (str(SEED),))
            conn.execute(
                "INSERT INTO demo_database (key, value) VALUES ('base_date', ?)",
                (base.isoformat(),),
            )
        return _populate(conn, base)
    finally:
        conn.close()


def _marker_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS demo_database (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )


def _populate(conn: sqlite3.Connection, base: date) -> dict[str, int]:
    rng = random.Random(SEED)
    repo = AppointmentRepository(conn)
    customer_ids = _insert_customers(conn, base)
    closed_day = base + timedelta(days=CLOSED_OFFSET_DAYS)
    conn.execute(
        "INSERT INTO provider_closures (provider_id, day, reason) VALUES (?, ?, 'Training day')",
        (CLOSED_PROVIDER, closed_day.isoformat()),
    )

    def service_at(moment: datetime) -> AppointmentService:
        return AppointmentService(repo, channel="demo", clock=lambda: moment)

    def book_first_free(
        day: date, provider: int, kind: str, name: str, customer: int | None
    ) -> int | None:
        """Book a random free start time for this provider on this day, as it would have been."""
        created = datetime.combine(day - timedelta(days=rng.randint(3, 9)), time(10))
        slots = service_at(created).availability(day, kind, provider).slots
        if not slots:
            return None
        request = {
            "patient_name": name,
            "appointment_type": kind,
            "date": day,
            "start_time": rng.choice(slots),
            "provider_id": provider,
        }
        svc = service_at(created)
        preview = svc.book(BookingRequest(**request))
        result = svc.book(BookingRequest(**request, confirmation_token=preview.confirmation_token))
        appointment_id = repo.get_by_code(result.confirmation_code).id
        conn.execute(
            "UPDATE appointments SET customer_id = ? WHERE id = ?", (customer, appointment_id)
        )
        return appointment_id

    def count() -> int:
        return conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]

    # 1. Provider 1 is fully booked for the morning on base + 2.
    full_day = base + timedelta(days=2)
    starts = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30"]
    for name, start in zip(CUSTOMERS[: len(starts)], starts, strict=True):
        created = datetime.combine(full_day - timedelta(days=5), time(10))
        svc = service_at(created)
        request = {
            "patient_name": name,
            "appointment_type": "cleaning",
            "date": full_day,
            "start_time": start,
            "provider_id": 1,
        }
        preview = svc.book(BookingRequest(**request))
        result = svc.book(BookingRequest(**request, confirmation_token=preview.confirmation_token))
        appointment_id = repo.get_by_code(result.confirmation_code).id
        conn.execute(
            "UPDATE appointments SET customer_id = ? WHERE id = ?",
            (customer_ids[name], appointment_id),
        )

    # 2. A checkup on base day, then a late cancellation attempt at 08:00: refused and queued.
    notice_name = "Mateo Silva"
    notice_created = datetime.combine(base - timedelta(days=3), time(10))
    request = {
        "patient_name": notice_name,
        "appointment_type": "checkup",
        "date": base,
        "start_time": "10:00",
        "provider_id": 1,
    }
    preview = service_at(notice_created).book(BookingRequest(**request))
    notice = service_at(notice_created).book(
        BookingRequest(**request, confirmation_token=preview.confirmation_token)
    )
    conn.execute(
        "UPDATE appointments SET customer_id = ? WHERE confirmation_code = ?",
        (customer_ids[notice_name], notice.confirmation_code),
    )
    with suppress(ApiError):  # the refusal is expected; the staff request it creates is kept
        service_at(datetime.combine(base, time(8))).cancel(
            CancelRequest(confirmation_code=notice.confirmation_code, patient_name=notice_name)
        )

    # 3. Callers with no customer record, each on the first day that has room.
    for name in NEW_CALLERS:
        for offset in range(1, 15):
            day = base + timedelta(days=offset)
            if day.weekday() == 6:
                continue
            if book_first_free(day, rng.choice([1, 2]), "checkup", name, None):
                break

    # 4. Everything else, until the schedule holds the target number of bookings.
    kinds = ["cleaning"] * 4 + ["checkup"] * 4 + ["consultation"] * 2
    historical: list[int] = []
    attempts = 0
    while count() < TOTAL_BOOKINGS and attempts < 2000:
        attempts += 1
        name = rng.choice(CUSTOMERS)
        day = base + timedelta(days=rng.randint(-10, 14))
        if day.weekday() == 6 or day == closed_day:
            continue
        appointment_id = book_first_free(
            day, rng.choice([1, 2]), rng.choice(kinds), name, customer_ids[name]
        )
        if appointment_id is not None and day < base:
            historical.append(appointment_id)

    # Cancel some historical bookings, two days before each one was due, well inside the rules.
    for appointment_id in historical[:CANCELLED_TARGET]:
        appointment = repo.get_by_id(appointment_id)
        when = datetime.combine(appointment.starts_at.date() - timedelta(days=2), time(10))
        svc = service_at(when)
        cancel = CancelRequest(
            confirmation_code=appointment.confirmation_code, patient_name=appointment.patient_name
        )
        preview = svc.cancel(cancel)
        svc.cancel(cancel.model_copy(update={"confirmation_token": preview.confirmation_token}))

    # 5. Staff requests, one in each state. The late-cancellation request is already queued.
    moment = datetime.combine(base, time(8))
    for reason in ("medical", "human_request", "unsupported"):
        escalate(conn, reason=reason, channel="demo", clock=lambda: moment)
    staff_repo.set_status_for_reason(conn, "human_request", "in_progress", moment)
    staff_repo.set_status_for_reason(conn, "change_too_late", "resolved", moment)

    return {
        "customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "providers": conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0],
        "bookings": count(),
        "cancelled": conn.execute(
            "SELECT COUNT(*) FROM appointments WHERE status = 'cancelled'"
        ).fetchone()[0],
        "closures": conn.execute("SELECT COUNT(*) FROM provider_closures").fetchone()[0],
        "staff_requests": conn.execute("SELECT COUNT(*) FROM staff_requests").fetchone()[0],
    }


def _insert_customers(conn: sqlite3.Connection, base: date) -> dict[str, int]:
    ids: dict[str, int] = {}
    stamp = datetime.combine(base, time(8)).isoformat(timespec="seconds")
    for name in CUSTOMERS:
        cursor = conn.execute(
            "INSERT INTO customers (full_name, created_at) VALUES (?, ?)", (name, stamp)
        )
        ids[name] = int(cursor.lastrowid)
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    counts = seed(args.db)
    print(f"seeded {check_location(args.db)}")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
