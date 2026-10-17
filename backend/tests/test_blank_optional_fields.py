"""Regression: voice agents send "" for optional fields they are not using.

A blank confirmation_token or idempotency_key must behave as if it were absent. Before this fix,
an empty token failed validation with 422 and the first booking attempt never produced a preview.
"""

import dataclasses

import pytest
from app.main import create_app
from fastapi.testclient import TestClient

from tests.conftest import next_weekday

SECRET = "test-secret-value-1234567890"
HEADERS = {"X-Tool-Secret": SECRET}


def booking_payload(**overrides) -> dict:
    data = {
        "patient_name": "Voice Caller",
        "appointment_type": "consultation",
        "date": next_weekday(1).isoformat(),
        "start_time": "15:30",
    }
    data.update(overrides)
    return data


@pytest.fixture
def tools_client(settings) -> TestClient:
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    with TestClient(create_app(configured)) as test_client:
        yield test_client


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_token_on_first_call_returns_a_preview(client, blank):
    response = client.post("/api/appointments", json=booking_payload(confirmation_token=blank))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmation_required"
    assert body["confirmation_token"]


def test_blank_token_through_tools_returns_a_preview(tools_client):
    response = tools_client.post(
        "/tools/book-appointment",
        json=booking_payload(confirmation_token=""),
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"


def test_blank_idempotency_key_is_ignored(client):
    response = client.post("/api/appointments", json=booking_payload(idempotency_key=""))
    assert response.status_code == 200
    assert response.json()["status"] == "confirmation_required"


def test_blank_token_on_reschedule_and_cancel_returns_a_preview(client):
    booked = client.post("/api/appointments", json=booking_payload()).json()
    token = booked["confirmation_token"]
    confirmed = client.post(
        "/api/appointments",
        json=booking_payload(confirmation_token=token),
    ).json()
    code = confirmed["confirmation_code"]

    cancel = client.post(
        "/api/appointments/cancel",
        json={"confirmation_code": code, "patient_name": "Voice Caller", "confirmation_token": ""},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "confirmation_required"

    reschedule = client.post(
        "/api/appointments/reschedule",
        json={
            "confirmation_code": code,
            "patient_name": "Voice Caller",
            "new_date": next_weekday(2).isoformat(),
            "new_start_time": "10:00",
            "confirmation_token": "",
        },
    )
    assert reschedule.status_code == 200
    assert reschedule.json()["status"] == "confirmation_required"


def test_a_short_non_blank_token_is_still_rejected(client):
    response = client.post(
        "/api/appointments",
        json=booking_payload(confirmation_token="too-short"),
    )
    assert response.status_code == 422
