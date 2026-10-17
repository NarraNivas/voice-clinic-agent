from datetime import date, datetime

from app.services import clinic_rules as rules

MONDAY = date(2026, 10, 12)
SATURDAY = date(2026, 10, 17)
SUNDAY = date(2026, 10, 18)
EARLY_MONDAY = datetime(2026, 10, 12, 8, 0)


def test_weekday_has_sixteen_half_hour_slots_from_nine_to_five():
    slots = rules.open_slots(MONDAY, 30, [], EARLY_MONDAY)
    assert slots[0] == "09:00"
    assert slots[-1] == "16:30"
    assert len(slots) == 16


def test_saturday_closes_at_one_so_last_start_is_twelve_thirty():
    slots = rules.open_slots(SATURDAY, 30, [], EARLY_MONDAY)
    assert slots[-1] == "12:30"


def test_sunday_has_no_slots():
    assert rules.open_slots(SUNDAY, 30, [], EARLY_MONDAY) == []


def test_sixty_minute_consultation_cannot_start_after_four():
    slots = rules.open_slots(MONDAY, 60, [], EARLY_MONDAY)
    assert slots[-1] == "16:00"


def test_booking_removes_only_overlapping_starts():
    booked = [(datetime(2026, 10, 12, 10, 0), datetime(2026, 10, 12, 11, 0))]
    slots = rules.open_slots(MONDAY, 30, booked, EARLY_MONDAY)
    assert "10:00" not in slots
    assert "10:30" not in slots
    assert "11:00" in slots
    assert "09:30" in slots


def test_past_times_are_excluded_on_today():
    slots = rules.open_slots(MONDAY, 30, [], datetime(2026, 10, 12, 12, 10))
    assert slots[0] == "12:30"


def test_describe_is_readable():
    text = rules.describe(datetime(2026, 10, 13, 9, 30))
    assert text == "Tuesday, October 13, 2026 at 09:30 AM"
