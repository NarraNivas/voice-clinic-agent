"""FastAPI dependencies: settings, one SQLite connection per request, and services."""

import sqlite3
from collections.abc import Iterator

from fastapi import Depends, Request

from app.config import Settings
from app.db import connect
from app.repositories.appointments import AppointmentRepository
from app.services.booking import AppointmentService


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_conn(settings: Settings = Depends(get_settings)) -> Iterator[sqlite3.Connection]:
    conn = connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def get_demo_service(conn: sqlite3.Connection = Depends(get_conn)) -> AppointmentService:
    return AppointmentService(AppointmentRepository(conn), channel="demo")


def get_repo(conn: sqlite3.Connection = Depends(get_conn)) -> AppointmentRepository:
    return AppointmentRepository(conn)
