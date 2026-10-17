"""Regression tests: time text that used to be guessed at, and canonical times that stay put."""

import dataclasses

import pytest
from app.main import create_app
from app.models.normalize import normalize_time
from fastapi.testclient import TestClient

from tests.conftest import next_weekday

SECRET = "test-secret-value-1234567890"


@pytest.fixture
def tools_client(settings) -> TestClient:
    configured = dataclasses.replace(settings, tool_shared_secret=SECRET)
    with TestClient(create_app(configured)) as test_client:
        yield test_client


def payload(start_time: str) -> dict:
    return {
        "patient_name": "Time Caller",
        "appointment_type": "checkup",
        "date": next_weekday(1).isoformat(),
        "start_time": start_time,
    }


def test_canonical_0330_stays_0330():
    assert normalize_time("03:30") == "03:30"


def test_canonical_0330_is_not_read_as_afternoon(client):
    # 03:30 is a real 24-hour time. The clinic is closed then, so the right answer is closed.
    response = client.post("/api/appointments", json=payload("03:30"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "clinic_closed"


def test_correction_is_not_silently_applied():
    text = "not 3:30, make it 4:00 PM"
    assert normalize_time(text) == text


def test_correction_is_rejected_at_the_api(client):
    response = client.post("/api/appointments", json=payload("not 3:30, make it 4:00 PM"))
    assert response.status_code == 422
    assert "start_time" in response.json()["error"]["message"]


def test_leftover_minute_word_makes_the_time_ambiguous():
    text = "three thirty five"
    assert normalize_time(text) == text


def test_leftover_minute_word_is_rejected_at_the_tools_route(tools_client):
    response = tools_client.post(
        "/tools/book-appointment",
        json=payload("three thirty five"),
        headers={"X-Tool-Secret": SECRET},
    )
    assert response.status_code == 422
    assert "start_time" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "text",
    ["3:30 or 4:00", "3:30 pm and 4:00 pm", "half past three or four"],
)
def test_two_times_in_one_request_are_ambiguous(text):
    assert normalize_time(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3:30 PM", "15:30"),
        ("3:30 for my consultation", "15:30"),
        ("half past three in the afternoon", "15:30"),
        ("12:30 AM", "00:30"),
    ],
)
def test_a_single_time_with_extra_words_still_reads_correctly(text, expected):
    assert normalize_time(text) == expected
