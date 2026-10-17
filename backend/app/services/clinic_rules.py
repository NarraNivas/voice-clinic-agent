"""Fictional clinic constants and the pure slot calculator.

Everything here is invented: the clinic, its hours, and the 555-01xx phone range,
which is reserved for fictional use. Times are clinic-local. `clinic_now` applies the clinic's
timezone once, and the rest of the code works with naive clinic-local datetimes.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import DEFAULT_TIMEZONE

CLINIC_NAME = "Maple Street Dental (Fictional Demo)"
CLINIC_ADDRESS = "100 Example Lane, Demo City (fictional)"
FRONT_DESK_PHONE = "555-0100"

SLOT_MINUTES = 30
BOOKING_WINDOW_DAYS = 60
CHANGE_NOTICE_HOURS = 24

APPOINTMENT_DURATIONS: dict[str, int] = {
    "cleaning": 30,
    "checkup": 30,
    "consultation": 60,
}

# Keys follow date.weekday(): Monday=0 ... Sunday=6. None means closed.
OPENING_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(9, 0), time(17, 0)),
    1: (time(9, 0), time(17, 0)),
    2: (time(9, 0), time(17, 0)),
    3: (time(9, 0), time(17, 0)),
    4: (time(9, 0), time(17, 0)),
    5: (time(9, 0), time(13, 0)),
    6: None,
}


def hours_for(day: date) -> tuple[time, time] | None:
    return OPENING_HOURS[day.weekday()]


def open_slots(
    day: date,
    duration_minutes: int,
    booked: list[tuple[datetime, datetime]],
    now: datetime,
) -> list[str]:
    """HH:MM start times inside opening hours, free of bookings, and in the future."""
    hours = hours_for(day)
    if hours is None:
        return []
    open_time, close_time = hours
    close_at = datetime.combine(day, close_time)
    duration = timedelta(minutes=duration_minutes)

    slots: list[str] = []
    cursor = datetime.combine(day, open_time)
    while cursor + duration <= close_at:
        if cursor > now and not overlaps(cursor, cursor + duration, booked):
            slots.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=SLOT_MINUTES)
    return slots


def overlaps(start: datetime, end: datetime, booked: list[tuple[datetime, datetime]]) -> bool:
    return any(start < booked_end and booked_start < end for booked_start, booked_end in booked)


def describe(moment: datetime) -> str:
    """Human-readable date and time for summaries, e.g. 'Tuesday, October 20, 2026 at 09:30 AM'."""
    return f"{moment:%A, %B} {moment.day}, {moment:%Y} at {moment:%I:%M %p}"


def clinic_now(timezone: str = DEFAULT_TIMEZONE) -> datetime:
    """The current wall-clock time in the clinic's timezone, as a naive minute-precision value.

    The rest of the code compares naive clinic-local datetimes, so this is the one place where
    the timezone is applied.
    """
    return datetime.now(ZoneInfo(timezone)).replace(second=0, microsecond=0, tzinfo=None)
