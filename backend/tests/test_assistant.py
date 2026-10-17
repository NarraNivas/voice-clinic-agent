"""FAQ matching, safety screening, and the demo text router. Medical text escalates."""

from app.repositories.appointments import AppointmentRepository
from app.services.assistant import route_message
from app.services.faq import match_faq
from app.services.safety import screen

from tests.conftest import FIXED_NOW


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- FAQ ----------------------------------------------------------------


def test_faq_answers_hours():
    assert match_faq("What time do you open on Saturdays?").topic == "hours"


def test_faq_answers_location_and_parking():
    assert match_faq("Where are you and is there parking?").topic == "location"


def test_faq_answers_cancellation_policy():
    assert match_faq("What is your cancellation policy?").topic == "cancellation_policy"


def test_faq_says_it_is_a_demo():
    assert match_faq("Is this real or are you a robot?").topic == "about_this_demo"


def test_faq_returns_none_when_nothing_matches():
    assert match_faq("Can you write me a poem about bicycles") is None


# --- safety screening ---------------------------------------------------


def test_emergency_wording_is_detected():
    assert screen("I have chest pain right now").kind == "emergency"


def test_medical_question_is_detected():
    assert screen("My gums are bleeding after brushing").kind == "medical"


def test_medication_question_is_detected():
    assert screen("Should I take ibuprofen for this?").kind == "medical"


def test_request_for_a_person_is_detected():
    assert screen("Can I talk to a real person please").kind == "human_request"


def test_ordinary_scheduling_question_is_not_flagged():
    assert screen("What are your hours?").kind == "none"


# --- router -------------------------------------------------------------


def route(text, conn):
    return route_message(text, repo=AppointmentRepository(conn), clock=lambda: FIXED_NOW)


def test_emergency_escalates_and_points_to_911(conn):
    result = route("I think I have chest pain", conn)
    assert result.route == "escalate_emergency"
    assert "911" in result.reply
    assert count(conn, "escalations") == 1


def test_medical_question_escalates_without_answering(conn):
    result = route("Is it normal for my tooth to hurt this much?", conn)
    assert result.route == "escalate_medical"
    assert "can't give medical advice" in result.reply
    assert count(conn, "escalations") == 1


def test_faq_question_is_answered_without_escalation(conn):
    result = route("What are your hours?", conn)
    assert result.route == "faq"
    assert "Monday to Friday" in result.reply
    assert count(conn, "escalations") == 0


def test_availability_with_date_and_type_returns_real_slots(conn):
    result = route("Any cleaning times on 2026-10-13?", conn)
    assert result.route == "availability"
    assert result.data["slots"][0] == "09:00"


def test_date_without_type_asks_which_type(conn):
    result = route("Anything open on 2026-10-13?", conn)
    assert result.route == "ask_appointment_type"


def test_booking_request_is_redirected_and_writes_nothing(conn):
    result = route("Book me a cleaning on 2026-10-13", conn)
    assert result.route == "use_booking_form"
    assert count(conn, "appointments") == 0


def test_unclear_message_asks_for_rephrase_without_escalating(conn):
    result = route("blah blah blah", conn)
    assert result.route == "clarify"
    assert count(conn, "escalations") == 0


def test_explicit_request_for_a_person_escalates(conn):
    result = route("Let me speak to someone", conn)
    assert result.route == "escalate_human"
    assert count(conn, "escalations") == 1
