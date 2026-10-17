# Evaluation scenarios

`scenarios.json` holds 31 scenarios that run against the real FastAPI app and SQLite database. They are run by `backend/tests/test_evals.py`, which creates one pytest case per scenario.

## Coverage

| Category | Scenarios | What is checked |
|---|---|---|
| success | 5 | FAQ answers, availability via chat, book preview then confirm, reschedule, cancel |
| unavailable | 3 | Slot already taken, consultation overlapping a cleaning, Sunday closed |
| invalid_input | 6 | Bad time format, off-grid time, unknown type, name too short, malformed code, wrong name on cancel |
| idempotency | 1 | Same key returns the same booking |
| security | 4 | A bare `confirmed` flag writes nothing, a forged token is rejected, a token is single-use, a token is bound to its exact details |
| robustness | 1 | A blank optional token, as a voice agent sends it, returns a preview |
| ambiguous | 4 | Gibberish, date without type, unrelated request, booking words redirect to the form |
| escalation | 2 | Emergency wording, explicit request for a person |
| medical | 3 | Symptom, medication, treatment advice are escalated and not answered |

## Method

- Each scenario is a single chat message (`type: message`) or a sequence of HTTP calls (`type: api`).
- A step with `"caller_confirms": true` is run the way a real caller is served. The runner sends the request with no token (the preview), then sends it again with the `confirmation_token` from that preview. Steps that use a raw `"confirmed"` key send it unchanged, because the API ignores that key. The security scenarios rely on this.
- Placeholders are filled per run: `{tuesday}` and `{sunday}` are real upcoming dates, so bookings stay inside the booking window. `{code}` is the confirmation code saved from an earlier step.
- Checks are exact for status codes, error codes, routes, and field values. Reply text is checked as a substring.
- Each test gets a fresh temporary SQLite file. Scenarios do not share state.
- Dates are relative to the real clock. Scenarios that would only pass at certain times of day (for example, a change inside the 24-hour notice window) are covered by unit tests with a fixed clock, not here.

## Running

```bash
cd backend
pytest tests/test_evals.py -v
```

## Results

Measured on 2026-10-17 (macOS 26.3, Python 3.12.5, pytest 9.1.1), one run:

- `tests/test_evals.py`: 31 passed, 0 failed.
- Whole backend suite: 193 passed, 0 failed (162 unit and API tests plus 31 evals).

These scenarios run against the app in-process. Results from the live voice agent are recorded separately in [docs/live-testing.md](../docs/live-testing.md), including the calls that failed.

These numbers come from a deterministic rule set on a fictional dataset. They show the rules do what they say. They do not measure how well a live voice agent performs with real callers, and they say nothing about the ElevenLabs model.

## Adding a scenario

1. Add an object to `scenarios.json` with a unique `id`, a `category`, and either `message` + `expect_route` or `steps`.
2. Run `pytest tests/test_evals.py -v`.
3. Record any new result in the table above.
