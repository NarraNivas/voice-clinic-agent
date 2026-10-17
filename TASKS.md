# Tasks

## Milestone A — Skeleton, config, data model, API contract
- [x] Detect environment (macOS 26.3, Python 3.12.5, Node 22.22.1, Git 2.50.1, Docker not installed)
- [x] Project docs: PROJECT_SPEC.md, DECISIONS.md, TASKS.md
- [x] Pinned backend dependencies (`backend/requirements*.txt`)
- [x] Config module
- [x] SQLite schema and repository
- [x] Pydantic request and response models

## Milestone B — Availability API, validation, rules, tests
- [x] Pure slot calculation (hours, grid, overlaps, booking window, past times)
- [x] Availability endpoint
- [x] Book endpoint (preview, confirm, idempotency, overlap rejection)
- [x] Reschedule and cancel (name + code match, 24h notice rule)
- [x] Lookup endpoint
- [x] Unit and API tests for business rules and failure paths

## Milestone C — FAQ knowledge base and escalation
- [x] FAQ data file (fictional)
- [x] FAQ matcher with an explicit no-match result
- [x] Medical and emergency screening
- [x] Escalation service and endpoint
- [x] Tests for medical, emergency, out-of-scope, and ambiguous input

## Milestone D — Frontend demo page
- [x] `index.html`, `styles.css`, `app.js` (text assistant, booking form, manage booking, interaction log)
- [x] Fictional banner and visible booking results
- [x] ElevenLabs widget section with a fallback when no agent ID is configured
- [x] Served by FastAPI at `/`

## Milestone E — ElevenLabs tool integration
- [x] `/tools/*` routes with `X-Tool-Secret` validation
- [x] Tests for missing and wrong secrets, and for the unconfigured state
- [x] Setup guide: `docs/elevenlabs-setup.md` (manual steps, tool definitions, allowlist, spend cap)

## Milestone F — Evaluation scenarios
- [x] `evals/scenarios.json` covering success, unavailable slots, invalid input, ambiguity, escalation, and medical questions
- [x] Runner test that reports pass/fail per scenario
- [x] `evals/README.md` with method and results

## Milestone G — Docs and CI
- [x] `README.md` (setup, demo workflow, tests, cost notes, limitations)
- [x] Architecture notes and a mermaid diagram
- [x] `docs/case-study.md` and `docs/demo-recording.md`
- [x] `.gitignore`
- [x] `.github/workflows/ci.yml` (install, ruff, pytest)

## Milestone H — Final verification
- [x] Run `pytest` and `ruff check`, fix failures
- [x] Start the server and check the demo page in a browser
- [x] Inspect the diff
- [x] Report exact run and demo commands

## Milestone I — Live integration hardening
- [x] Tools-only app for the tunnel, confirmation tokens, privacy-safe logs
- [x] Blank optional fields treated as absent
- [x] Validation errors name the field and the expected format; logs record field names only
- [x] Spoken-style times and appointment types accepted; voice route ignores idempotency keys
- [x] Demo page retry keeps the preview and reuses the idempotency key
- [x] `scripts/live_check.py` passes 12/12 through the public URL
- [ ] A full spoken booking after the fixes (needs a person on the call)
- [ ] Permanent public URL (needs an account choice)

