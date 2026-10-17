"""The CRM sandbox application. A simulator for demonstrating handoff delivery, nothing more.

Routes:
- PUT  /cases/{request_id}   create the case, or return the existing one for the same request
- GET  /cases/{request_id}   read one case
- GET  /cases                list cases (for reports)
- GET  /health               liveness, labelled as a simulator

Fault injection (only when the app is created with faults_enabled=True):
- POST /admin/faults   set how many upcoming PUTs fail with 503 before writing (fail_next), and
                       how many succeed in writing but answer 500 (lose_response_next), which
                       models a response that never reaches the client after the case is saved.
- GET  /admin/faults   read the current counters.
"""

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

REQUEST_ID = r"^[a-f0-9]{32}$"
SIMULATOR_LABEL = "local CRM sandbox (simulator, not a real CRM)"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    case_ref TEXT NOT NULL UNIQUE,
    payload_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    reason TEXT NOT NULL,
    appointment_ref TEXT,
    created_at TEXT NOT NULL
);
"""


class CaseIn(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=40)
    appointment_ref: str | None = Field(default=None, max_length=20)


class FaultSettings(BaseModel):
    fail_next: int = Field(default=0, ge=0, le=100)
    lose_response_next: int = Field(default=0, ge=0, le=100)


class _Faults:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.fail_next = 0
        self.lose_response_next = 0

    def set(self, fail_next: int, lose_response_next: int) -> None:
        with self._lock:
            self.fail_next = fail_next
            self.lose_response_next = lose_response_next

    def take(self, name: str) -> bool:
        with self._lock:
            remaining = getattr(self, name)
            if remaining > 0:
                setattr(self, name, remaining - 1)
                return True
            return False

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"fail_next": self.fail_next, "lose_response_next": self.lose_response_next}


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _payload_hash(body: CaseIn) -> str:
    canonical = json.dumps(body.model_dump(), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_crm_app(database_path: Path, *, faults_enabled: bool = False) -> FastAPI:
    app = FastAPI(
        title="Local CRM sandbox",
        version="0.1.0",
        description=f"Simulator: {SIMULATOR_LABEL}. Fictional data only.",
    )
    _connect(database_path).close()  # create the schema once at startup
    faults = _Faults()
    app.state.faults = faults

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "label": SIMULATOR_LABEL}

    @app.put("/cases/{request_id}")
    def put_case(
        body: CaseIn,
        request_id: str = PathParam(pattern=REQUEST_ID),
    ) -> JSONResponse:
        if faults.take("fail_next"):
            # Nothing is written. The client should retry later.
            return _error(503, "unavailable", "Simulated outage. Nothing was saved.")

        conn = _connect(database_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT case_ref, payload_hash FROM cases WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is not None:
                conn.execute("COMMIT")
                if row["payload_hash"] != _payload_hash(body):
                    return _error(
                        409, "conflict", "This request id already holds different content."
                    )
                status, created, case_ref = 200, False, row["case_ref"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO cases (request_id, case_ref, payload_hash, category, reason,
                                       appointment_ref, created_at)
                    VALUES (?, 'pending', ?, ?, ?, ?, ?)
                    """,
                    (
                        request_id,
                        _payload_hash(body),
                        body.category,
                        body.reason,
                        body.appointment_ref,
                        datetime.now(UTC).isoformat(timespec="seconds"),
                    ),
                )
                seq = cursor.lastrowid
                case_ref = f"CASE-{seq:06d}"
                conn.execute("UPDATE cases SET case_ref = ? WHERE seq = ?", (case_ref, seq))
                conn.execute("COMMIT")
                status, created = 201, True
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        if faults.take("lose_response_next"):
            # The case is saved, but the client is told something went wrong.
            return _error(500, "response_lost", "Simulated failure after the case was saved.")
        return JSONResponse(status_code=status, content={"case_ref": case_ref, "created": created})

    @app.get("/cases/{request_id}")
    def get_case(request_id: str = PathParam(pattern=REQUEST_ID)) -> JSONResponse:
        conn = _connect(database_path)
        try:
            row = conn.execute("SELECT * FROM cases WHERE request_id = ?", (request_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return _error(404, "not_found", "No case for that request id.")
        return JSONResponse(content=_case_view(row))

    @app.get("/cases")
    def list_cases() -> dict[str, Any]:
        conn = _connect(database_path)
        try:
            rows = conn.execute("SELECT * FROM cases ORDER BY seq").fetchall()
        finally:
            conn.close()
        return {"count": len(rows), "items": [_case_view(row) for row in rows]}

    if faults_enabled:

        @app.get("/admin/faults")
        def read_faults() -> dict[str, int]:
            return faults.snapshot()

        @app.post("/admin/faults")
        def set_faults(settings: FaultSettings) -> dict[str, int]:
            faults.set(settings.fail_next, settings.lose_response_next)
            return faults.snapshot()

    return app


def _case_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "request_id": row["request_id"],
        "case_ref": row["case_ref"],
        "category": row["category"],
        "reason": row["reason"],
        "appointment_ref": row["appointment_ref"],
        "created_at": row["created_at"],
    }
