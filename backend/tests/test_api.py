"""HTTP contract tests. They use dates relative to today, not the fixed test clock."""

from datetime import timedelta

from tests.conftest import next_weekday


def test_health_reports_disabled_tools_when_no_secret(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["tool_endpoints_enabled"] is False
    assert body["elevenlabs_widget_configured"] is False


def test_clinic_info_is_fictional_and_has_types(client):
    body = client.get("/api/clinic").json()
    assert "Fictional" in body["name"]
    assert body["front_desk_phone"].startswith("555-")
    assert set(body["appointment_types"]) == {"cleaning", "checkup", "consultation"}


def test_availability_returns_slots(client):
    day = next_weekday(1).isoformat()  # a Tuesday
    response = client.post("/api/availability", json={"date": day, "appointment_type": "checkup"})
    assert response.status_code == 200
    assert response.json()["slots"]


def test_bad_appointment_type_is_422_without_echoing_input(client):
    response = client.post(
        "/api/availability",
        json={"date": next_weekday(1).isoformat(), "appointment_type": "root canal 555-1234"},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert "555-1234" not in str(response.json())
    assert "Traceback" not in str(response.json())


def test_bad_time_format_is_rejected(client):
    response = client.post(
        "/api/appointments",
        json={
            "patient_name": "Test Patient",
            "appointment_type": "cleaning",
            "date": next_weekday(1).isoformat(),
            "start_time": "25:00",
        },
    )
    assert response.status_code == 422


def test_book_preview_then_confirm_over_http(client):
    day = next_weekday(1)
    payload = {
        "patient_name": "Test Patient",
        "appointment_type": "cleaning",
        "date": day.isoformat(),
        "start_time": "09:00",
    }
    preview = client.post("/api/appointments", json=payload).json()
    assert preview["status"] == "confirmation_required"
    assert preview["confirmation_code"] is None
    assert preview["confirmation_token"]

    booked = client.post(
        "/api/appointments", json={**payload, "confirmation_token": preview["confirmation_token"]}
    ).json()
    assert booked["status"] == "booked"
    code = booked["confirmation_code"]

    lookup = client.post(
        "/api/appointments/lookup", json={"confirmation_code": code, "patient_name": "Test Patient"}
    )
    assert lookup.status_code == 200
    assert lookup.json()["starts_at"] == f"{day.isoformat()}T09:00"


def test_cancel_over_http_and_error_shape_for_unknown_code(client):
    response = client.post(
        "/api/appointments/cancel",
        json={"confirmation_code": "MSD-ABC123", "patient_name": "Nobody"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_a_confirmed_flag_over_http_writes_nothing(client):
    payload = {
        "patient_name": "Test Patient",
        "appointment_type": "cleaning",
        "date": next_weekday(1).isoformat(),
        "start_time": "09:00",
        "confirmed": True,
    }
    body = client.post("/api/appointments", json=payload).json()
    assert body["status"] == "confirmation_required"
    assert body["confirmation_code"] is None


def test_forged_token_over_http_is_409(client):
    payload = {
        "patient_name": "Test Patient",
        "appointment_type": "cleaning",
        "date": next_weekday(1).isoformat(),
        "start_time": "09:00",
        "confirmation_token": "forged-token-0123456789abcdef",
    }
    response = client.post("/api/appointments", json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_confirmation"


def test_past_date_is_rejected_over_http(client):
    yesterday = (next_weekday(1, 0) - timedelta(days=7)).isoformat()
    response = client.post(
        "/api/appointments",
        json={
            "patient_name": "Test Patient",
            "appointment_type": "checkup",
            "date": yesterday,
            "start_time": "09:00",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"time_in_past", "outside_booking_window"}
