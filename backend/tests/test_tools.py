"""ElevenLabs tool routes: secret validation, disabled state, the preview-then-token rule,
and the tools-only app that is safe to expose through a tunnel."""

import dataclasses

import pytest
from app.main import create_app, create_tools_app
from fastapi.testclient import TestClient

from tests.conftest import next_weekday

SECRET = "test-secret-value-1234567890"


@pytest.fixture
def secured_client(settings) -> TestClient:
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    with TestClient(create_app(configured)) as test_client:
        yield test_client


@pytest.fixture
def tools_only_client(settings) -> TestClient:
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    with TestClient(create_tools_app(configured)) as test_client:
        yield test_client


def booking_payload(**overrides) -> dict:
    data = {
        "patient_name": "Voice Caller",
        "appointment_type": "cleaning",
        "date": next_weekday(1).isoformat(),
        "start_time": "10:00",
    }
    data.update(overrides)
    return data


HEADERS = {"X-Tool-Secret": SECRET}


def test_tools_are_disabled_when_no_secret_is_configured(client):
    response = client.post("/tools/answer-faq", json={"question": "hours"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tools_disabled"


def test_missing_secret_header_is_rejected(secured_client):
    response = secured_client.post("/tools/answer-faq", json={"question": "hours"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_wrong_secret_is_rejected(secured_client):
    response = secured_client.post(
        "/tools/answer-faq",
        json={"question": "hours"},
        headers={"X-Tool-Secret": "not-the-secret"},
    )
    assert response.status_code == 401


def test_correct_secret_reaches_the_tool(secured_client):
    response = secured_client.post(
        "/tools/answer-faq",
        json={"question": "What are your hours?"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["topic"] == "hours"


def test_secret_is_checked_before_any_booking_happens(secured_client):
    response = secured_client.post("/tools/book-appointment", json=booking_payload())
    assert response.status_code == 401


def test_booking_through_tools_needs_the_preview_token(secured_client):
    preview = secured_client.post(
        "/tools/book-appointment", json=booking_payload(), headers=HEADERS
    ).json()
    assert preview["status"] == "confirmation_required"
    assert preview["confirmation_code"] is None
    assert preview["confirmation_token"]

    booked = secured_client.post(
        "/tools/book-appointment",
        json=booking_payload(confirmation_token=preview["confirmation_token"]),
        headers=HEADERS,
    ).json()
    assert booked["status"] == "booked"
    assert booked["confirmation_code"].startswith("MSD-")


def test_a_confirmed_flag_alone_books_nothing_through_tools(secured_client):
    body = secured_client.post(
        "/tools/book-appointment", json={**booking_payload(), "confirmed": True}, headers=HEADERS
    ).json()
    assert body["status"] == "confirmation_required"
    assert body["confirmation_code"] is None


def test_forged_token_through_tools_is_rejected(secured_client):
    response = secured_client.post(
        "/tools/book-appointment",
        json=booking_payload(confirmation_token="forged-token-0123456789abcdef"),
        headers=HEADERS,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_confirmation"


def test_tool_escalation_returns_front_desk_number(secured_client):
    body = secured_client.post(
        "/tools/escalate-to-human",
        json={"reason": "medical"},
        headers=HEADERS,
    ).json()
    assert body["front_desk_phone"] == "555-0100"
    assert "can't give medical advice" in body["message"]


def test_escalation_rejects_free_text_reasons(secured_client):
    response = secured_client.post(
        "/tools/escalate-to-human", json={"reason": "my tooth hurts badly"}, headers=HEADERS
    )
    assert response.status_code == 422


def test_tool_actions_are_logged_under_elevenlabs_channel(secured_client):
    secured_client.post(
        "/tools/check-availability",
        json={"date": next_weekday(1).isoformat(), "appointment_type": "checkup"},
        headers=HEADERS,
    )
    items = secured_client.get("/api/interactions").json()["items"]
    assert any(item["channel"] == "elevenlabs" for item in items)


# --- tools-only app (the one to tunnel) ----------------------------------


def test_tools_only_app_serves_tools(tools_only_client):
    response = tools_only_client.post(
        "/tools/answer-faq", json={"question": "hours"}, headers=HEADERS
    )
    assert response.status_code == 200


def test_tools_only_app_has_no_demo_api(tools_only_client):
    # The demo API is unauthenticated and includes the activity log. It must not be reachable.
    assert tools_only_client.get("/api/interactions").status_code == 404
    assert tools_only_client.get("/api/health").status_code == 404
    assert tools_only_client.post("/api/appointments", json=booking_payload()).status_code == 404


def test_tools_only_app_serves_no_pages(tools_only_client):
    assert tools_only_client.get("/").status_code == 404
    assert tools_only_client.get("/app.js").status_code == 404
