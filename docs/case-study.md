# Case study: a voice appointment assistant for a fictional clinic

**Audience:** engineers and hiring managers who want to see how an AI assistant can be built around hard limits rather than prompt instructions.

## The problem

A dental clinic's front desk handles repetitive requests: opening hours, booking, moving or cancelling appointments. Some requests should never reach an automated system, such as a medical question or an emergency. A voice agent that handles the easy cases well must also hand off the hard ones safely.

This project builds that workflow for a fictional clinic. It is a portfolio demo, not a product.

## Design decisions

**The backend owns the facts.** Availability is calculated on the server from opening hours, appointment lengths, and existing bookings. The language model can only offer times the server returned. This removes the most common failure of scheduling bots, which is a confident wrong time.

**Writes need a server-issued token from a preview.** Booking, rescheduling, and cancelling return a preview and a single-use token. The write happens only when the same details come back with that token. The token expires after five minutes. A flag in the request cannot write anything, so a model that skips the preview gets a preview back, not a booking.

**Safety is handled in code.** Emergency wording escalates with a 911 prompt. Medical questions are escalated, not answered. Changes inside 24 hours are escalated. A person can always ask for a human. These rules are tested with fixed inputs.

**Idempotency where retries are likely.** Each booking can carry an idempotency key. A retried request returns the original booking instead of creating a duplicate.

**Local first.** The demo page runs with no credentials, and the rules behave the same with or without voice. Voice is an optional layer that calls the same routes as the browser.

## What was built

- A FastAPI service with SQLite storage, and validation at every API boundary.
- Business rules in plain Python, separate from HTTP.
- A browser demo page with a text assistant, booking form, booking management, and an activity log.
- Seven tool routes for a voice agent, protected by a shared secret.
- 213 unit and API tests, and 31 scenario evaluations.
- A live check script that exercises the voice tools through a public URL.
- CI that runs lint and tests.

## How it was checked

- `pytest` runs 244 tests: 213 unit and API tests and 31 scenario evaluations. All pass on the last run.
- Connected to a real ElevenLabs agent, three of the first four voice calls failed to book. Each failure was traced through the server logs: an empty token, an error that did not say which field was wrong, and spoken-style times. After the fixes, a scripted check through the public URL passed 12 of 12. The details are in [live-testing.md](live-testing.md).
- The evaluation scenarios cover success, unavailable slots, invalid input, ambiguous requests, escalation, and medical questions. The method and results are in [evals/README.md](../evals/README.md).
- The demo page was loaded in a browser. The booking button ran with no console errors.
- These checks cover deterministic rules on fictional data. They do not measure how a live voice agent performs with real callers.

## Limits and what I would change next

- The demo text assistant uses keyword rules, not a language model. It is deliberately narrow.
- The keyword safety screen is a starting point. A real deployment needs clinical review and a much broader screen.
- The `/api/*` routes have no authentication and are meant for localhost only.
- Voice tools need a public URL. Deploying the service with proper authentication, and connecting it to a real scheduling system, are the next steps.
- A Salesforce or other CRM adapter would replace the SQLite repository. The services are already separated for this, but no adapter exists yet.

## Takeaway

For customer-facing automation, the useful work is deciding which decisions the model is allowed to make. Here the model may answer FAQs and collect details. The server decides what is available, what gets written, and when a person takes over.
