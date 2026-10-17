"""Stale previews are refused. Lost replies get the recorded outcome, never a second write.

These run through the service with a fixed clock and a disposable database, and also through the
HTTP routes, including the voice-tool route.
"""

import dataclasses
import sqlite3
from datetime import timedelta

import pytest
from app.main import create_app
from app.models.schemas import BookingRequest, CancelRequest, RescheduleRequest
from app.services.errors import ApiError
from fastapi.testclient import TestClient

from tests.conftest import FIXED_NOW, next_weekday

TUESDAY = FIXED_NOW.date() + timedelta(days=1)
SECRET = "test-secret-value-1234567890"


def booking(**overrides) -> BookingRequest:
    data = {
        "patient_name": "Revision Caller",
        "appointment_type": "cleaning",
        "date": TUESDAY,
        "start_time": "10:00",
    }
    data.update(overrides)
    return BookingRequest(**data)


def book(service, **overrides):
    preview = service.book(booking(**overrides))
    return service.book(booking(confirmation_token=preview.confirmation_token, **overrides))


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def expect(code: str, func, *args):
    with pytest.raises(ApiError) as excinfo:
        func(*args)
    assert excinfo.value.code == code, excinfo.value.message
    return excinfo.value


# --- A3: a preview is bound to the revision the caller reviewed -------------------------


def test_cancel_preview_taken_before_a_reschedule_cannot_cancel_the_new_booking(service):
    code = book(service).confirmation_code
    stale_cancel = service.cancel(
        CancelRequest(confirmation_code=code, patient_name="Revision Caller")
    )
    move = service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="14:00",
        )
    )
    service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="14:00",
            confirmation_token=move.confirmation_token,
        )
    )
    expect(
        "invalid_confirmation",
        service.cancel,
        CancelRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            confirmation_token=stale_cancel.confirmation_token,
        ),
    )
    assert service.lookup(code, "Revision Caller").status == "booked"


def test_reschedule_preview_taken_before_another_reschedule_is_refused(service):
    code = book(service).confirmation_code
    first_move = service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="11:00",
        )
    )
    other = service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="12:00",
        )
    )
    service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="12:00",
            confirmation_token=other.confirmation_token,
        )
    )
    expect(
        "invalid_confirmation",
        service.reschedule,
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="11:00",
            confirmation_token=first_move.confirmation_token,
        ),
    )
    assert service.lookup(code, "Revision Caller").starts_at == f"{TUESDAY.isoformat()}T12:00"


def test_revision_increments_on_every_change(service, conn):
    code = book(service).confirmation_code
    before = conn.execute("SELECT revision FROM appointments").fetchone()["revision"]
    preview = service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="15:00",
        )
    )
    service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="15:00",
            confirmation_token=preview.confirmation_token,
        )
    )
    after = conn.execute("SELECT revision FROM appointments").fetchone()["revision"]
    assert after == before + 1


# --- A4: a lost confirm reply is answered with the recorded outcome ---------------------


def test_retrying_a_confirmed_booking_returns_the_same_outcome_without_writing(service, conn):
    preview = service.book(booking())
    first = service.book(booking(confirmation_token=preview.confirmation_token))
    second = service.book(booking(confirmation_token=preview.confirmation_token))
    assert second.status == "booked"
    assert second.confirmation_code == first.confirmation_code
    assert count(conn, "appointments") == 1


def test_retrying_a_confirmed_cancel_returns_cancelled_without_writing(service, conn):
    code = book(service).confirmation_code
    preview = service.cancel(CancelRequest(confirmation_code=code, patient_name="Revision Caller"))
    request = CancelRequest(
        confirmation_code=code,
        patient_name="Revision Caller",
        confirmation_token=preview.confirmation_token,
    )
    first = service.cancel(request)
    revision_after_first = conn.execute("SELECT revision FROM appointments").fetchone()["revision"]
    second = service.cancel(request)
    assert second.status == first.status == "cancelled"
    assert (
        conn.execute("SELECT revision FROM appointments").fetchone()["revision"]
        == revision_after_first
    )


def test_a_retry_is_superseded_once_the_booking_has_changed(service):
    code = book(service).confirmation_code
    preview = service.reschedule(
        RescheduleRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            new_date=TUESDAY,
            new_start_time="13:00",
        )
    )
    request = RescheduleRequest(
        confirmation_code=code,
        patient_name="Revision Caller",
        new_date=TUESDAY,
        new_start_time="13:00",
        confirmation_token=preview.confirmation_token,
    )
    service.reschedule(request)
    cancel_preview = service.cancel(
        CancelRequest(confirmation_code=code, patient_name="Revision Caller")
    )
    service.cancel(
        CancelRequest(
            confirmation_code=code,
            patient_name="Revision Caller",
            confirmation_token=cancel_preview.confirmation_token,
        )
    )
    # The booking is cancelled now. The old "rescheduled" outcome must not be replayed.
    expect("outcome_superseded", service.reschedule, request)


def test_a_retry_never_creates_a_second_booking_through_the_voice_route(settings):
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    headers = {"X-Tool-Secret": SECRET}
    body = {
        "patient_name": "Voice Retry",
        "appointment_type": "checkup",
        "date": next_weekday(1).isoformat(),
        "start_time": "09:30",
    }
    with TestClient(create_app(configured)) as client:
        preview = client.post("/tools/book-appointment", json=body, headers=headers).json()
        token = preview["confirmation_token"]
        first = client.post(
            "/tools/book-appointment", json={**body, "confirmation_token": token}, headers=headers
        ).json()
        # The agent never saw the first reply, so it sends the same token again.
        retry = client.post(
            "/tools/book-appointment", json={**body, "confirmation_token": token}, headers=headers
        )
    assert retry.status_code == 200
    assert retry.json()["confirmation_code"] == first["confirmation_code"]
    conn = sqlite3.connect(settings.database_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 1
    finally:
        conn.close()


def test_an_unconfirmed_token_still_cannot_be_used_for_a_different_booking(service):
    preview = service.book(booking())
    expect(
        "invalid_confirmation",
        service.book,
        booking(start_time="11:00", confirmation_token=preview.confirmation_token),
    )


def test_replay_still_answers_after_the_clock_moves_on(service):
    preview = service.book(booking())
    service.book(booking(confirmation_token=preview.confirmation_token))
    later = type(service)(service.repo, clock=lambda: FIXED_NOW + timedelta(hours=3))
    # The token expired for first use, but its recorded outcome can still be read back.
    assert later.book(booking(confirmation_token=preview.confirmation_token)).status == "booked"
