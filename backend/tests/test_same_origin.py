"""Demo API writes from another site are refused. Same-origin and header-less calls still work."""

import dataclasses

from app.main import create_tools_app
from fastapi.testclient import TestClient

REQUEST_ID = "0" * 32
URL = f"/api/staff/requests/{REQUEST_ID}/status"
BODY = {"status": "resolved"}


def test_write_from_another_site_is_refused(client):
    response = client.post(URL, json=BODY, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_origin_request"


def test_write_with_null_origin_is_refused(client):
    # Sandboxed iframes and some redirects send the literal string "null".
    response = client.post(URL, json=BODY, headers={"Origin": "null"})
    assert response.status_code == 403


def test_write_from_the_same_origin_is_allowed(client):
    response = client.post(URL, json=BODY, headers={"Origin": "http://testserver"})
    # Allowed past the guard. The request id does not exist, so the route answers 404.
    assert response.status_code == 404


def test_write_without_an_origin_header_is_allowed(client):
    response = client.post(URL, json=BODY)
    assert response.status_code == 404


def test_reads_are_not_affected_by_a_foreign_origin(client):
    response = client.get("/api/staff/requests", headers={"Origin": "https://evil.example"})
    assert response.status_code == 200


def test_tools_app_is_not_guarded_by_origin(settings):
    configured = dataclasses.replace(settings, tool_shared_secret="test-secret-value-1234567890")
    with TestClient(create_tools_app(configured)) as tools:
        response = tools.post(
            "/tools/book-appointment",
            json={},
            headers={
                "Origin": "https://evil.example",
                "X-Tool-Secret": "test-secret-value-1234567890",
            },
        )
    # The tools app has its own secret check. It must not answer 403 for the origin alone.
    assert response.status_code != 403
