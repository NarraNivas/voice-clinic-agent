"""Application factories.

create_app: the local demo. Serves the demo page, /api/* (unauthenticated), and /tools/*.
create_tools_app: only /tools/* (secret-protected). This is the one to expose through a tunnel.

    uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000   # local demo
    uvicorn app.main:create_tools_app --factory --host 127.0.0.1 --port 8001  # tunnel target

Never point a tunnel at the port running create_app. It serves /api/*, which has no authentication.
"""

from collections.abc import Callable
from datetime import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.analytics import router as analytics_router
from app.api.errors import register_error_handlers
from app.api.middleware import add_request_logging
from app.api.outbox import router as outbox_router
from app.api.routes import router as api_router
from app.api.staff import router as staff_router
from app.api.tools import router as tools_router
from app.config import Settings, load_settings
from app.db import init_db
from app.services.clinic_rules import clinic_now


def _clinic_clock(settings: Settings) -> Callable[[], datetime]:
    return lambda: clinic_now(settings.clinic_timezone)


def create_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    init_db(settings.database_path)

    app = FastAPI(
        title="Voice Clinic Agent API",
        version="0.1.0",
        description="Fictional dental clinic demo. All data is invented.",
    )
    app.state.settings = settings
    app.state.clock = clock or _clinic_clock(settings)
    register_error_handlers(app)
    add_request_logging(app)
    app.include_router(api_router, prefix="/api")
    app.include_router(tools_router, prefix="/tools")
    app.include_router(outbox_router, prefix="/api")
    app.include_router(staff_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


def create_tools_app(
    settings: Settings | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Tool routes only. No demo page, no /api, no activity log."""
    settings = settings or load_settings()
    init_db(settings.database_path)

    app = FastAPI(
        title="Voice Clinic Agent tools",
        version="0.1.0",
        description="Server tools for a voice agent. Requires X-Tool-Secret.",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.clock = clock or _clinic_clock(settings)
    register_error_handlers(app)
    app.include_router(tools_router, prefix="/tools")
    return app
