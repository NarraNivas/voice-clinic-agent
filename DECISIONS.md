# Decisions

Each entry records a choice, the alternatives, and the tradeoff.

## D1. Python 3.12 with FastAPI and SQLite
- Chosen because the brief asks for Python 3.11+ and FastAPI. Pydantic validation comes with FastAPI.
- SQLite via stdlib `sqlite3`. No ORM. The schema is small, and raw SQL keeps it easy to read.
- Tradeoff: no migrations framework. The schema is created with `CREATE TABLE IF NOT EXISTS` at startup, which is enough for a demo.

## D2. Plain HTML/CSS/JS frontend served by FastAPI
- No React or build step. One `index.html`, one `app.js`, and one `styles.css`.
- Tradeoff: less component structure. The demo page is small, so this is fine. Revisit if the UI grows.

## D3. Backend is authoritative for availability
- Slots are computed server-side from clinic rules and existing bookings. The voice agent or the browser can only choose from slots the backend returned.

## D4. Two-step writes with server-issued, single-use tokens
- Book, reschedule, and cancel return a preview and a `confirmation_token` unless a valid token is sent. The token is random, stored as a SHA-256 hash, expires after five minutes, is bound to the exact operation and details, and works once.
- The token is consumed inside the same transaction as the write, so a failed check rolls back the token use.
- An earlier version used a `confirmed: true` flag. A caller could send it without ever seeing a preview, so the flag was removed.

## D5. Confirmation code plus name for changes
- A confirmation code alone is treated as a weak secret. Reschedule and cancel also require a matching patient name (case-insensitive). This is a demo-level guard, not real authentication.

## D6. Idempotency via optional `idempotency_key`
- Booking with the same key and matching details returns the existing appointment without a new token. Keys are unique in the database. Clients should generate one per user request.
- A reused key with different details is rejected with `idempotency_conflict`.

## D7. Separate `/tools/*` routes behind a shared secret, and a tools-only app for tunnels
- ElevenLabs server tools call these routes with `X-Tool-Secret`. The browser demo uses `/api/*`.
- `/api/*` is unauthenticated and includes the activity log, so it must stay on localhost. A tunnel exposes whatever it forwards to, so the tunnel points only at `create_tools_app`, which serves `/tools/*` and nothing else.
- The secret is compared with `hmac.compare_digest`. If `TOOL_SHARED_SECRET` is unset, `/tools/*` returns 503 so it cannot be called open.

## D8. Rule-based demo router instead of an LLM
- The text box in the demo uses keyword rules for FAQ, medical screening, and escalation. It does not do free-form booking. This keeps the local demo free and deterministic.
- The real conversational path is the ElevenLabs agent, which is optional.

## D9. ElevenLabs widget is optional and embedded by public agent ID
- The widget needs a public agent with authentication disabled. The agent ID is not secret, but anyone who has it can start paid calls. The setup guide asks for an allowlist and a spend cap.
- Server tools need a publicly reachable URL, so cloud ElevenLabs cannot call `localhost` directly. Local testing needs a tunnel, which is a third-party service. Not enabled without approval.

## D10. No Docker in the first release
- Docker is not installed on the development machine, and the app has no service dependencies. A Dockerfile would add something that cannot be verified here. Revisit if deployment is requested.

## D11. Fictional clinic, not a real business
- Name, address, and phone numbers are invented. Phone numbers use the reserved 555 range.

## D12. Naive local clinic time
- All times are clinic-local with no timezone handling. The demo has one fictional location, so this is a documented simplification.

## D13. Interaction log without transcripts
- Interactions store the tool name, outcome, and a short summary. Full conversation transcripts are not stored, to keep the demo's data footprint small.

## D14. Logs and escalations keep outcomes and references, not personal details
- The activity log and the escalation table store outcomes, tool names, and numeric appointment ids (`appointment #12`). They never store patient names, confirmation codes, or caller free text.
- Escalations are recorded by reason only (`emergency`, `medical`, `human_request`, and so on). The escalation endpoint does not accept free text.
- Tradeoff: the front desk cannot see what the caller said in the log. That is intended. The reason and the appointment id are enough to find the booking.
