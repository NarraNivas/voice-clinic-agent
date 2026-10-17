"""The local staff queue: reading requests and moving them through their states."""

import pytest
from app.db import connect
from app.main import create_app, create_tools_app
from app.services.escalation import escalate
from fastapi.testclient import TestClient

from tests.conftest import FIXED_NOW


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, clock=lambda: FIXED_NOW)) as test_client:
        yield test_client


def request_id_for(settings, reason):
    conn = connect(settings.database_path)
    try:
        escalate(conn, reason=reason, channel="demo", clock=lambda: FIXED_NOW)
        return conn.execute(
            "SELECT request_id FROM staff_requests WHERE reason = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (reason,),
        ).fetchone()[0]
    finally:
        conn.close()


def test_the_queue_lists_requests_with_their_handoff_state(client, settings):
    request_id_for(settings, "medical")
    body = client.get("/api/staff/requests").json()
    assert body["statuses"] == ["open", "in_progress", "resolved"]
    item = body["items"][0]
    assert item["status"] == "open"
    assert item["handoff_state"] == "queued"  # queued is not the same as delivered


def test_a_request_moves_through_its_states(client, settings):
    request_id = request_id_for(settings, "human_request")
    assert (
        client.post(
            f"/api/staff/requests/{request_id}/status", json={"status": "in_progress"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/staff/requests/{request_id}/status", json={"status": "resolved"}
        ).status_code
        == 200
    )
    item = next(
        i
        for i in client.get("/api/staff/requests").json()["items"]
        if i["request_id"] == request_id
    )
    assert item["status"] == "resolved"


def test_an_unknown_status_is_rejected(client, settings):
    request_id = request_id_for(settings, "medical")
    assert (
        client.post(
            f"/api/staff/requests/{request_id}/status", json={"status": "closed"}
        ).status_code
        == 422
    )


def test_an_unknown_request_is_a_404(client):
    assert (
        client.post(
            "/api/staff/requests/" + "a" * 32 + "/status", json={"status": "resolved"}
        ).status_code
        == 404
    )


def test_the_staff_queue_is_not_on_the_tools_only_app(settings):
    with TestClient(create_tools_app(settings)) as tools:
        assert tools.get("/api/staff/requests").status_code == 404
