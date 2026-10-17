"""HTTP tests for FAQ, assistant, escalation, and interaction log routes."""


def test_faq_endpoint_answers(client):
    body = client.post("/api/faq", json={"question": "Where is parking?"}).json()
    assert body["answered"] is True
    assert body["topic"] == "location"


def test_faq_endpoint_admits_when_it_does_not_know(client):
    body = client.post("/api/faq", json={"question": "Write a sonnet about bicycles"}).json()
    assert body["answered"] is False
    assert body["answer"] is None


def test_message_endpoint_escalates_medical_text(client):
    body = client.post("/api/assistant/message", json={"message": "I have severe swelling"}).json()
    assert body["route"] == "escalate_medical"
    assert "555-0100" in body["reply"]


def test_message_endpoint_rejects_empty_input(client):
    response = client.post("/api/assistant/message", json={"message": ""})
    assert response.status_code == 422


def test_explicit_escalation_endpoint(client):
    body = client.post(
        "/api/escalations", json={"reason": "human_request", "summary": "wants a callback"}
    ).json()
    assert body["escalation_id"] >= 1
    assert body["front_desk_phone"] == "555-0100"


def test_unknown_escalation_reason_is_rejected(client):
    response = client.post("/api/escalations", json={"reason": "just because"})
    assert response.status_code == 422


def test_interaction_log_shows_recent_actions(client):
    client.post("/api/faq", json={"question": "hours"})
    client.post("/api/escalations", json={"reason": "ambiguous"})
    items = client.get("/api/interactions").json()["items"]
    tools = {item["tool_name"] for item in items}
    assert "escalate_to_human" in tools
