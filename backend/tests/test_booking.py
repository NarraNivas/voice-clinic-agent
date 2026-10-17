"""Business-rule tests for the booking service, using a fixed clock and a real SQLite file."""

import re
from datetime import date, timedelta

import pytest
from app.models.schemas import BookingRequest, CancelRequest, ChangeResult, RescheduleRequest
from app.services.booking import AppointmentService
from app.services.errors import ApiError

from tests.conftest import FIXED_NOW

TUESDAY = date(2026, 10, 13)
CODE_PATTERN = re.compile(r"^MSD-[A-Z0-9]{6}$")


def booking(**overrides) -> BookingRequest:
    data = {
        "patient_name": "Test Patient",
        "appointment_type": "cleaning",
        "date": TUESDAY,
        "start_time": "09:00",
    }
    data.update(overrides)
    return BookingRequest(**data)


def book_confirmed(service: AppointmentService, **overrides) -> ChangeResult:
    """The only way to write: preview, then confirm with the token from that preview."""
    preview = service.book(booking(**overrides))
    assert preview.status == "confirmation_required"
    return service.book(booking(confirmation_token=preview.confirmation_token, **overrides))


def cancel_confirmed(
    service: AppointmentService, code: str, name: str = "Test Patient"
) -> ChangeResult:
    base = {"confirmation_code": code, "patient_name": name}
    preview = service.cancel(CancelRequest(**base))
    return service.cancel(CancelRequest(**base, confirmation_token=preview.confirmation_token))


def count_rows(conn, table: str = "appointments") -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def expect_error(code: str, func, *args):
    with pytest.raises(ApiError) as excinfo:
        func(*args)
    assert excinfo.value.code == code
    return excinfo.value


# --- availability ---------------------------------------------------------


def test_availability_lists_open_slots_for_the_day(service):
    result = service.availability(TUESDAY, "cleaning")
    assert result.slots[0] == "09:00"
    assert result.duration_minutes == 30


def test_availability_is_empty_on_sunday(service):
    result = service.availability(date(2026, 10, 18), "checkup")
    assert result.slots == []
    assert "No open slots" in result.message


def test_availability_outside_window_is_empty(service):
    far = FIXED_NOW.date() + timedelta(days=61)
    assert service.availability(far, "cleaning").slots == []


def test_availability_in_the_past_says_so(service):
    past = FIXED_NOW.date() - timedelta(days=1)
    result = service.availability(past, "cleaning")
    assert result.slots == []
    assert "already passed" in result.message


# --- booking: preview and confirmation tokens ----------------------------


def test_preview_returns_a_token_and_writes_no_appointment(service, conn):
    preview = service.book(booking())
    assert preview.status == "confirmation_required"
    assert preview.confirmation_code is None
    assert preview.confirmation_token
    assert len(preview.confirmation_token) >= 20
    assert count_rows(conn) == 0


def test_confirmed_booking_writes_and_returns_code(service, conn):
    result = book_confirmed(service)
    assert result.status == "booked"
    assert CODE_PATTERN.match(result.confirmation_code)
    assert result.appointment.starts_at == "2026-10-13T09:00"
    assert count_rows(conn) == 1


def test_a_confirmed_flag_on_its_own_writes_nothing(service, conn):
    # Unknown fields are ignored by the schema, so a bare "confirmed" flag is just a preview.
    request = BookingRequest(
        patient_name="Test Patient",
        appointment_type="cleaning",
        date=TUESDAY,
        start_time="09:00",
        confirmed=True,
    )
    result = service.book(request)
    assert result.status == "confirmation_required"
    assert count_rows(conn) == 0


def test_forged_token_is_rejected_and_writes_nothing(service, conn):
    expect_error(
        "invalid_confirmation",
        service.book,
        booking(confirmation_token="forged-token-0123456789abcdef"),
    )
    assert count_rows(conn) == 0


def test_token_cannot_be_reused(service, conn):
    preview = service.book(booking())
    booked = service.book(booking(confirmation_token=preview.confirmation_token))
    assert booked.status == "booked"
    # Free the slot so the reuse reaches the token check rather than the slot check.
    cancel_confirmed(service, booked.confirmation_code)
    expect_error(
        "invalid_confirmation",
        service.book,
        booking(confirmation_token=preview.confirmation_token),
    )
    assert count_rows(conn) == 1  # only the original booking row, now cancelled


def test_token_is_bound_to_the_exact_details(service, conn):
    preview = service.book(booking(start_time="10:00"))
    expect_error(
        "invalid_confirmation",
        service.book,
        booking(start_time="11:00", confirmation_token=preview.confirmation_token),
    )
    assert count_rows(conn) == 0


def test_token_expires_after_five_minutes(conn, service):
    preview = service.book(booking())
    later = AppointmentService(service.repo, clock=lambda: FIXED_NOW + timedelta(minutes=6))
    expect_error(
        "confirmation_expired",
        later.book,
        booking(confirmation_token=preview.confirmation_token),
    )
    assert count_rows(conn) == 0


# --- booking rules -------------------------------------------------------


def test_overlapping_booking_is_rejected(service):
    book_confirmed(service)
    expect_error("slot_unavailable", service.book, booking(patient_name="Someone Else"))


def test_consultation_overlapping_a_cleaning_is_rejected(service):
    book_confirmed(service, start_time="09:30")
    expect_error(
        "slot_unavailable",
        service.book,
        booking(appointment_type="consultation", start_time="09:00"),
    )


def test_sunday_is_closed(service):
    expect_error("clinic_closed", service.book, booking(date=date(2026, 10, 18)))


def test_consultation_cannot_run_past_saturday_closing(service):
    expect_error(
        "clinic_closed",
        service.book,
        booking(date=date(2026, 10, 17), start_time="12:30", appointment_type="consultation"),
    )


def test_start_time_must_be_on_the_grid(service):
    expect_error("invalid_time", service.book, booking(start_time="09:15"))


def test_past_time_is_rejected(service):
    expect_error("time_in_past", service.book, booking(date=FIXED_NOW.date(), start_time="07:00"))


def test_outside_booking_window_is_rejected(service):
    far = FIXED_NOW.date() + timedelta(days=61)
    expect_error("outside_booking_window", service.book, booking(date=far))


def test_idempotent_replay_returns_same_appointment_without_a_new_token(service, conn):
    key = "req-abc-12345"
    first = book_confirmed(service, idempotency_key=key)
    # A retry with the same key and details returns the original booking. It writes nothing.
    second = service.book(booking(idempotency_key=key))
    assert second.status == "booked"
    assert second.confirmation_code == first.confirmation_code
    assert count_rows(conn) == 1


def test_idempotency_key_reused_for_different_booking_is_a_conflict(service):
    key = "req-abc-12345"
    book_confirmed(service, idempotency_key=key)
    expect_error(
        "idempotency_conflict",
        service.book,
        booking(start_time="10:00", idempotency_key=key),
    )


# --- lookup, reschedule, cancel -----------------------------------------


def test_name_must_match_to_see_or_change_a_booking(service):
    code = book_confirmed(service).confirmation_code
    expect_error("not_found", service.lookup, code, "Wrong Name")
    expect_error(
        "not_found",
        service.cancel,
        CancelRequest(confirmation_code=code, patient_name="Wrong Name"),
    )


def test_unknown_code_gives_same_error_as_name_mismatch(service):
    expect_error("not_found", service.lookup, "MSD-ZZZZZZ", "Test Patient")


def test_name_match_ignores_case_and_extra_spaces(service):
    code = book_confirmed(service).confirmation_code
    assert service.lookup(code, "  test   PATIENT ").confirmation_code == code


def test_reschedule_preview_then_confirm(service):
    code = book_confirmed(service).confirmation_code
    base = {
        "confirmation_code": code,
        "patient_name": "Test Patient",
        "new_date": TUESDAY,
        "new_start_time": "14:00",
    }
    preview = service.reschedule(RescheduleRequest(**base))
    assert preview.status == "confirmation_required"
    assert service.lookup(code, "Test Patient").starts_at == "2026-10-13T09:00"

    done = service.reschedule(
        RescheduleRequest(**base, confirmation_token=preview.confirmation_token)
    )
    assert done.status == "rescheduled"
    assert service.lookup(code, "Test Patient").starts_at == "2026-10-13T14:00"


def test_reschedule_token_cannot_be_used_for_a_different_time(service):
    code = book_confirmed(service).confirmation_code
    base = {"confirmation_code": code, "patient_name": "Test Patient", "new_date": TUESDAY}
    preview = service.reschedule(RescheduleRequest(**base, new_start_time="14:00"))
    expect_error(
        "invalid_confirmation",
        service.reschedule,
        RescheduleRequest(
            **base,
            new_start_time="15:00",
            confirmation_token=preview.confirmation_token,
        ),
    )
    assert service.lookup(code, "Test Patient").starts_at == "2026-10-13T09:00"


def test_reschedule_into_a_taken_slot_is_rejected_before_any_token_check(service):
    code = book_confirmed(service).confirmation_code
    book_confirmed(service, patient_name="Other Person", start_time="14:00")
    expect_error(
        "slot_unavailable",
        service.reschedule,
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Test Patient",
            new_date=TUESDAY,
            new_start_time="14:00",
        ),
    )


def test_cancel_then_cancel_again_is_an_error(service):
    code = book_confirmed(service).confirmation_code
    assert cancel_confirmed(service, code).status == "cancelled"
    expect_error(
        "already_cancelled",
        service.cancel,
        CancelRequest(confirmation_code=code, patient_name="Test Patient"),
    )


def test_cancelled_slot_becomes_available_again(service):
    code = book_confirmed(service).confirmation_code
    cancel_confirmed(service, code)
    assert "09:00" in service.availability(TUESDAY, "cleaning").slots


def test_change_inside_24_hour_notice_escalates(service, conn):
    soon = FIXED_NOW + timedelta(hours=2)
    code = book_confirmed(service, date=soon.date(), start_time="10:00").confirmation_code
    error = expect_error(
        "change_too_late",
        service.cancel,
        CancelRequest(confirmation_code=code, patient_name="Test Patient"),
    )
    assert "cannot be made here" in error.message
    assert "No staff member is notified" in error.message
    assert conn.execute("SELECT reason FROM escalations").fetchone()["reason"] == "change_too_late"


# --- logs ---------------------------------------------------------------


def test_every_action_is_logged(service, conn):
    service.availability(TUESDAY, "cleaning")
    book_confirmed(service)
    tools = [row["tool_name"] for row in conn.execute("SELECT tool_name FROM interactions")]
    assert tools == ["check_availability", "book_appointment", "book_appointment"]


def test_logs_never_contain_patient_names_or_confirmation_codes(service, conn):
    code = book_confirmed(service, patient_name="Zelda Quillfeather").confirmation_code
    service.lookup(code, "Zelda Quillfeather")
    cancel_confirmed(service, code, name="Zelda Quillfeather")
    summaries = " ".join(row["summary"] for row in conn.execute("SELECT summary FROM interactions"))
    assert "Zelda" not in summaries
    assert code not in summaries
    assert "appointment #" in summaries
