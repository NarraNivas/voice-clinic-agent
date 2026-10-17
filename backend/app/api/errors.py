"""Turn exceptions into the documented error shape. Never leak stack traces or input values."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.errors import ApiError

logger = logging.getLogger("clinic.api")


# What each field should look like, in words the caller or agent can act on.
FIELD_HINTS: dict[str, str] = {
    "date": "use YYYY-MM-DD",
    "new_date": "use YYYY-MM-DD",
    "start_time": "use 24-hour HH:MM, such as 14:30",
    "new_start_time": "use 24-hour HH:MM, such as 14:30",
    "appointment_type": "use cleaning, checkup, or consultation",
    "confirmation_code": "use the format MSD-XXXXXX",
    "confirmation_token": "send the token exactly as the preview returned it, or leave it out",
    "idempotency_key": "use at least 8 characters, or leave it out",
    "patient_name": "use the patient's name, 2 to 80 characters",
    "reason": "use emergency, medical, human_request, unsupported, or ambiguous",
    "question": "send the caller's question as text",
}


def _describe_problem(field: str, error_type: str) -> str:
    hint = FIELD_HINTS.get(field.rsplit(".", 1)[-1], "check this field")
    return f"{field or 'body'}: {hint}"


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def booking_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field names and the rule that failed only. Submitted values are never echoed or logged,
        # because they can contain patient names and contact details.
        problems = sorted(
            {
                _describe_problem(".".join(str(p) for p in err["loc"][1:]), err["type"])
                for err in exc.errors()
            }
        )
        message = "Invalid request. " + "; ".join(problems) if problems else "Invalid request."
        logger.warning(
            "validation failed path=%s fields=%s",
            request.url.path,
            ",".join(sorted({problem.split(":")[0] for problem in problems})),
        )
        return JSONResponse(status_code=422, content=error_body("invalid_request", message))

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong. Please try again."),
        )
