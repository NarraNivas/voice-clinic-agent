"""Runs evals/scenarios.json against the real app: one pytest case per scenario.

Method: each scenario is a sequence of HTTP calls or a single chat message. Placeholders such as
{tuesday} and {token} are filled in per run. Expected status, error code, route, and field values
are checked exactly, or as a substring for reply text.

A step with "caller_confirms": true is run the way a real caller is served: the runner sends the
request with no token (the preview), then sends the same body with the confirmation_token from
that preview. A raw "confirmed" key is never read by the API, so it is sent as-is in the
security scenarios.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import next_weekday

SCENARIOS_PATH = Path(__file__).resolve().parents[2] / "evals" / "scenarios.json"
SCENARIOS: list[dict[str, Any]] = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))[
    "scenarios"
]


def substitutions(state: dict[str, str]) -> dict[str, str]:
    return {
        "{tuesday}": next_weekday(1).isoformat(),
        "{sunday}": next_weekday(6).isoformat(),
        "{code}": state.get("code", ""),
        "{token}": state.get("token", ""),
        "{key}": "eval-key-0001",
    }


def fill(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        for placeholder, replacement in values.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, dict):
        return {key: fill(item, values) for key, item in value.items()}
    if isinstance(value, list):
        return [fill(item, values) for item in value]
    return value


def perform(client: TestClient, step: dict[str, Any], values: dict[str, str]):
    """Send one step. Expands caller_confirms into preview, then confirm with the token."""
    body = fill(step.get("body"), values)
    if body is not None and body.pop("caller_confirms", False):
        preview = client.request(step["method"], step["path"], json=body)
        data = preview.json()
        if preview.status_code != 200 or data.get("status") != "confirmation_required":
            # Errors, and replays that are already booked, are the result. Nothing to confirm.
            return preview
        body["confirmation_token"] = data["confirmation_token"]
    return client.request(step["method"], step["path"], json=body)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario(scenario: dict[str, Any], client) -> None:
    state: dict[str, str] = {}

    if scenario["type"] == "message":
        message = fill(scenario["message"], substitutions(state))
        body = client.post("/api/assistant/message", json={"message": message}).json()
        assert body["route"] == scenario["expect_route"], body
        if "expect_reply_contains" in scenario:
            assert scenario["expect_reply_contains"] in body["reply"], body
        return

    for step in scenario["steps"]:
        values = substitutions(state)
        response = perform(client, step, values)
        data = response.json()

        assert response.status_code == step["expect_status"], data
        if "expect_error" in step:
            assert data["error"]["code"] == step["expect_error"], data
        for key, expected in fill(step.get("expect", {}), substitutions(state)).items():
            assert data.get(key) == expected, (key, data)
        for variable, key in step.get("save", {}).items():
            state[variable] = data[key]
