"""Provider-specific availability, closures, and the optional provider field on the tools."""

import dataclasses
from datetime import timedelta

import pytest
from app.main import create_app
from app.models.schemas import BookingRequest
from app.services.errors import ApiError
from fastapi.testclient import TestClient

from tests.conftest import FIXED_NOW, next_weekday

TUESDAY = FIXED_NOW.date() + timedelta(days=1)
SECRET = "test-secret-value-1234567890"


def booking(**extra):
    data = {
        "patient_name": "Provider Test",
        "appointment_type": "checkup",
        "date": TUESDAY,
        "start_time": "10:00",
    }
    data.update(extra)
    return BookingRequest(**data)


def test_availability_without_a_provider_offers_any_free_provider(service):
    preview = service.book(booking(provider_id=1))
    service.book(booking(provider_id=1, confirmation_token=preview.confirmation_token))
    slots = service.availability(TUESDAY, "checkup").slots
    assert "10:00" in slots  # provider 2 is still free at 10:00


def test_availability_for_one_provider_hides_the_other_providers_bookings(service):
    preview = service.book(booking(provider_id=1))
    service.book(booking(provider_id=1, confirmation_token=preview.confirmation_token))
    assert "10:00" not in service.availability(TUESDAY, "checkup", provider_id=1).slots
    assert "10:00" in service.availability(TUESDAY, "checkup", provider_id=2).slots


def test_an_unknown_provider_is_rejected(service):
    with pytest.raises(ApiError) as excinfo:
        service.availability(TUESDAY, "checkup", provider_id=99)
    assert excinfo.value.code == "unknown_provider"


def test_a_closed_provider_offers_nothing_that_day(service, conn):
    conn.execute(
        "INSERT INTO provider_closures (provider_id, day, reason) VALUES (2, ?, 'Test')",
        (TUESDAY.isoformat(),),
    )
    assert service.availability(TUESDAY, "checkup", provider_id=2).slots == []
    assert service.availability(TUESDAY, "checkup", provider_id=1).slots


def test_booking_without_a_provider_picks_a_free_one(service):
    first = service.book(booking())
    booked = service.book(booking(confirmation_token=first.confirmation_token))
    assert booked.status == "booked"
    second = service.book(booking(patient_name="Second Person"))
    assert second.status == "confirmation_required"  # provider 2 takes the same time


def test_a_retry_keeps_the_provider_its_preview_chose(service, conn):
    preview = service.book(booking(provider_id=2))
    # Provider 2 is now taken by someone else. The retry must still answer for provider 2's booking,
    # not quietly move it to provider 1.
    booked = service.book(booking(confirmation_token=preview.confirmation_token))
    provider = conn.execute(
        "SELECT provider_id FROM appointments WHERE confirmation_code = ?",
        (booked.confirmation_code,),
    ).fetchone()[0]
    assert provider == 2
    again = service.book(booking(confirmation_token=preview.confirmation_token))
    assert again.confirmation_code == booked.confirmation_code


def test_older_tool_payloads_without_a_provider_still_work(settings):
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    headers = {"X-Tool-Secret": SECRET}
    body = {
        "patient_name": "Old Client",
        "appointment_type": "cleaning",
        "date": next_weekday(1).isoformat(),
        "start_time": "09:00",
    }
    with TestClient(create_app(configured)) as client:
        preview = client.post("/tools/book-appointment", json=body, headers=headers).json()
        assert preview["status"] == "confirmation_required"
        assert (
            client.post(
                "/tools/check-availability",
                json={"date": body["date"], "appointment_type": "cleaning"},
                headers=headers,
            ).status_code
            == 200
        )


def test_the_tool_schema_keeps_provider_optional(settings):
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    spec = create_app(configured).openapi()
    for name in ("VoiceBookingRequest", "AvailabilityRequest"):
        assert "provider_id" not in spec["components"]["schemas"][name].get("required", [])
