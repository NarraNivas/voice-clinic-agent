"""Read-only view of the staff handoff queue for the demo: states and reasons, never caller text."""

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_conn
from app.repositories import outbox as outbox_repo

router = APIRouter()


@router.get("/outbox")
def outbox_status(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, Any]:
    return {
        "counts": outbox_repo.counts(conn),
        "items": outbox_repo.recent(conn),
    }
