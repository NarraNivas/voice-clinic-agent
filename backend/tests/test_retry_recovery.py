"""A confirm whose response never reaches the browser must not lead to a second booking.

The page keeps one idempotency key per set of booking details, so a retry, or choosing the
same slot again, returns the original booking.
"""

import sqlite3

from tests.conftest import next_weekday


def payload(**extra) -> dict:
    data = {
        "patient_name": "Retry Caller",
        "appointment_type": "cleaning",
        "date": next_weekday(1).isoformat(),
        "start_time": "11:00",
        "idempotency_key": "retry-key-0001",
    }
    data.update(extra)
    return data


def test_retrying_a_confirm_with_the_same_token_returns_the_same_booking(client):
    preview = client.post("/api/appointments", json=payload()).json()
    token = preview["confirmation_token"]
    first = client.post("/api/appointments", json=payload(confirmation_token=token)).json()
    assert first["status"] == "booked"

    # The browser never saw `first`. It retries with exactly the same request.
    retry = client.post("/api/appointments", json=payload(confirmation_token=token))
    assert retry.status_code == 200
    assert retry.json()["status"] == "booked"
    assert retry.json()["confirmation_code"] == first["confirmation_code"]


def test_choosing_the_same_slot_again_shows_the_existing_booking(client):
    preview = client.post("/api/appointments", json=payload()).json()
    client.post("/api/appointments", json=payload(confirmation_token=preview["confirmation_token"]))

    # A fresh preview with the same key does not offer a second booking.
    again = client.post("/api/appointments", json=payload())
    assert again.status_code == 200
    assert again.json()["status"] == "booked"
    assert again.json()["confirmation_token"] is None


def test_only_one_row_is_created_across_retries(client, settings):
    preview = client.post("/api/appointments", json=payload()).json()
    token = preview["confirmation_token"]
    for _ in range(3):
        client.post("/api/appointments", json=payload(confirmation_token=token))

    conn = sqlite3.connect(settings.database_path)
    try:
        rows = conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0]
    finally:
        conn.close()
    assert rows == 1


def test_a_cancelled_booking_is_never_replayed_as_a_success(client):
    key = "retry-key-cancel"
    body = payload(idempotency_key=key)
    preview = client.post("/api/appointments", json=body).json()
    booked = client.post(
        "/api/appointments", json={**body, "confirmation_token": preview["confirmation_token"]}
    ).json()
    assert booked["status"] == "booked"

    cancel_preview = client.post(
        "/api/appointments/cancel",
        json={"confirmation_code": booked["confirmation_code"], "patient_name": "Retry Caller"},
    ).json()
    cancelled = client.post(
        "/api/appointments/cancel",
        json={
            "confirmation_code": booked["confirmation_code"],
            "patient_name": "Retry Caller",
            "confirmation_token": cancel_preview["confirmation_token"],
        },
    ).json()
    assert cancelled["status"] == "cancelled"

    # The same request key after cancellation must not come back as "booked".
    replay = client.post("/api/appointments", json=body)
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "idempotency_used"
    assert replay.json().get("status") != "booked"


def test_a_lost_cancel_reply_can_be_recovered_by_reading_the_booking(client):
    preview = client.post("/api/appointments", json=payload()).json()
    booked = client.post(
        "/api/appointments", json=payload(confirmation_token=preview["confirmation_token"])
    ).json()
    code = booked["confirmation_code"]
    cancel_preview = client.post(
        "/api/appointments/cancel",
        json={"confirmation_code": code, "patient_name": "Retry Caller"},
    ).json()
    token = cancel_preview["confirmation_token"]
    # The first confirm succeeds on the server, but the browser never sees the reply.
    client.post(
        "/api/appointments/cancel",
        json={
            "confirmation_code": code,
            "patient_name": "Retry Caller",
            "confirmation_token": token,
        },
    )
    # Recovery reads the booking and sees it cancelled, so nothing is resent.
    found = client.post(
        "/api/appointments/lookup", json={"confirmation_code": code, "patient_name": "Retry Caller"}
    ).json()
    assert found["status"] == "cancelled"
    # Resending the same token is refused, so no second write can happen.
    again = client.post(
        "/api/appointments/cancel",
        json={
            "confirmation_code": code,
            "patient_name": "Retry Caller",
            "confirmation_token": token,
        },
    )
    assert again.status_code == 409


def test_a_lost_reschedule_reply_is_recovered_by_reading_the_booking(client):
    preview = client.post("/api/appointments", json=payload()).json()
    booked = client.post(
        "/api/appointments", json=payload(confirmation_token=preview["confirmation_token"])
    ).json()
    code = booked["confirmation_code"]
    base = {
        "confirmation_code": code,
        "patient_name": "Retry Caller",
        "new_date": next_weekday(2).isoformat(),
        "new_start_time": "14:00",
    }
    move_preview = client.post("/api/appointments/reschedule", json=base).json()
    token = move_preview["confirmation_token"]
    client.post("/api/appointments/reschedule", json={**base, "confirmation_token": token})
    found = client.post(
        "/api/appointments/lookup", json={"confirmation_code": code, "patient_name": "Retry Caller"}
    ).json()
    assert found["starts_at"] == f"{base['new_date']}T14:00"
    again = client.post("/api/appointments/reschedule", json={**base, "confirmation_token": token})
    assert again.status_code == 409
