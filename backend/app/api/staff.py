"""Local staff queue. There is no login here, so these routes are for the local demo only.

They sit beside the demo API, which is unauthenticated and bound to localhost. They are never
served by the tools-only app.
"""

import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from app.api.deps import get_clock, get_conn
from app.repositories import staff

router = APIRouter()


class StatusChange(BaseModel):
    status: Literal["open", "in_progress", "resolved"]


@router.get("/staff/requests")
def list_staff_requests(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, object]:
    items = staff.list_requests(conn)
    return {"items": items, "statuses": list(staff.STATUSES)}


@router.post("/staff/requests/{request_id}/status")
def change_status(
    body: StatusChange,
    request_id: str = Path(pattern=r"^[a-f0-9]{32}$"),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> dict[str, object]:
    if not staff.set_status(conn, request_id, body.status, clock()):
        raise HTTPException(status_code=404, detail="No such staff request.")
    return {"request_id": request_id, "status": body.status}
