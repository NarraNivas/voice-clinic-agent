"""Demo-facing routes under /api. These are for the local demo page and are not authenticated.
Keep the server bound to 127.0.0.1. ElevenLabs uses the /tools routes instead."""

import sqlite3
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends

from app.api.deps import get_clock, get_conn, get_demo_service, get_repo, get_settings
from app.config import Settings
from app.models import schemas
from app.repositories import log
from app.repositories.appointments import AppointmentRepository
from app.services import clinic_rules as rules
from app.services.assistant import route_message
from app.services.booking import AppointmentService
from app.services.escalation import escalate
from app.services.faq import match_faq

router = APIRouter()


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "status": "ok",
        "mode": "demo",
        "tool_endpoints_enabled": settings.tool_shared_secret is not None,
        "elevenlabs_widget_configured": settings.elevenlabs_agent_id is not None,
        "elevenlabs_agent_id": settings.elevenlabs_agent_id,
    }


@router.get("/clinic")
def clinic_info() -> dict[str, object]:
    return {
        "name": rules.CLINIC_NAME,
        "address": rules.CLINIC_ADDRESS,
        "front_desk_phone": rules.FRONT_DESK_PHONE,
        "appointment_types": rules.APPOINTMENT_DURATIONS,
        "booking_window_days": rules.BOOKING_WINDOW_DAYS,
        "change_notice_hours": rules.CHANGE_NOTICE_HOURS,
        "slot_minutes": rules.SLOT_MINUTES,
    }


@router.post("/availability", response_model=schemas.AvailabilityResponse)
def availability(
    req: schemas.AvailabilityRequest,
    service: AppointmentService = Depends(get_demo_service),
) -> schemas.AvailabilityResponse:
    return service.availability(req.date, req.appointment_type)


@router.post("/appointments", response_model=schemas.ChangeResult)
def book(
    req: schemas.BookingRequest,
    service: AppointmentService = Depends(get_demo_service),
) -> schemas.ChangeResult:
    return service.book(req)


@router.post("/appointments/lookup", response_model=schemas.AppointmentOut)
def lookup(
    req: schemas.LookupRequest,
    service: AppointmentService = Depends(get_demo_service),
) -> schemas.AppointmentOut:
    # POST, not GET: a patient name should not appear in URLs or server logs.
    return service.lookup(req.confirmation_code, req.patient_name)


@router.post("/appointments/reschedule", response_model=schemas.ChangeResult)
def reschedule(
    req: schemas.RescheduleRequest,
    service: AppointmentService = Depends(get_demo_service),
) -> schemas.ChangeResult:
    return service.reschedule(req)


@router.post("/appointments/cancel", response_model=schemas.ChangeResult)
def cancel(
    req: schemas.CancelRequest,
    service: AppointmentService = Depends(get_demo_service),
) -> schemas.ChangeResult:
    return service.cancel(req)


@router.post("/faq", response_model=schemas.FaqResponse)
def faq(req: schemas.FaqRequest) -> schemas.FaqResponse:
    match = match_faq(req.question)
    if match is None:
        return schemas.FaqResponse(
            answered=False,
            message="I don't have an answer for that. Would you like to speak to a person?",
        )
    return schemas.FaqResponse(
        answered=True, topic=match.topic, answer=match.answer, message="Answered from FAQ."
    )


@router.post("/assistant/message", response_model=schemas.MessageResponse)
def assistant_message(
    req: schemas.MessageRequest,
    repo: AppointmentRepository = Depends(get_repo),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> schemas.MessageResponse:
    result = route_message(req.message, repo=repo, clock=clock)
    return schemas.MessageResponse(route=result.route, reply=result.reply, data=result.data)


@router.post("/escalations", response_model=schemas.EscalationResponse)
def create_escalation(
    req: schemas.EscalationRequest,
    conn: sqlite3.Connection = Depends(get_conn),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> schemas.EscalationResponse:
    result = escalate(conn, reason=req.reason, channel="demo", clock=clock)
    return schemas.EscalationResponse(
        escalation_id=result.escalation_id,
        message=result.message,
        front_desk_phone=rules.FRONT_DESK_PHONE,
        delivery_state=result.delivery_state,
    )


@router.get("/interactions")
def interactions(conn: sqlite3.Connection = Depends(get_conn)) -> dict[str, object]:
    return {"items": log.recent_interactions(conn, limit=20)}
