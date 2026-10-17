"""Demo-mode text router. Deterministic rules, no LLM.

It answers FAQ questions, shows availability when a date and type are given, escalates
medical, emergency, and human-request messages, and asks for clarification otherwise.
It never writes bookings. Writes happen only through the confirmed booking form or tool calls.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.models.schemas import AppointmentType
from app.repositories.appointments import AppointmentRepository
from app.services import safety
from app.services.booking import AppointmentService
from app.services.escalation import escalate
from app.services.faq import match_faq

ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
TYPE_WORDS: dict[str, AppointmentType] = {
    "cleaning": "cleaning",
    "checkup": "checkup",
    "check-up": "checkup",
    "check up": "checkup",
    "consult": "consultation",
}
# Word boundaries keep "cancellation policy" (an FAQ question) from matching "cancel".
CHANGE_INTENT = re.compile(r"\b(book|booking|schedule|reschedule|cancel|move)\b")
CHANNEL = "demo"

ESCALATION_ROUTES = {
    "emergency": "escalate_emergency",
    "medical": "escalate_medical",
    "human_request": "escalate_human",
}


@dataclass(frozen=True)
class RouteResult:
    route: str
    reply: str
    data: dict[str, Any] = field(default_factory=dict)


def route_message(
    text: str,
    *,
    repo: AppointmentRepository,
    clock: Callable[[], datetime],
) -> RouteResult:
    lowered = " ".join(text.lower().split())

    # Safety first: emergency and medical wording is never answered by the assistant.
    verdict = safety.screen(lowered)
    if verdict.kind in ESCALATION_ROUTES:
        _, reply = escalate(repo.conn, reason=verdict.kind, channel=CHANNEL, clock=clock)
        return RouteResult(ESCALATION_ROUTES[verdict.kind], reply)

    # Chat text never makes a change. Point the caller to the preview-then-confirm form instead.
    if CHANGE_INTENT.search(lowered):
        return RouteResult(
            "use_booking_form",
            "To book, reschedule, or cancel, use the booking form on this page. "
            "Each change is shown to you and needs your confirmation first. "
            "I can also check open times if you give me a date and appointment type.",
        )

    service = AppointmentService(repo, channel=CHANNEL, clock=clock)
    iso_match = ISO_DATE.search(lowered)
    if iso_match:
        return _availability_route(lowered, iso_match.group(0), service)

    faq = match_faq(lowered)
    if faq:
        return RouteResult("faq", faq.answer, {"topic": faq.topic})

    return RouteResult(
        "clarify",
        "I can answer questions about hours, location, insurance, and policies, or check "
        "open times for a date. Could you rephrase? If you'd rather speak to a person, say so.",
    )


def _availability_route(lowered: str, iso_text: str, service: AppointmentService) -> RouteResult:
    try:
        day = date.fromisoformat(iso_text)
    except ValueError:
        return RouteResult("clarify", "That date doesn't look valid. Use the format YYYY-MM-DD.")

    appointment_type = next((kind for word, kind in TYPE_WORDS.items() if word in lowered), None)
    if appointment_type is None:
        return RouteResult(
            "ask_appointment_type",
            "Which appointment type would you like: cleaning, checkup, or consultation?",
            {"date": day.isoformat()},
        )

    result = service.availability(day, appointment_type)
    if result.slots:
        reply = f"Open {appointment_type} times on {day.isoformat()}: " + ", ".join(result.slots)
    else:
        reply = result.message
    return RouteResult("availability", reply, {"slots": result.slots, "date": day.isoformat()})
