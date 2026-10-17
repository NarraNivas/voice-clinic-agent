"""Escalation wording must be true. This demo records requests and notifies nobody.

These tests stop a future edit from claiming a person was contacted when nothing was sent.
"""

import pytest
from app.services.escalation import REASON_MESSAGES

FALSE_CLAIMS = [
    "i've asked a team member",
    "i've passed",
    "will follow up",
    "team member will",
    "has been notified",
    "someone will call",
    "a person will call",
    "we will call",
]


@pytest.mark.parametrize("reason", sorted(REASON_MESSAGES))
def test_no_message_claims_a_notification_was_sent(reason):
    text = REASON_MESSAGES[reason].lower()
    for claim in FALSE_CLAIMS:
        assert claim not in text, f"{reason!r} claims: {claim!r}"


@pytest.mark.parametrize("reason", sorted(REASON_MESSAGES))
def test_every_message_says_the_demo_records_or_no_one_is_notified(reason):
    text = REASON_MESSAGES[reason].lower()
    assert (
        "records" in text or "no staff member is notified" in text or "cannot be made here" in text
    )


def test_emergency_message_gives_direct_guidance():
    text = REASON_MESSAGES["emergency"]
    assert "911" in text
    assert "contacts no one" in text or "does not contact" in text.lower()


def test_medical_message_does_not_give_advice():
    assert "can't give medical advice" in REASON_MESSAGES["medical"].lower()


def test_fictional_number_is_identified_as_not_live():
    assert "not a live line" in REASON_MESSAGES["human_request"]
