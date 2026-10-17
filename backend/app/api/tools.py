"""Server-tool routes for the ElevenLabs agent. Every route requires the X-Tool-Secret header.

Each route calls the same services as the demo routes, but logs under channel "elevenlabs".
Tool results are plain JSON so the agent can read them back to the caller.
"""

import hmac
import sqlite3
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, Header

from app.api.deps import get_clock, get_conn, get_settings
from app.config import Settings
from app.models import schemas
from app.repositories.appointments import AppointmentRepository
from app.services import clinic_rules as rules
from app.services.booking import AppointmentService
from app.services.errors import ApiError
from app.services.escalation import escalate
from app.services.faq import match_faq

CHANNEL = "elevenlabs"

router = APIRouter()


def require_tool_secret(
    settings: Settings = Depends(get_settings),
    x_tool_secret: str | None = Header(default=None, alias="X-Tool-Secret"),
) -> None:
    expected = settings.tool_shared_secret
    if expected is None:
        raise ApiError(
            "tools_disabled",
            "Tool endpoints are disabled. Set TOOL_SHARED_SECRET to enable them.",
            status_code=503,
        )
    # Constant-time comparison so the secret cannot be guessed by timing differences.
    if x_tool_secret is None or not hmac.compare_digest(x_tool_secret, expected):
        raise ApiError("unauthorized", "Missing or invalid tool secret.", status_code=401)


def get_tool_service(
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> AppointmentService:
    return AppointmentService(AppointmentRepository(conn), channel=CHANNEL, clock=clock)


@router.post(
    "/check-availability",
    response_model=schemas.AvailabilityResponse,
    dependencies=[Depends(require_tool_secret)],
)
def check_availability(
    req: schemas.AvailabilityRequest,
    service: AppointmentService = Depends(get_tool_service),
) -> schemas.AvailabilityResponse:
    return service.availability(req.date, req.appointment_type)


@router.post(
    "/book-appointment",
    response_model=schemas.ChangeResult,
    dependencies=[Depends(require_tool_secret)],
)
def book_appointment(
    req: schemas.VoiceBookingRequest,
    service: AppointmentService = Depends(get_tool_service),
) -> schemas.ChangeResult:
    # Preview first: the agent reads the summary back. After a spoken yes it sends the
    # confirmation_token from that preview, with the same details.
    return service.book(schemas.BookingRequest(**req.model_dump()))


@router.post(
    "/lookup-appointment",
    response_model=schemas.AppointmentOut,
    dependencies=[Depends(require_tool_secret)],
)
def lookup_appointment(
    req: schemas.LookupRequest,
    service: AppointmentService = Depends(get_tool_service),
) -> schemas.AppointmentOut:
    return service.lookup(req.confirmation_code, req.patient_name)


@router.post(
    "/reschedule-appointment",
    response_model=schemas.ChangeResult,
    dependencies=[Depends(require_tool_secret)],
)
def reschedule_appointment(
    req: schemas.RescheduleRequest,
    service: AppointmentService = Depends(get_tool_service),
) -> schemas.ChangeResult:
    return service.reschedule(req)


@router.post(
    "/cancel-appointment",
    response_model=schemas.ChangeResult,
    dependencies=[Depends(require_tool_secret)],
)
def cancel_appointment(
    req: schemas.CancelRequest,
    service: AppointmentService = Depends(get_tool_service),
) -> schemas.ChangeResult:
    return service.cancel(req)


@router.post(
    "/answer-faq",
    response_model=schemas.FaqResponse,
    dependencies=[Depends(require_tool_secret)],
)
def answer_faq(req: schemas.FaqRequest) -> schemas.FaqResponse:
    match = match_faq(req.question)
    if match is None:
        return schemas.FaqResponse(
            answered=False,
            message="No FAQ match. Say so, and offer to record a request for the clinic.",
        )
    return schemas.FaqResponse(answered=True, topic=match.topic, answer=match.answer, message="ok")


@router.post(
    "/escalate-to-human",
    response_model=schemas.EscalationResponse,
    dependencies=[Depends(require_tool_secret)],
)
def escalate_to_human(
    req: schemas.EscalationRequest,
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> schemas.EscalationResponse:
    result = escalate(conn, reason=req.reason, channel=CHANNEL, clock=clock)
    return schemas.EscalationResponse(
        escalation_id=result.escalation_id,
        message=result.message,
        front_desk_phone=rules.FRONT_DESK_PHONE,
        delivery_state=result.delivery_state,
    )
