"""Escalation: records a request for a human. This demo sends no notifications."""

import sqlite3
from collections.abc import Callable
from datetime import datetime

from app.repositories import log
from app.services import clinic_rules as rules

# What the caller is told. Every message says what this demo actually does: it records the
# request in its own database. Nothing is sent to staff, and no call is placed.
RECORDED_NOTE = (
    f"This demo records the request ({rules.FRONT_DESK_PHONE} is a fictional number, "
    "not a live line). No staff member is notified here."
)
REASON_MESSAGES: dict[str, str] = {
    "emergency": (
        "If this is an emergency, call 911 (or your local emergency number) now. "
        "Do not wait for this assistant. This demo records the report but contacts no one."
    ),
    "medical": (
        "I can't give medical advice or diagnose problems. Please speak to a dentist or doctor. "
        f"This demo records the question for the clinic. {RECORDED_NOTE}"
    ),
    "human_request": (f"This demo records your request to speak to a person. {RECORDED_NOTE}"),
    "unsupported": (
        f"That is outside what this demo can do. This demo records the request. {RECORDED_NOTE}"
    ),
    "ambiguous": (
        f"I could not tell what you need. This demo records the request for review. {RECORDED_NOTE}"
    ),
    "change_too_late": (
        "Changes need 24 hours' notice, so this one cannot be made here. "
        f"This demo records the request for the clinic. {RECORDED_NOTE}"
    ),
}


def escalate(
    conn: sqlite3.Connection,
    *,
    reason: str,
    channel: str,
    clock: Callable[[], datetime],
) -> tuple[int, str]:
    """Record an escalation by reason and return (escalation_id, message for the caller).

    The caller's own words are not stored. The reason is enough for the clinic to
    decide what to do next, and it keeps medical and personal detail out of the database.
    """
    now = clock()
    escalation_id = log.record_escalation(conn, reason=reason, now=now)
    log.record_interaction(
        conn,
        channel=channel,
        tool_name="escalate_to_human",
        outcome="escalated",
        summary=f"{reason} (#{escalation_id})",
        now=now,
    )
    return escalation_id, REASON_MESSAGES.get(reason, REASON_MESSAGES["ambiguous"])
