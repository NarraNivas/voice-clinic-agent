"""Live check of the voice tools through a public URL, using the same calls a voice agent makes.

Usage, from the repo root:
    set -a; . ./.env; set +a
    backend/.venv/bin/python scripts/live_check.py https://<your-public-host>

It reads TOOL_SHARED_SECRET from the environment and never prints it or any confirmation token.
It books one fictional appointment ("Live Check") and then cancels it. Standard library only.
Exit code 0 means every check passed.
"""

import datetime as dt
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

PATIENT = "Live Check"


def post(base: str, path: str, body: dict, secret: str | None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Tool-Secret"] = secret
    request = urllib.request.Request(
        base + path, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    return _send(request)


def get(base: str, path: str) -> tuple[int, dict]:
    return _send(urllib.request.Request(base + path, method="GET"))


def _tls_context() -> ssl.SSLContext:
    """Verify HTTPS with certifi's CA bundle when available. Some macOS Python builds ship
    without system certificates; verification is never turned off."""
    try:
        import certifi  # noqa: PLC0415  (optional dependency, imported only when present)

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


TLS = _tls_context()


def _send(request: urllib.request.Request) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(request, timeout=20, context=TLS) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except json.JSONDecodeError:
            return error.code, {}


def next_tuesday(min_days: int = 3) -> str:
    day = dt.date.today() + dt.timedelta(days=min_days)
    while day.weekday() != 1:
        day += dt.timedelta(days=1)
    return day.isoformat()


def spoken(hhmm: str) -> str:
    """'15:30' -> '3:30 PM', the way an agent often sends a time."""
    hour, minute = map(int, hhmm.split(":"))
    return f"{(hour % 12) or 12}:{minute:02d} {'PM' if hour >= 12 else 'AM'}"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    base = sys.argv[1].rstrip("/")
    secret = os.environ.get("TOOL_SHARED_SECRET")
    if not secret:
        print("TOOL_SHARED_SECRET is not set. Load .env first: set -a; . ./.env; set +a")
        return 2

    results: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        results.append((name, passed, detail))

    faq = {"question": "What are your hours?"}

    status, _ = post(base, "/tools/answer-faq", faq, None)
    check("no secret is rejected", status == 401, f"HTTP {status}")

    status, _ = post(base, "/tools/answer-faq", faq, "wrong-secret-value")
    check("wrong secret is rejected", status == 401, f"HTTP {status}")

    status, _ = get(base, "/api/interactions")
    check("demo API is not exposed", status == 404, f"HTTP {status}")

    status, body = post(base, "/tools/answer-faq", faq, secret)
    check("FAQ answers hours", status == 200 and body.get("topic") == "hours", f"HTTP {status}")

    day = next_tuesday()
    status, body = post(
        base,
        "/tools/check-availability",
        {"date": day, "appointment_type": "consultation"},
        secret,
    )
    slots = body.get("slots", [])
    check("availability returns real slots", status == 200 and bool(slots), f"{len(slots)} slots")
    if not slots:
        return report(results)
    slot = slots[-1]

    # First call, as the agent sends it: blank token, a key of its own, and a spoken-style time.
    booking = {
        "patient_name": PATIENT,
        "appointment_type": "consultation",
        "date": day,
        "start_time": spoken(slot),
    }
    status, body = post(
        base,
        "/tools/book-appointment",
        {**booking, "confirmation_token": "", "idempotency_key": "req1"},
        secret,
    )
    token = body.get("confirmation_token") or ""
    check(
        "preview with blank token and spoken time",
        status == 200 and body.get("status") == "confirmation_required" and len(token) >= 20,
        f"HTTP {status}, token length {len(token)}",
    )

    status, body = post(
        base, "/tools/book-appointment", {**booking, "confirmation_token": token}, secret
    )
    code = body.get("confirmation_code") or ""
    check(
        "confirm with token books",
        status == 200 and body.get("status") == "booked",
        f"HTTP {status}",
    )

    status, body = post(
        base, "/tools/book-appointment", {**booking, "confirmation_token": token}, secret
    )
    check(
        "reusing the token does not book twice",
        status == 409,
        f"HTTP {status} {body.get('error', {}).get('code', '')}",
    )

    status, body = post(
        base,
        "/tools/lookup-appointment",
        {"confirmation_code": code, "patient_name": PATIENT},
        secret,
    )
    check(
        "lookup by code and name",
        status == 200 and body.get("status") == "booked",
        f"HTTP {status}",
    )

    cancel = {"confirmation_code": code, "patient_name": PATIENT}
    status, body = post(
        base, "/tools/cancel-appointment", {**cancel, "confirmation_token": ""}, secret
    )
    cancel_token = body.get("confirmation_token") or ""
    check(
        "cancel preview",
        status == 200 and body.get("status") == "confirmation_required",
        f"HTTP {status}",
    )

    status, body = post(
        base, "/tools/cancel-appointment", {**cancel, "confirmation_token": cancel_token}, secret
    )
    check("cancel confirm", status == 200 and body.get("status") == "cancelled", f"HTTP {status}")

    status, body = post(base, "/tools/escalate-to-human", {"reason": "medical"}, secret)
    check(
        "medical escalation",
        status == 200 and body.get("front_desk_phone") == "555-0100",
        f"HTTP {status}",
    )

    return report(results)


def report(results: list[tuple[str, bool, str]]) -> int:
    width = max(len(name) for name, _, _ in results)
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = sum(1 for _, passed, _ in results if not passed)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
