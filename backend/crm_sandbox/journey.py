"""The recovery journey, run end to end against two local HTTP services.

    cd backend && .venv/bin/python -m crm_sandbox.journey

It starts the clinic demo app and the CRM sandbox on free localhost ports, using temporary
databases that are removed afterwards. Nothing here reads or changes your demo database.

Steps:
1. Book a cleaning, using the preview-then-confirm flow.
2. Ask to cancel it inside the 24-hour notice window. The request is queued for the clinic.
3. Make the CRM sandbox fail twice. The outbox shows the handoff as queued, with retries.
4. Restore the sandbox. Make it save the case but lose the response once.
5. Run the worker until the handoff is delivered. Check that the sandbox holds exactly one case.

The worker runs on a fake clock, so the backoff steps happen instantly.
"""

import json
import shutil
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db import connect
from app.main import create_app
from app.services.outbox import HttpCrmClient, deliver_due

from crm_sandbox.app import create_crm_app
from crm_sandbox.serving import serve


def _next_monday(min_days_ahead: int = 2) -> date:
    day = date.today() + timedelta(days=min_days_ahead)
    while day.weekday() != 0:
        day += timedelta(days=1)
    return day


def _call(method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def _states(clinic_url: str) -> dict[str, Any]:
    _, body = _call("GET", f"{clinic_url}/api/outbox")
    return body


def run(*, verbose: bool = True) -> dict[str, Any]:
    """Run the journey and return what happened, so a test can check it."""
    workdir = Path(tempfile.mkdtemp(prefix="clinic-journey-"))
    clinic_db = workdir / "clinic.db"
    crm_db = workdir / "crm.db"
    monday = _next_monday()
    now = datetime.combine(monday, datetime.min.time()).replace(hour=8)
    report: dict[str, Any] = {"steps": []}

    def say(text: str) -> None:
        report["steps"].append(text)
        if verbose:
            print(text)

    settings = Settings(
        database_path=clinic_db,
        tool_shared_secret=None,
        elevenlabs_agent_id=None,
        frontend_dir=workdir / "no-frontend",
    )
    clinic_app = create_app(settings, clock=lambda: now)
    crm_app = create_crm_app(crm_db, faults_enabled=True)

    try:
        with serve(crm_app) as crm, serve(clinic_app) as clinic:
            say(f"clinic demo on {clinic.base_url}, CRM sandbox on {crm.base_url} (localhost only)")

            # 1. Book, with the preview first.
            booking = {
                "patient_name": "Journey Caller",
                "appointment_type": "cleaning",
                "date": monday.isoformat(),
                "start_time": "10:00",
            }
            _, preview = _call("POST", f"{clinic.base_url}/api/appointments", booking)
            _, booked = _call(
                "POST",
                f"{clinic.base_url}/api/appointments",
                {**booking, "confirmation_token": preview["confirmation_token"]},
            )
            code = booked["confirmation_code"]
            say(f"1. booked {code} after a preview and a confirm (status: {booked['status']})")

            # 2. A change inside the notice window is refused and queued, not made.
            status, refused = _call(
                "POST",
                f"{clinic.base_url}/api/appointments/cancel",
                {"confirmation_code": code, "patient_name": "Journey Caller"},
            )
            report["refusal_message"] = refused["error"]["message"]
            say(f"2. late cancel refused with HTTP {status}: {refused['error']['code']}")
            say(f"   the caller is told: {refused['error']['message']}")

            queued = _states(clinic.base_url)
            say(f"   outbox after the refusal: {queued['counts']}")

            # 3. The CRM fails twice. The worker retries with backoff, on a fake clock.
            _call("POST", f"{crm.base_url}/admin/faults", {"fail_next": 2})
            worker = HttpCrmClient(crm.base_url)
            clinic_conn = connect(clinic_db)
            try:
                first = deliver_due(clinic_conn, worker, now=now)
                say(f"3. worker attempt 1 with the CRM down: {[d.outcome for d in first]}")
                second = deliver_due(clinic_conn, worker, now=now + timedelta(seconds=30))
                say(f"   worker attempt 2 at +30s: {[d.outcome for d in second]}")
                say(f"   outbox shows: {_states(clinic.base_url)['counts']}")

                # 4. The CRM is back, but the next save loses its response after committing.
                _call(
                    "POST",
                    f"{crm.base_url}/admin/faults",
                    {"fail_next": 0, "lose_response_next": 1},
                )
                third = deliver_due(clinic_conn, worker, now=now + timedelta(seconds=90))
                say(
                    "4. CRM restored; the next save is lost after commit: "
                    f"{[d.outcome for d in third]}"
                )

                # 5. The worker retries. The CRM recognises the request and returns the same case.
                fourth = deliver_due(clinic_conn, worker, now=now + timedelta(seconds=210))
                say(f"5. worker attempt 4: {[d.outcome for d in fourth]}")
            finally:
                clinic_conn.close()

            _, cases = _call("GET", f"{crm.base_url}/cases")
            final = _states(clinic.base_url)
            report.update(
                {
                    "confirmation_code": code,
                    "cases_in_crm": cases["count"],
                    "case_refs": [item["case_ref"] for item in cases["items"]],
                    "final_counts": final["counts"],
                    "attempts": [d.attempts for d in fourth],
                    "outcomes": [d.outcome for d in (first + second + third + fourth)],
                }
            )
            say(
                f"result: {cases['count']} case in the CRM "
                f"({', '.join(report['case_refs'])}), outbox {final['counts']}"
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return report


def main() -> int:
    report = run(verbose=True)
    delivered = report["final_counts"]["delivered"]
    ok = report["cases_in_crm"] == 1 and delivered == 1
    print("PASS: one case, delivered exactly once." if ok else "FAIL: see the steps above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
