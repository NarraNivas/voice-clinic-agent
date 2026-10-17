"""Availability, booking, rescheduling, and cancellation rules.

Writes are two-step. The first call, with no confirmation_token, returns a preview and a
single-use token bound to the exact operation and details. The second call sends that token back.
The token is checked and marked used inside the same transaction as the write, so a failed check
rolls back both. A boolean flag in the request cannot write anything on its own.

Logs record outcomes and numeric appointment ids only: no patient names and no confirmation codes.
"""

import secrets
from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from app.models.domain import Appointment
from app.models.schemas import (
    AppointmentOut,
    AppointmentType,
    AvailabilityResponse,
    BookingRequest,
    CancelRequest,
    ChangeResult,
    RescheduleRequest,
)
from app.repositories import log
from app.repositories.appointments import AppointmentRepository
from app.services import clinic_rules as rules
from app.services import confirmations
from app.services.errors import ApiError

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, to avoid misreading
Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


class AppointmentService:
    def __init__(
        self,
        repo: AppointmentRepository,
        *,
        channel: str = "demo",
        clock: Clock = _now,
    ) -> None:
        self.repo = repo
        self.channel = channel
        self.clock = clock

    # --- availability -------------------------------------------------------

    def availability(self, day: date, appointment_type: AppointmentType) -> AvailabilityResponse:
        now = self.clock()
        duration = rules.APPOINTMENT_DURATIONS[appointment_type]
        if day < now.date():
            slots: list[str] = []
            message = "That date has already passed. Pick today or a later date."
        elif not _in_booking_window(day, now):
            slots = []
            message = f"Bookings open up to {rules.BOOKING_WINDOW_DAYS} days ahead, from today."
        else:
            slots = rules.open_slots(day, duration, self._booked_intervals(day), now)
            message = (
                f"{len(slots)} open slot(s) found."
                if slots
                else "No open slots on that day. Try another date."
            )
        self._log("check_availability", "ok", f"{appointment_type}: {len(slots)} slots")
        return AvailabilityResponse(
            date=day,
            appointment_type=appointment_type,
            duration_minutes=duration,
            slots=slots,
            message=message,
        )

    # --- booking ------------------------------------------------------------

    def book(self, req: BookingRequest) -> ChangeResult:
        if req.idempotency_key:
            existing = self.repo.get_by_idempotency_key(req.idempotency_key)
            if existing:
                if existing.status != "booked":
                    # A cancelled booking is never reported as a success. Start a new request.
                    raise ApiError(
                        "idempotency_used",
                        "That request was already used for a booking that is now cancelled. "
                        "Start a new request to book again.",
                        status_code=409,
                    )
                if not _same_booking(existing, req):
                    raise ApiError(
                        "idempotency_conflict",
                        "This request key was already used for a different booking.",
                        status_code=409,
                    )
                return self._booked_result(existing, already_done=True)

        duration = rules.APPOINTMENT_DURATIONS[req.appointment_type]
        starts_at = _combine(req.date, req.start_time)
        now = self.clock()
        self._check_slot(starts_at, duration, now, ignore_id=None)

        details = {
            "name": _normalize(req.patient_name),
            "type": req.appointment_type,
            "starts_at": starts_at.isoformat(timespec="minutes"),
            "key": req.idempotency_key or "",
        }
        fingerprint = confirmations.digest("book", details)

        if req.confirmation_token is None:
            token = self._issue_token("book", fingerprint)
            self._log("book_appointment", "preview", f"{req.appointment_type} preview")
            return ChangeResult(
                status="confirmation_required",
                summary=(
                    f"Book a {req.appointment_type} for {req.patient_name} on "
                    f"{rules.describe(starts_at)} ({duration} min). Say yes to confirm."
                ),
                confirmation_token=token,
            )

        with self.repo.write_transaction():
            confirmations.consume(
                self.repo.conn,
                token=req.confirmation_token,
                operation="book",
                details_digest=fingerprint,
                now=now,
            )
            # Re-check inside the transaction: another request may have taken the slot.
            self._check_slot(starts_at, duration, now, ignore_id=None)
            appointment = self.repo.insert(
                confirmation_code=self._new_code(),
                patient_name=req.patient_name.strip(),
                appointment_type=req.appointment_type,
                starts_at=starts_at,
                duration_minutes=duration,
                idempotency_key=req.idempotency_key,
                now=now,
            )
        self._log("book_appointment", "booked", f"appointment #{appointment.id}")
        return self._booked_result(appointment, already_done=False)

    # --- lookup, reschedule, cancel ----------------------------------------

    def lookup(self, confirmation_code: str, patient_name: str) -> AppointmentOut:
        appointment = self._find(confirmation_code, patient_name)
        self._log("lookup_appointment", "ok", f"appointment #{appointment.id}")
        return _out(appointment)

    def reschedule(self, req: RescheduleRequest) -> ChangeResult:
        appointment = self._find(req.confirmation_code, req.patient_name)
        if appointment.status != "booked":
            raise ApiError("already_cancelled", "This appointment is cancelled.", 409)
        now = self.clock()
        self._check_notice(appointment, now)

        new_start = _combine(req.new_date, req.new_start_time)
        self._check_slot(new_start, appointment.duration_minutes, now, ignore_id=appointment.id)

        fingerprint = confirmations.digest(
            "reschedule",
            {"appointment": appointment.id, "starts_at": new_start.isoformat(timespec="minutes")},
        )

        if req.confirmation_token is None:
            token = self._issue_token("reschedule", fingerprint)
            self._log("reschedule_appointment", "preview", f"appointment #{appointment.id}")
            return ChangeResult(
                status="confirmation_required",
                summary=(
                    f"Move your {appointment.appointment_type} from "
                    f"{rules.describe(appointment.starts_at)} to {rules.describe(new_start)}. "
                    "Say yes to confirm."
                ),
                confirmation_code=appointment.confirmation_code,
                confirmation_token=token,
            )

        with self.repo.write_transaction():
            confirmations.consume(
                self.repo.conn,
                token=req.confirmation_token,
                operation="reschedule",
                details_digest=fingerprint,
                now=now,
            )
            self._check_slot(new_start, appointment.duration_minutes, now, ignore_id=appointment.id)
            self.repo.move(appointment.id, new_start, now)
        updated = self.repo.get_by_code(appointment.confirmation_code)
        assert updated is not None  # the row was just updated inside this request
        self._log("reschedule_appointment", "rescheduled", f"appointment #{appointment.id}")
        return ChangeResult(
            status="rescheduled",
            summary=f"Rescheduled to {rules.describe(updated.starts_at)}.",
            confirmation_code=updated.confirmation_code,
            appointment=_out(updated),
        )

    def cancel(self, req: CancelRequest) -> ChangeResult:
        appointment = self._find(req.confirmation_code, req.patient_name)
        if appointment.status != "booked":
            raise ApiError("already_cancelled", "This appointment is already cancelled.", 409)
        now = self.clock()
        self._check_notice(appointment, now)

        fingerprint = confirmations.digest("cancel", {"appointment": appointment.id})

        if req.confirmation_token is None:
            token = self._issue_token("cancel", fingerprint)
            self._log("cancel_appointment", "preview", f"appointment #{appointment.id}")
            return ChangeResult(
                status="confirmation_required",
                summary=(
                    f"Cancel your {appointment.appointment_type} on "
                    f"{rules.describe(appointment.starts_at)}. Say yes to confirm."
                ),
                confirmation_code=appointment.confirmation_code,
                confirmation_token=token,
            )

        with self.repo.write_transaction():
            confirmations.consume(
                self.repo.conn,
                token=req.confirmation_token,
                operation="cancel",
                details_digest=fingerprint,
                now=now,
            )
            self.repo.set_status(appointment.id, "cancelled", now)
        self._log("cancel_appointment", "cancelled", f"appointment #{appointment.id}")
        return ChangeResult(
            status="cancelled",
            summary="Your appointment has been cancelled.",
            confirmation_code=appointment.confirmation_code,
            appointment=_out(appointment, status="cancelled"),
        )

    # --- helpers ------------------------------------------------------------

    def _issue_token(self, operation: str, fingerprint: str) -> str:
        return confirmations.issue(
            self.repo.conn,
            operation=operation,
            details_digest=fingerprint,
            now=self.clock(),
        )

    def _booked_intervals(
        self, day: date, ignore_id: int | None = None
    ) -> list[tuple[datetime, datetime]]:
        return [(a.starts_at, a.ends_at) for a in self.repo.booked_on(day) if a.id != ignore_id]

    def _check_slot(
        self, starts_at: datetime, duration: int, now: datetime, ignore_id: int | None
    ) -> None:
        day = starts_at.date()
        if starts_at <= now:
            raise ApiError("time_in_past", "That time has already passed.")
        if not _in_booking_window(day, now):
            raise ApiError(
                "outside_booking_window",
                f"Bookings open up to {rules.BOOKING_WINDOW_DAYS} days ahead, from today.",
            )
        hours = rules.hours_for(day)
        if hours is None:
            raise ApiError("clinic_closed", "The clinic is closed that day.")
        open_time, close_time = hours
        ends_at = starts_at + timedelta(minutes=duration)
        if starts_at < datetime.combine(day, open_time) or ends_at > datetime.combine(
            day, close_time
        ):
            raise ApiError("clinic_closed", "That time is outside clinic hours.")
        if starts_at.minute % rules.SLOT_MINUTES != 0:
            raise ApiError(
                "invalid_time",
                f"Start times must be on the {rules.SLOT_MINUTES}-minute grid.",
            )
        if rules.overlaps(starts_at, ends_at, self._booked_intervals(day, ignore_id)):
            raise ApiError("slot_unavailable", "That time is no longer available.", 409)

    def _check_notice(self, appointment: Appointment, now: datetime) -> None:
        if appointment.starts_at - now < timedelta(hours=rules.CHANGE_NOTICE_HOURS):
            # Changes inside the notice window go to a person, not to the caller.
            log.record_escalation(self.repo.conn, reason="change_too_late", now=now)
            self._log("change_appointment", "escalated", f"appointment #{appointment.id}")
            raise ApiError(
                "change_too_late",
                f"Changes need {rules.CHANGE_NOTICE_HOURS} hours' notice, so this change "
                "cannot be made here. This demo records the request for the clinic. "
                "No staff member is notified.",
                status_code=409,
            )

    def _find(self, confirmation_code: str, patient_name: str) -> Appointment:
        appointment = self.repo.get_by_code(confirmation_code)
        # Same message for "no such code" and "name mismatch", so codes cannot be probed.
        if appointment is None or _normalize(appointment.patient_name) != _normalize(patient_name):
            raise ApiError("not_found", "No appointment matches those details.", 404)
        return appointment

    def _new_code(self) -> str:
        while True:
            code = "MSD-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            if self.repo.get_by_code(code) is None:
                return code

    def _booked_result(self, appointment: Appointment, *, already_done: bool) -> ChangeResult:
        suffix = " (already booked for this request)" if already_done else ""
        return ChangeResult(
            status="booked",
            summary=(
                f"Booked {appointment.confirmation_code} for "
                f"{rules.describe(appointment.starts_at)}{suffix}."
            ),
            confirmation_code=appointment.confirmation_code,
            appointment=_out(appointment),
        )

    def _log(self, tool: str, outcome: str, summary: str) -> None:
        log.record_interaction(
            self.repo.conn,
            channel=self.channel,
            tool_name=tool,
            outcome=outcome,
            summary=summary,
            now=self.clock(),
        )


def _combine(day: date, start_time: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(start_time))


def _in_booking_window(day: date, now: datetime) -> bool:
    today = now.date()
    return today <= day <= today + timedelta(days=rules.BOOKING_WINDOW_DAYS)


def _normalize(name: str) -> str:
    return " ".join(name.split()).casefold()


def _same_booking(appointment: Appointment, req: BookingRequest) -> bool:
    return (
        _normalize(appointment.patient_name) == _normalize(req.patient_name)
        and appointment.appointment_type == req.appointment_type
        and appointment.starts_at == _combine(req.date, req.start_time)
    )


def _out(appointment: Appointment, status: str | None = None) -> AppointmentOut:
    return AppointmentOut(
        confirmation_code=appointment.confirmation_code,
        patient_name=appointment.patient_name,
        appointment_type=appointment.appointment_type,
        starts_at=appointment.starts_at.isoformat(timespec="minutes"),
        duration_minutes=appointment.duration_minutes,
        status=status or appointment.status,
    )
