"""Request and response schemas for the HTTP API. Validation happens here, at the boundary.

Writes use a two-step flow. A request with no confirmation_token returns a preview and a token.
Sending that token back with the same details performs the write. There is no boolean flag.
"""

from datetime import date as Date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field

from app.models.normalize import normalize_appointment_type, normalize_date, normalize_time

AppointmentType = Literal["cleaning", "checkup", "consultation"]

AppointmentTypeIn = Annotated[
    AppointmentType,
    BeforeValidator(normalize_appointment_type),
    Field(description="Exactly one of: cleaning, checkup, consultation."),
]
TimeOfDay = Annotated[
    str,
    BeforeValidator(normalize_time),
    Field(
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description=(
            "Start time in 24-hour HH:MM format. Convert what the caller says: 3:30 PM becomes "
            "15:30, 9:00 AM becomes 09:00, 12:30 PM becomes 12:30. Never send AM, PM, or words."
        ),
        examples=["09:00", "15:30"],
    ),
]
ConfirmationCode = Field(pattern=r"^MSD-[A-Z0-9]{6}$", description="e.g. MSD-7K2Q9X")
PatientName = Field(min_length=2, max_length=80)


def _blank_to_none(value: Any) -> Any:
    """Voice agents often send "" for optional fields they are not using. Treat that as absent."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


OptionalToken = Annotated[
    Annotated[
        str,
        Field(
            min_length=20,
            max_length=100,
            description="Returned by the preview. Send it back with the same details to confirm.",
        ),
    ]
    | None,
    BeforeValidator(_blank_to_none),
]
OptionalKey = Annotated[
    Annotated[str, Field(min_length=8, max_length=100)] | None,
    BeforeValidator(_blank_to_none),
]


DateIn = Annotated[
    Date,
    BeforeValidator(normalize_date),
    Field(
        description=(
            "Calendar date in YYYY-MM-DD format. Convert what the caller says: October 23rd "
            "becomes 2026-10-23. Use the current year unless the caller names another."
        ),
        examples=["2026-10-23"],
    ),
]


class AvailabilityRequest(BaseModel):
    date: DateIn
    appointment_type: AppointmentTypeIn
    provider_id: int | None = Field(
        default=None,
        ge=1,
        description="Optional. Omit to offer or book with any free provider.",
    )


class AvailabilityResponse(BaseModel):
    date: Date
    appointment_type: AppointmentType
    duration_minutes: int
    slots: list[str]
    message: str


class BookingRequest(BaseModel):
    patient_name: str = PatientName
    appointment_type: AppointmentTypeIn
    date: DateIn
    start_time: TimeOfDay
    idempotency_key: OptionalKey = None
    provider_id: int | None = Field(
        default=None,
        ge=1,
        description="Optional. Omit to offer or book with any free provider.",
    )
    confirmation_token: OptionalToken = None


class VoiceBookingRequest(BaseModel):
    """Booking body for the voice agent. It has no idempotency key: the confirmation token
    already prevents duplicates, and a key the agent invents would only cause validation errors."""

    patient_name: str = PatientName
    appointment_type: AppointmentTypeIn
    date: DateIn
    start_time: TimeOfDay
    confirmation_token: OptionalToken = None
    provider_id: int | None = Field(
        default=None,
        ge=1,
        description="Optional. Omit to offer or book with any free provider.",
    )


class RescheduleRequest(BaseModel):
    confirmation_code: str = ConfirmationCode
    patient_name: str = PatientName
    new_date: DateIn
    new_start_time: TimeOfDay
    confirmation_token: OptionalToken = None


class CancelRequest(BaseModel):
    confirmation_code: str = ConfirmationCode
    patient_name: str = PatientName
    confirmation_token: OptionalToken = None


class LookupRequest(BaseModel):
    confirmation_code: str = ConfirmationCode
    patient_name: str = PatientName


class AppointmentOut(BaseModel):
    confirmation_code: str
    patient_name: str
    appointment_type: str
    starts_at: str
    duration_minutes: int
    status: str


class ChangeResult(BaseModel):
    status: Literal["confirmation_required", "booked", "rescheduled", "cancelled"]
    summary: str
    confirmation_code: str | None = None
    confirmation_token: str | None = None
    appointment: AppointmentOut | None = None


class FaqRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class FaqResponse(BaseModel):
    answered: bool
    topic: str | None = None
    answer: str | None = None
    message: str


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class MessageResponse(BaseModel):
    route: str
    reply: str
    data: dict[str, object] = Field(default_factory=dict)


EscalationReason = Literal["emergency", "medical", "human_request", "unsupported", "ambiguous"]


class EscalationRequest(BaseModel):
    # Reason only. Free text is not accepted, so callers cannot put personal detail in the log.
    reason: EscalationReason


class EscalationResponse(BaseModel):
    escalation_id: int
    message: str
    front_desk_phone: str
    # "queued" until the simulated CRM accepts the handoff. Never "delivered" before that.
    delivery_state: str = "queued"
