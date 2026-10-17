"""Availability, booking, rescheduling, and cancellation rules.

Writes are two-step. The first call, with no confirmation_token, returns a preview and a
single-use token bound to the operation, the details, and the appointment revision the caller
reviewed. The second call sends that token back. The token is checked, and marked used, inside the
same transaction as the write, so a failed check rolls back both.

A confirmed token keeps its outcome. If the same token is sent again, the stored outcome is
returned without writing, as long as the booking is still in the state that outcome describes.
Otherwise the caller gets an `outcome_superseded` conflict.

Logs record outcomes and numeric appointment ids only: no patient names and no confirmation codes.
"""

import secrets
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

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
from app.services.escalation import escalate

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I, to avoid misreading
Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    return rules.clinic_now()


class AppointmentService:
    def __init__(
        self,
        repo: AppointmentRepository,
        *,
        channel: str = "demo",
        clock: Clock = _default_clock,
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
        details = {
            "name": _normalize(req.patient_name),
            "type": req.appointment_type,
            "starts_at": starts_at.isoformat(timespec="minutes"),
            "key": req.idempotency_key or "",
        }
        fingerprint = confirmations.digest("book", details)

        if req.confirmation_token is None:
            self._check_slot(starts_at, duration, now, ignore_id=None)
            token = self._issue_token("book", fingerprint, revision=0)
            self._log("book_appointment", "preview", f"{req.appointment_type} preview")
            return ChangeResult(
                status="confirmation_required",
                summary=(
                    f"Book a {req.appointment_type} for {req.patient_name} on "
                    f"{rules.describe(starts_at)} ({duration} min). Say yes to confirm."
                ),
                confirmation_token=token,
            )

        recorded = confirmations.stored_outcome(
            self.repo.conn,
            token=req.confirmation_token,
            operation="book",
            details_digest=fingerprint,
        )
        if recorded is not None:
            return self._replay(recorded)

        with self.repo.write_transaction():
            replay = confirmations.consume(
                self.repo.conn,
                token=req.confirmation_token,
                operation="book",
                details_digest=fingerprint,
                current_revision=0,
                now=now,
            )
            if replay is not None:
                return self._replay(replay)
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
            result = self._booked_result(appointment, already_done=False)
            confirmations.record_outcome(
                self.repo.conn,
                token=req.confirmation_token,
                outcome=_outcome(result, appointment),
            )
        self._log("book_appointment", "booked", f"appointment #{appointment.id}")
        return result

    # --- lookup, reschedule, cancel ----------------------------------------

    def lookup(self, confirmation_code: str, patient_name: str) -> AppointmentOut:
        appointment = self._find(confirmation_code, patient_name)
        self._log("lookup_appointment", "ok", f"appointment #{appointment.id}")
        return _out(appointment)

    def reschedule(self, req: RescheduleRequest) -> ChangeResult:
        appointment = self._find(req.confirmation_code, req.patient_name)
        now = self.clock()
        new_start = _combine(req.new_date, req.new_start_time)
        fingerprint = confirmations.digest(
            "reschedule",
            {"appointment": appointment.id, "starts_at": new_start.isoformat(timespec="minutes")},
        )

        if req.confirmation_token is None:
            self._require_booked(appointment)
            self._check_notice(appointment, now)
            self._check_slot(new_start, appointment.duration_minutes, now, appointment.id)
            token = self._issue_token("reschedule", fingerprint, revision=appointment.revision)
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

        recorded = confirmations.stored_outcome(
            self.repo.conn,
            token=req.confirmation_token,
            operation="reschedule",
            details_digest=fingerprint,
        )
        if recorded is not None:
            return self._replay(recorded)
        self._check_notice(appointment, now)

        with self.repo.write_transaction():
            current = self._reload(appointment.id)
            replay = confirmations.consume(
                self.repo.conn,
                token=req.confirmation_token,
                operation="reschedule",
                details_digest=fingerprint,
                current_revision=current.revision,
                now=now,
            )
            if replay is not None:
                return self._replay(replay)
            self._require_booked(current)
            self._check_slot(new_start, current.duration_minutes, now, current.id)
            self.repo.move(current.id, new_start, now)
            updated = self._reload(current.id)
            result = ChangeResult(
                status="rescheduled",
                summary=f"Rescheduled to {rules.describe(updated.starts_at)}.",
                confirmation_code=updated.confirmation_code,
                appointment=_out(updated),
            )
            confirmations.record_outcome(
                self.repo.conn,
                token=req.confirmation_token,
                outcome=_outcome(result, updated),
            )
        self._log("reschedule_appointment", "rescheduled", f"appointment #{appointment.id}")
        return result

    def cancel(self, req: CancelRequest) -> ChangeResult:
        appointment = self._find(req.confirmation_code, req.patient_name)
        now = self.clock()
        fingerprint = confirmations.digest("cancel", {"appointment": appointment.id})

        if req.confirmation_token is None:
            self._require_booked(appointment)
            self._check_notice(appointment, now)
            token = self._issue_token("cancel", fingerprint, revision=appointment.revision)
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

        recorded = confirmations.stored_outcome(
            self.repo.conn,
            token=req.confirmation_token,
            operation="cancel",
            details_digest=fingerprint,
        )
        if recorded is not None:
            return self._replay(recorded)
        self._check_notice(appointment, now)

        with self.repo.write_transaction():
            current = self._reload(appointment.id)
            replay = confirmations.consume(
                self.repo.conn,
                token=req.confirmation_token,
                operation="cancel",
                details_digest=fingerprint,
                current_revision=current.revision,
                now=now,
            )
            if replay is not None:
                return self._replay(replay)
            self._require_booked(current)
            self.repo.set_status(current.id, "cancelled", now)
            updated = self._reload(current.id)
            result = ChangeResult(
                status="cancelled",
                summary="Your appointment has been cancelled.",
                confirmation_code=updated.confirmation_code,
                appointment=_out(updated, status="cancelled"),
            )
            confirmations.record_outcome(
                self.repo.conn,
                token=req.confirmation_token,
                outcome=_outcome(result, updated),
            )
        self._log("cancel_appointment", "cancelled", f"appointment #{appointment.id}")
        return result

    # --- helpers ------------------------------------------------------------

    def _issue_token(self, operation: str, fingerprint: str, *, revision: int) -> str:
        return confirmations.issue(
            self.repo.conn,
            operation=operation,
            details_digest=fingerprint,
            preview_revision=revision,
            now=self.clock(),
        )

    def _reload(self, appointment_id: int) -> Appointment:
        current = self.repo.get_by_id(appointment_id)
        if current is None:
            raise ApiError("not_found", "No appointment matches those details.", 404)
        return current

    def _require_booked(self, appointment: Appointment) -> None:
        if appointment.status != "booked":
            raise ApiError("already_cancelled", "This appointment is already cancelled.", 409)

    def _replay(self, recorded: dict[str, Any]) -> ChangeResult:
        """Answer a retry with the outcome it already produced, if nothing has changed since."""
        appointment = self.repo.get_by_id(int(recorded["appointment_id"]))
        if appointment is None or appointment.revision != recorded["revision"]:
            raise ApiError(
                "outcome_superseded",
                "This request already completed, and the booking has changed since. "
                "Check the current booking.",
                status_code=409,
            )
        return ChangeResult(
            status=recorded["status"],
            summary=recorded["summary"],
            confirmation_code=recorded["confirmation_code"],
            appointment=_out(appointment),
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
            # Changes inside the notice window are queued for the clinic, not made here.
            escalation = escalate(
                self.repo.conn,
                reason="change_too_late",
                channel=self.channel,
                clock=self.clock,
                appointment_id=appointment.id,
            )
            raise ApiError("change_too_late", escalation.message, status_code=409)

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


def _outcome(result: ChangeResult, appointment: Appointment) -> dict[str, Any]:
    """What a confirmed token did, recorded so a retry can be answered without writing."""
    return {
        "status": result.status,
        "summary": result.summary,
        "confirmation_code": result.confirmation_code,
        "appointment_id": appointment.id,
        "revision": appointment.revision,
    }


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
