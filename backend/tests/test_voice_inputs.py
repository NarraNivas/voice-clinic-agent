"""Inputs as a voice agent actually sends them: times in several spoken-style forms, and
idempotency keys it should not be sending at all."""

import dataclasses

import pytest
from app.main import create_app
from app.models.normalize import normalize_time
from fastapi.testclient import TestClient

from tests.conftest import next_weekday

SECRET = "test-secret-value-1234567890"
HEADERS = {"X-Tool-Secret": SECRET}


@pytest.fixture
def tools_client(settings) -> TestClient:
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    with TestClient(create_app(configured)) as test_client:
        yield test_client


def payload(start_time: str, **extra) -> dict:
    data = {
        "patient_name": "Voice Caller",
        "appointment_type": "checkup",
        "date": next_weekday(1).isoformat(),
        "start_time": start_time,
    }
    data.update(extra)
    return data


@pytest.mark.parametrize(
    ("spoken_form", "normalized"),
    [
        ("12:30", "12:30"),
        ("12:30 PM", "12:30"),
        ("12:30pm", "12:30"),
        ("12:30 p.m.", "12:30"),
        ("1:30 PM", "13:30"),
        ("2:30 pm", "14:30"),
        ("12:30:00", "12:30"),
        ("9:00 AM", "09:00"),
        ("13:00", "13:00"),
    ],
)
def test_common_time_forms_are_accepted(client, spoken_form, normalized):
    response = client.post("/api/appointments", json=payload(spoken_form))
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "confirmation_required"
    # The preview summary shows the normalised time, so the caller hears what will be booked.
    summary = response.json()["summary"]
    hour = int(normalized[:2])
    expected_clock = f"{(hour % 12) or 12:02d}:{normalized[3:]} {'PM' if hour >= 12 else 'AM'}"
    assert expected_clock in summary


@pytest.mark.parametrize("bad", ["25:00", "lunchtime", "130"])
def test_nonsense_times_are_still_rejected(client, bad):
    response = client.post("/api/appointments", json=payload(bad))
    assert response.status_code == 422
    assert "start_time" in response.json()["error"]["message"]


def test_tools_ignore_a_short_idempotency_key_from_the_agent(tools_client):
    response = tools_client.post(
        "/tools/book-appointment",
        json=payload("14:30", idempotency_key="req1"),
        headers=HEADERS,
    )
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "confirmation_required"


def test_demo_api_still_validates_idempotency_keys(client):
    response = client.post("/api/appointments", json=payload("14:30", idempotency_key="req1"))
    assert response.status_code == 422


@pytest.mark.parametrize(
    "spoken_type", ["Consultation", " CHECKUP ", "check-up", "Check Up", "teeth cleaning"]
)
def test_common_appointment_type_forms_are_accepted(client, spoken_type):
    body = payload("10:00")
    body["appointment_type"] = spoken_type
    response = client.post("/api/appointments", json=body)
    assert response.status_code == 200, response.json()


def test_unknown_appointment_type_is_still_rejected(client):
    body = payload("10:00")
    body["appointment_type"] = "root canal"
    response = client.post("/api/appointments", json=body)
    assert response.status_code == 422
    assert "appointment_type" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("spoken_time", "normalized"),
    [
        ("3:30", "15:30"),
        ("three thirty", "15:30"),
        ("three thirty pm", "15:30"),
        ("3:30 pm", "15:30"),
        ("9", "09:00"),
        ("12:30", "12:30"),
    ],
)
def test_spoken_time_forms_are_normalised(spoken_time, normalized):
    assert normalize_time(spoken_time) == normalized


@pytest.mark.parametrize(
    "spoken_date",
    ["October 23rd", "23 October", "oct 23", "10/23", "October 23, 2026"],
)
def test_spoken_dates_are_accepted(client, spoken_date):
    body = payload("15:30")
    body["date"] = spoken_date
    response = client.post("/api/appointments", json=body)
    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "confirmation_required"


def test_unparseable_date_is_still_rejected(client):
    body = payload("15:30")
    body["date"] = "next tuesday-ish"
    response = client.post("/api/appointments", json=body)
    assert response.status_code == 422
    assert "date" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("spoken_time", "normalized"),
    [
        ("3:30 PM", "15:30"),
        ("3:30PM", "15:30"),
        ("15:30 PM", "15:30"),
        ("3:30 in the afternoon", "15:30"),
        ("3.30", "15:30"),
        ("3 30", "15:30"),
        ("half past three", "15:30"),
        ("three-thirty", "15:30"),
        ("quarter to four", "15:45"),
        ("1530", "15:30"),
        ("3:30 PM EST", "15:30"),
        ("12 noon", "12:00"),
        ("9 am", "09:00"),
    ],
)
def test_wide_range_of_spoken_times(spoken_time, normalized):
    assert normalize_time(spoken_time) == normalized
