"""Read-only analytics for the local dashboard. Aggregates only, never names or caller text."""

import sqlite3
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_conn
from app.repositories import analytics

router = APIRouter()

DateParam = Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]


@router.get("/analytics")
def dashboard(
    provider_id: Annotated[int | None, Query(ge=1)] = None,
    appointment_type: Literal["checkup", "cleaning", "consultation"] | None = None,
    date_from: DateParam = None,
    date_to: DateParam = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict[str, Any]:
    return analytics.dashboard(
        conn,
        provider_id=provider_id,
        appointment_type=appointment_type,
        date_from=date_from,
        date_to=date_to,
    )
