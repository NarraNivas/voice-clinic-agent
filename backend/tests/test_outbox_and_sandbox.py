"""The handoff outbox and the CRM sandbox: retries on a fake clock, bounded attempts, idempotent
upserts, and the injected failures. Real localhost HTTP is covered by the journey test."""

import secrets
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from app.db import connect, init_db
from app.repositories import outbox as outbox_repo
from app.services import escalation
from app.services.outbox import (
    LEASE,
    MAX_ATTEMPTS,
    CrmReply,
    CrmUnavailable,
    HttpCrmClient,
    backoff_after,
    deliver_due,
)
from crm_sandbox.app import create_crm_app
from fastapi.testclient import TestClient

T0 = datetime(2026, 10, 12, 8, 0)


class FakeCrm:
    """Answers each call from a script of replies. Records every call it receives."""

    def __init__(self, *replies) -> None:
        self.replies = list(replies)
        self.calls: list[str] = []
        self.saved: dict[str, str] = {}

    def put_case(self, request_id: str, payload: dict) -> CrmReply:
        self.calls.append(request_id)
        reply = self.replies.pop(0) if self.replies else CrmReply(200, "CASE-000001")
        if isinstance(reply, Exception):
            raise reply
        if reply.status in (200, 201) and reply.case_ref:
            self.saved.setdefault(request_id, reply.case_ref)
        return reply


@pytest.fixture
def db(tmp_path) -> Path:
    path = tmp_path / "outbox.db"
    init_db(path)
    return path


def queue_one(db_path: Path) -> str:
    conn = connect(db_path)
    try:
        request_id = secrets.token_hex(16)
        conn.execute("BEGIN IMMEDIATE")
        outbox_repo.create_staff_request(
            conn,
            request_id=request_id,
            reason="medical",
            appointment_id=None,
            payload={"category": "medical", "reason": "medical", "appointment_ref": None},
            now=T0,
        )
        conn.execute("COMMIT")
        return request_id
    finally:
        conn.close()


def state(db_path: Path, request_id: str):
    conn = connect(db_path)
    try:
        return outbox_repo.get(conn, request_id)
    finally:
        conn.close()


def run(db_path: Path, crm, at: datetime):
    conn = connect(db_path)
    try:
        return deliver_due(conn, crm, now=at)
    finally:
        conn.close()


# --- C3: the worker -----------------------------------------------------------------------


def test_backoff_doubles_and_is_capped():
    assert backoff_after(1) == timedelta(seconds=30)
    assert backoff_after(2) == timedelta(seconds=60)
    assert backoff_after(3) == timedelta(seconds=120)
    assert backoff_after(20) == timedelta(minutes=15)


def test_a_healthy_crm_delivers_on_the_first_try(db):
    request_id = queue_one(db)
    crm = FakeCrm(CrmReply(201, "CASE-000001"))
    results = run(db, crm, T0)
    assert [r.outcome for r in results] == ["delivered"]
    row = state(db, request_id)
    assert row.state == "delivered"
    assert row.crm_case_ref == "CASE-000001"
    assert row.attempts == 1


def test_a_failing_crm_is_retried_on_the_backoff_schedule(db):
    request_id = queue_one(db)
    crm = FakeCrm(CrmReply(503, None), CrmReply(503, None))
    run(db, crm, T0)
    assert state(db, request_id).next_attempt_at == T0 + timedelta(seconds=30)
    # Nothing is due before the backoff ends.
    assert run(db, crm, T0 + timedelta(seconds=29)) == []
    run(db, crm, T0 + timedelta(seconds=30))
    assert state(db, request_id).next_attempt_at == T0 + timedelta(seconds=90)


def test_unreachable_crm_is_retryable(db):
    request_id = queue_one(db)
    crm = FakeCrm(CrmUnavailable("connection refused"))
    results = run(db, crm, T0)
    assert results[0].outcome == "retry"
    assert state(db, request_id).state == "queued"


def test_retries_stop_after_the_bounded_number_of_attempts(db):
    request_id = queue_one(db)
    crm = FakeCrm(*[CrmReply(503, None)] * MAX_ATTEMPTS)
    now = T0
    for _ in range(MAX_ATTEMPTS):
        run(db, crm, now)
        now = now + timedelta(hours=1)
    row = state(db, request_id)
    assert row.state == "failed"
    assert row.attempts == MAX_ATTEMPTS
    assert len(crm.calls) == MAX_ATTEMPTS


def test_a_conflict_is_not_retried(db):
    request_id = queue_one(db)
    crm = FakeCrm(CrmReply(409, None))
    results = run(db, crm, T0)
    assert results[0].outcome == "failed"
    assert state(db, request_id).state == "failed"
    assert len(crm.calls) == 1


def test_a_lease_stops_a_second_worker_sending_the_same_handoff(db):
    queue_one(db)
    crm = FakeCrm(CrmReply(201, "CASE-000001"))
    run(db, crm, T0)
    assert run(db, crm, T0) == []  # already delivered, and the lease would hide it anyway
    assert len(crm.calls) == 1


def test_a_claimed_handoff_is_hidden_until_its_lease_ends(db):
    request_id = queue_one(db)
    conn = connect(db)
    try:
        outbox_repo.claim(conn, request_id, T0 + LEASE)
    finally:
        conn.close()
    assert run(db, FakeCrm(), T0) == []
    assert [r.request_id for r in run(db, FakeCrm(), T0 + LEASE)] == [request_id]


def test_http_client_maps_a_refused_connection_to_retryable(db):
    request_id = queue_one(db)
    dead = HttpCrmClient("http://127.0.0.1:9", timeout=1.0)  # nothing listens on port 9
    results = run(db, dead, T0)
    assert results[0].outcome == "retry"
    assert state(db, request_id).last_error.startswith("unreachable")


# --- C2: the handoff is queued, not delivered, when the request is made ------------------


def test_escalation_queues_a_handoff_and_says_so(db):
    conn = connect(db)
    try:
        result = escalation.escalate(conn, reason="medical", channel="demo", clock=lambda: T0)
        assert result.delivery_state == "queued"
        assert "not delivered" in result.message
        assert outbox_repo.get(conn, result.request_id).state == "queued"
    finally:
        conn.close()


# --- C1 and C4: the sandbox ---------------------------------------------------------------


@pytest.fixture
def crm(tmp_path):
    app = create_crm_app(tmp_path / "crm.db", faults_enabled=True)
    with TestClient(app) as client:
        yield client


REQUEST = "a" * 32
BODY = {"category": "medical", "reason": "medical", "appointment_ref": None}


def test_put_creates_once_and_returns_the_same_case_for_a_replay(crm):
    first = crm.put(f"/cases/{REQUEST}", json=BODY)
    again = crm.put(f"/cases/{REQUEST}", json=BODY)
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["case_ref"] == first.json()["case_ref"]
    assert crm.get("/cases").json()["count"] == 1


def test_the_same_request_id_with_different_content_is_a_conflict(crm):
    crm.put(f"/cases/{REQUEST}", json=BODY)
    other = crm.put(f"/cases/{REQUEST}", json=BODY | {"reason": "emergency"})
    assert other.status_code == 409


def test_a_malformed_request_id_is_rejected(crm):
    assert crm.put("/cases/not-a-real-id", json=BODY).status_code == 422


def test_a_simulated_outage_writes_nothing(crm):
    crm.post("/admin/faults", json={"fail_next": 1, "lose_response_next": 0})
    assert crm.put(f"/cases/{REQUEST}", json=BODY).status_code == 503
    assert crm.get("/cases").json()["count"] == 0


def test_a_lost_response_saves_the_case_but_reports_failure(crm):
    crm.post("/admin/faults", json={"fail_next": 0, "lose_response_next": 1})
    lost = crm.put(f"/cases/{REQUEST}", json=BODY)
    assert lost.status_code == 500
    assert crm.get("/cases").json()["count"] == 1
    retry = crm.put(f"/cases/{REQUEST}", json=BODY)
    assert retry.status_code == 200
    assert retry.json()["created"] is False


def test_fault_injection_is_off_unless_enabled(tmp_path):
    app = create_crm_app(tmp_path / "no-faults.db", faults_enabled=False)
    with TestClient(app) as client:
        assert client.post("/admin/faults", json={"fail_next": 1}).status_code == 404
        assert client.get("/health").json()["label"].startswith("local CRM sandbox")


def test_the_sandbox_gets_its_own_database(tmp_path):
    clinic = tmp_path / "clinic.db"
    crm_db = tmp_path / "crm.db"
    init_db(clinic)
    create_crm_app(crm_db)
    assert crm_db.exists()
    assert clinic.exists()
    conn = connect(crm_db)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_")
        }
    finally:
        conn.close()
    assert tables == {"cases"}
