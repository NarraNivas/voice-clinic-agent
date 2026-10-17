"""Application factories.

create_app: the local demo. Serves the demo page, /api/* (unauthenticated), and /tools/*.
create_tools_app: only /tools/* (secret-protected). This is the one to expose through a tunnel.

    uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000   # local demo
    uvicorn app.main:create_tools_app --factory --host 127.0.0.1 --port 8001  # tunnel target

Never point a tunnel at the port running create_app. It serves /api/*, which has no authentication.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.errors import register_error_handlers
from app.api.routes import router as api_router
from app.api.tools import router as tools_router
from app.config import Settings, load_settings
from app.db import init_db


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    init_db(settings.database_path)

    app = FastAPI(
        title="Voice Clinic Agent API",
        version="0.1.0",
        description="Fictional dental clinic demo. All data is invented.",
    )
    app.state.settings = settings
    register_error_handlers(app)
    app.include_router(api_router, prefix="/api")
    app.include_router(tools_router, prefix="/tools")

    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


def create_tools_app(settings: Settings | None = None) -> FastAPI:
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
    register_error_handlers(app)
    app.include_router(tools_router, prefix="/tools")
    return app
