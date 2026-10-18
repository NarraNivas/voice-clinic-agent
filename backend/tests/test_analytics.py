"""The analytics endpoint returns aggregates only, and its filters narrow the numbers."""

from tests.conftest import next_weekday

PATIENT = "Priya Analytics-Test"


def book(client, *, appointment_type="cleaning", start_time="10:00", day=1):
    """Two steps, as the API requires: a preview that returns a token, then the confirmed write."""
    details = {
        "patient_name": PATIENT,
        "appointment_type": appointment_type,
        "date": next_weekday(day).isoformat(),
        "start_time": start_time,
    }
    preview = client.post("/api/appointments", json=details)
    assert preview.json()["status"] == "confirmation_required", preview.text
    token = preview.json()["confirmation_token"]
    confirmed = client.post("/api/appointments", json={**details, "confirmation_token": token})
    assert confirmed.status_code == 200, confirmed.text


def test_empty_database_gives_zero_totals(client):
    body = client.get("/api/analytics").json()
    assert body["totals"]["appointments"] == 0
    assert body["totals"]["cancel_rate"] == 0.0
    assert body["by_day"] == []
    assert len(body["by_provider"]) == 2


def test_response_contains_no_patient_names(client):
    book(client)
    text = client.get("/api/analytics").text
    assert PATIENT not in text
    assert "patient_name" not in text


def test_totals_count_booked_appointments_and_minutes(client):
    book(client, start_time="10:00")
    book(client, start_time="11:00", appointment_type="checkup")
    body = client.get("/api/analytics").json()
    assert body["totals"]["booked"] == 2
    assert body["totals"]["booked_minutes"] > 0
    assert {row["name"] for row in body["by_type"]} == {"cleaning", "checkup"}


def test_type_filter_narrows_the_totals(client):
    book(client, appointment_type="cleaning")
    book(client, start_time="11:00", appointment_type="checkup")
    body = client.get("/api/analytics", params={"appointment_type": "checkup"}).json()
    assert body["totals"]["booked"] == 1
    assert [row["name"] for row in body["by_type"]] == ["checkup"]


def test_date_range_filter_excludes_other_days(client):
    book(client, day=1)
    far_day = next_weekday(1, min_days_ahead=60).isoformat()
    body = client.get("/api/analytics", params={"date_from": far_day}).json()
    assert body["totals"]["appointments"] == 0


def test_unknown_appointment_type_is_rejected(client):
    response = client.get("/api/analytics", params={"appointment_type": "surgery"})
    assert response.status_code == 422


def test_malformed_date_is_rejected(client):
    response = client.get("/api/analytics", params={"date_from": "19/10/2026"})
    assert response.status_code == 422
