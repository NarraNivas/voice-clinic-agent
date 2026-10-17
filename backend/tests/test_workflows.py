"""Curated workflow fixtures, run against the real app.

Each case is a synthetic regression fixture: it reproduces a failure class seen during live
testing and checks the outcome the server must produce. These are deterministic contract checks.
They do not measure the live voice agent, and they do not replay any recorded call.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import next_weekday
from tests.test_evals import fill, perform

WORKFLOWS_PATH = Path(__file__).resolve().parents[2] / "evals" / "workflows.json"
DATA = json.loads(WORKFLOWS_PATH.read_text(encoding="utf-8"))
WORKFLOWS: list[dict[str, Any]] = DATA["workflows"]


def values(state: dict[str, str]) -> dict[str, str]:
    base = {"{tuesday}": next_weekday(1).isoformat(), "{sunday}": next_weekday(6).isoformat()}
    base.update({"{" + key + "}": value for key, value in state.items()})
    return base


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=[w["id"] for w in WORKFLOWS])
def test_workflow(workflow, client):
    if workflow["type"] == "message":
        body = client.post("/api/assistant/message", json={"message": workflow["message"]}).json()
        assert body["route"] == workflow["expect_route"], body
        if "expect_reply_contains" in workflow:
            assert workflow["expect_reply_contains"] in body["reply"], body
        return

    state: dict[str, str] = {}
    for step in workflow["steps"]:
        response = perform(client, step, values(state))
        data = response.json()
        assert response.status_code == step["expect_status"], data
        if "expect_error" in step:
            assert data["error"]["code"] == step["expect_error"], data
        for key, expected in fill(step.get("expect", {}), values(state)).items():
            assert data.get(key) == expected, (key, data)
        for variable, key in step.get("save", {}).items():
            state[variable] = data[key]
