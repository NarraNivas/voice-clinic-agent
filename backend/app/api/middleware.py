"""Request correlation and timing. Logs the method, path, status, and duration, never bodies."""

import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("clinic.http")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def add_same_origin_guard(app: FastAPI) -> None:
    """Refuse state-changing /api calls that a browser sends from another site.

    Browsers always send an Origin header on cross-site writes. If it names a different host,
    the request is refused. Requests with no Origin header (curl, scripts, the test client) are
    not affected. This is defence in depth: the demo API also has no CORS policy.
    """

    @app.middleware("http")
    async def same_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and origin is not None
            and urlsplit(origin).netloc != request.headers.get("host", "")
        ):
            log.warning("refused cross-origin write path=%s", request.url.path)
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "cross_origin_request",
                        "message": "Writes must come from this demo's own page.",
                    }
                },
            )
        return await call_next(request)


def add_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = secrets.token_hex(8)
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        log.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
