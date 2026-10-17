"""Escalation: records a staff request and queues its handoff to the CRM sandbox.

Nothing here notifies a person. A request is stored with its reason, queued in the outbox in the
same transaction, and delivered later by the outbox worker to a simulated CRM. Until the CRM
accepts it, the caller is told it is queued, never that it was delivered.
"""

import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.db import transaction
from app.repositories import log
from app.repositories import outbox as outbox_repo
from app.services import clinic_rules as rules

RECORDED_NOTE = (
    "The request is queued for a simulated clinic records system (a local sandbox). It is not "
    "delivered until that system accepts it. No staff member is notified here. "
    f"{rules.FRONT_DESK_PHONE} is a fictional number, not a live line."
)
REASON_MESSAGES: dict[str, str] = {
    "emergency": (
        "If this is an emergency, call 911 (or your local emergency number) now. "
        f"Do not wait for this assistant. {RECORDED_NOTE}"
    ),
    "medical": (
        "I can't give medical advice or diagnose problems. Please speak to a dentist or doctor. "
        f"Your question is for the clinic. {RECORDED_NOTE}"
    ),
    "human_request": f"Your request to speak to a person is recorded. {RECORDED_NOTE}",
    "unsupported": f"That is outside what this demo can do. {RECORDED_NOTE}",
    "ambiguous": f"I could not tell what you need, so the request is for review. {RECORDED_NOTE}",
    "change_too_late": (
        f"Changes need 24 hours' notice, so this one cannot be made here. {RECORDED_NOTE}"
    ),
}


@dataclass(frozen=True)
class Escalation:
    escalation_id: int
    request_id: str
    message: str
    delivery_state: str = "queued"


def escalate(
    conn: sqlite3.Connection,
    *,
    reason: str,
    channel: str,
    clock: Callable[[], datetime],
    appointment_id: int | None = None,
) -> Escalation:
    """Record the request, queue its handoff, and return what the caller should hear.

    The caller's own words are not stored. The reason and an appointment number are enough for
    the clinic to act on, and they keep medical and personal detail out of the database.
    """
    now = clock()
    request_id = secrets.token_hex(16)
    payload = {
        "category": reason,
        "reason": reason,
        "appointment_ref": f"APT-{appointment_id}" if appointment_id is not None else None,
    }
    with transaction(conn):
        outbox_repo.create_staff_request(
            conn,
            request_id=request_id,
            reason=reason,
            appointment_id=appointment_id,
            payload=payload,
            now=now,
        )
        escalation_id = log.record_escalation(conn, reason=reason, now=now)
        log.record_interaction(
            conn,
            channel=channel,
            tool_name="escalate_to_human",
            outcome="queued",
            summary=f"{reason} (#{escalation_id})",
            now=now,
        )
    return Escalation(
        escalation_id=escalation_id,
        request_id=request_id,
        message=REASON_MESSAGES.get(reason, REASON_MESSAGES["ambiguous"]),
    )
