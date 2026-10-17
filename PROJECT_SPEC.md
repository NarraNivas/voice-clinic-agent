# Project Spec — Voice Clinic Agent

A portfolio demo of a browser-based voice appointment assistant for a **fictional** dental clinic, "Maple Street Dental (Fictional Demo)".

## Goals

- Answer FAQ questions from a small fictional knowledge base.
- Check availability, book, reschedule, and cancel fictional appointments.
- Confirm details before any change.
- Escalate ambiguous, unsupported, or sensitive requests to a human.
- Log outcomes in a local SQLite database.
- Never give medical advice.

Non-goals for the first release: telephony, real patient data, accounts, payments, production deployment, Salesforce.

## Architecture

```mermaid
flowchart LR
    Browser[Demo page<br/>frontend/] -->|/api/*| API[FastAPI app]
    Widget[ElevenLabs widget<br/>optional] -->|voice| EL[ElevenAgents cloud]
    EL -->|server tools<br/>X-Tool-Secret| Tools[/tools/* routes]
    API --> Services[Services<br/>rules, FAQ, escalation]
    Tools --> Services
    Services --> Repo[Repository]
    Repo --> DB[(SQLite)]
```

Layers:

- `api/`: HTTP routes and auth dependency. Thin; no business rules.
- `services/`: business rules (slots, booking, escalation, FAQ, safety screening). Pure logic where possible.
- `repositories/`: SQL only.
- `models/`: Pydantic request and response schemas.
- `data/`: FAQ content and clinic constants.

Future CRM adapter: services depend on a repository interface, so a Salesforce-backed repository could replace SQLite later. This is designed for, not built.

## Clinic rules

- Hours: Mon–Fri 09:00–17:00, Sat 09:00–13:00, Sun closed (clinic-local time, no timezone conversion).
- Slot grid: every 30 minutes, starting on the hour or half-hour.
- Appointment types and durations: `cleaning` 30 min, `checkup` 30 min, `consultation` 60 min.
- One chair: active bookings may not overlap.
- Booking window: today through 60 days ahead. No bookings in the past.
- Changes (reschedule or cancel) need at least 24 hours' notice. Inside that window, the change is refused and the request is recorded for the clinic. Nothing is sent to staff.
- A booking is identified by a confirmation code (`MSD-XXXXXX`). Reschedule and cancel also require the patient name to match, so a code alone is not enough.

## User workflows

1. **FAQ**: "What are your hours?" → answer from FAQ. Unknown → say so and offer to record a request.
2. **Availability**: date and type → backend returns open slots only.
3. **Book**: collect name, type, date, time → preview with confirmation summary and token → on explicit yes, resend the same details with the token → code returned.
4. **Reschedule**: code + name + new slot → preview → confirm → updated.
5. **Cancel**: code + name → preview → confirm → cancelled.
6. **Escalate**: medical question, emergency wording, out-of-scope, ambiguous, or too-close-to-change → escalation record (reason only) and a message saying the demo records the request and notifies no one.

Emergency wording (for example, "chest pain", "can't breathe", "severe bleeding") → tell the caller to call emergency services (911 in the US), then escalate. Do not diagnose.

## API contract (summary)

All responses are JSON. Errors: `{"error": {"code": str, "message": str}}`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness and config flags (no secrets) |
| GET | `/api/clinic` | Fictional clinic info, types, and FAQ topics |
| POST | `/api/availability` | Open slots for a date and type |
| POST | `/api/appointments` | Book (preview with a token, then confirm with the token) |
| POST | `/api/appointments/lookup` | Look up a booking (POST so names stay out of URLs and logs) |
| POST | `/api/appointments/reschedule` | Reschedule (preview with a token, then confirm) |
| POST | `/api/appointments/cancel` | Cancel (preview with a token, then confirm) |
| POST | `/api/faq` | Answer a FAQ question or return no match |
| POST | `/api/assistant/message` | Demo-mode text router (no LLM) |
| POST | `/api/escalations` | Create an escalation for a human |
| GET | `/api/interactions` | Recent interaction log (demo) |
| POST | `/tools/check-availability`, `/book-appointment`, `/lookup-appointment`, `/reschedule-appointment`, `/cancel-appointment`, `/answer-faq`, `/escalate-to-human` | Same operations for ElevenLabs server tools. Requires `X-Tool-Secret`; 503 if unset. |

Preview response: `{"status": "confirmation_required", "summary": "...", "confirmation_code": null, "confirmation_token": "..."}`.
Confirm by sending the same body with `confirmation_token` set. Success: `{"status": "booked", "confirmation_code": "MSD-...", "summary": "...", "appointment": {...}}`.
Tokens are single-use, bound to the exact operation and details, and expire after five minutes. A bad, reused, or expired token returns `409` (`invalid_confirmation` or `confirmation_expired`).

## Acceptance criteria

- A new developer can clone, follow the README, and run the app with no credentials.
- The demo page works without an ElevenLabs key and shows visible booking results.
- `pytest` and `ruff check` pass locally and in CI.
- Booking, rescheduling, and cancelling never happen without a valid single-use token from a preview of the same details.
- Overlapping and closed-hour bookings are rejected with clear errors.
- Repeated booking with the same `idempotency_key` returns the same appointment.
- Tool endpoints reject missing or wrong `X-Tool-Secret` values.
- The tools-only app (`create_tools_app`) serves no `/api` routes and no pages, so it is the only app to tunnel.
- Logs and escalations contain no patient names, confirmation codes, or caller free text.
- Medical and emergency inputs are escalated, not answered.
- Error responses contain no stack traces.
