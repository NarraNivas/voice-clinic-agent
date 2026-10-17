"""Shared fixtures. Every test gets its own temporary SQLite file."""

from collections.abc import Iterator
from datetime import date, datetime, timedelta

import pytest
from app.config import Settings
from app.db import connect, init_db
from app.main import create_app
from app.repositories.appointments import AppointmentRepository
from app.services.booking import AppointmentService
from fastapi.testclient import TestClient

# Fixed "now" for service tests: Monday 2026-10-12 at 08:00 clinic time.
FIXED_NOW = datetime(2026, 10, 12, 8, 0)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        tool_shared_secret=None,
        elevenlabs_agent_id=None,
        frontend_dir=tmp_path / "no-frontend",
    )


@pytest.fixture
def conn(settings: Settings) -> Iterator:
    init_db(settings.database_path)
    connection = connect(settings.database_path)
    yield connection
    connection.close()


@pytest.fixture
def service(conn) -> AppointmentService:
    return AppointmentService(AppointmentRepository(conn), clock=lambda: FIXED_NOW)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def next_weekday(weekday: int, min_days_ahead: int = 2) -> date:
    """First date on or after today + min_days_ahead that falls on the given weekday (Mon=0)."""
    day = date.today() + timedelta(days=min_days_ahead)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return day
