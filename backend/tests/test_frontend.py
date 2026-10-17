"""The demo page is served by the app and has no leftover ElevenLabs script when unconfigured."""

import dataclasses

from app.config import FRONTEND_DIR
from app.main import create_app
from fastapi.testclient import TestClient


def frontend_client(settings, **overrides) -> TestClient:
    configured = dataclasses.replace(settings, frontend_dir=FRONTEND_DIR, **overrides)
    return TestClient(create_app(configured))


def test_root_serves_the_demo_page(settings):
    with frontend_client(settings) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Voice Clinic Agent Demo" in response.text
        assert "AI demo" in response.text


def test_static_script_is_served(settings):
    with frontend_client(settings) as client:
        response = client.get("/app.js")
        assert response.status_code == 200
        # Server text must go through textContent, never an innerHTML assignment.
        assert ".innerHTML =" not in response.text


def test_widget_element_is_not_rendered_without_agent_id(settings):
    with frontend_client(settings) as client:
        assert client.get("/api/health").json()["elevenlabs_widget_configured"] is False
        assert "elevenlabs-convai" not in client.get("/").text
