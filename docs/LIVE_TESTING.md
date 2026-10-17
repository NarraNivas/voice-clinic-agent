# Live testing log

This page records what happened when the app was connected to a real ElevenLabs voice agent. It includes the failures. Every finding below came from server logs, not from guesses.

## Setup

- The tools-only app (`create_tools_app`) ran on `127.0.0.1:8001`.
- A Cloudflare Quick Tunnel exposed only that port over HTTPS. The demo app stayed on localhost.
- The ElevenLabs agent had seven webhook tools. Each sent the `X-Tool-Secret` header.
- Logs record the method, path, status code, and the names of any fields that failed validation. They never record field values, so no patient details appear in them.

## Voice calls, in order

Date: 2026-10-17. Each call was a short spoken conversation through the ElevenLabs widget.

| # | What the caller tried | What the server saw | Cause | Fix |
|---|---|---|---|---|
| 1 | Book a cleaning | Availability, preview, and confirm all returned 200. Lookup returned 200. | — | It worked. |
| 2 | Book a consultation | Availability returned 200. Then three `book-appointment` calls returned 422 before any preview was created. | The agent sent `"confirmation_token": ""` on its first call. The empty string failed the 20-character minimum. | Blank optional fields are treated as absent. |
| 3 | Book a consultation | One preview returned 200, then confirm calls returned 422. | Unknown at the time. The 422 message did not name the field, so neither the agent nor the log could tell. | Validation errors now name the field and the expected format, for example `start_time: use 24-hour HH:MM`. The log records field names only. |
| 4 | Book a consultation | Confirm calls returned 422. The log named `start_time` (4 times), `confirmation_token` (once, with `start_time`), `idempotency_key` (once), and `appointment_type` (once). | The agent sent spoken-style times, added an idempotency key of its own, and once sent an appointment type the schema did not accept. | Times such as `3:30 PM`, `3:30pm`, and `15:30:00` are converted to `15:30`. The voice tool route no longer takes an idempotency key, because the confirmation token already prevents duplicates. Appointment types are trimmed and lowercased, and a few aliases are mapped (`check-up` becomes `checkup`). |

What this showed: the server's rules were right, but its input handling was too strict for what a speech model sends. The hardest part was finding out which field failed. Naming it in the error fixed that, and the agent can now read the error and correct itself.

| 5 | Book a consultation for October 23rd at 3:30 | Confirm calls returned 422 for `start_time` (twice) and for `date`, `start_time`, and `appointment_type` (once). The agent then tried a lookup for an existing booking without a confirmation code, and the agent could not complete it. | The agent sent dates and times in spoken forms the schema rejected: `October 23rd` and `3:30` with no AM/PM. | Dates such as `October 23rd`, `23 October`, and `10/23` are accepted. Times such as `3:30`, `three thirty`, and `3:30 pm` are accepted. A bare hour from 1 to 6 means afternoon, because the clinic opens at 9. |

| 6 | Book a consultation for October 23rd at 3:30, then say yes | Confirm calls returned 422 for `start_time`, and once for `confirmation_token` with `start_time`. The agent said it needed "the exact confirmation token". | The time forms `3:30 PM`, `15:30 PM`, `3:30 in the afternoon`, and `3.30` still failed. The earlier fix only covered a fixed list of forms, which is why new forms kept appearing. | Time parsing now reads the hour, minute, and AM/PM or afternoon marker from any position in the text. Tests cover 30 forms. The live check passes. The token problem is not yet explained, see below. |

Call 6 shows that matching a fixed list of forms cannot keep up with speech. The parser now reads the hour and minute from anywhere in the text, rather than matching whole strings.

Open point after call 6: the agent says it needs the exact confirmation token. The server returns the token in the preview, and the live check confirms with it. So the token is either not reaching the agent in its tool result, or the agent is not passing it back. The agent-side test chat shows the tool results and can settle this.

Call 5 also exposed a design limit, not a bug. Lookup requires the confirmation code and the name, so a caller who has lost the code cannot be found by name alone. Changing that would weaken the lookup rule, so it is left as it is and noted as an open question.

## Browser journeys

After the voice fixes, the demo page was driven like a real person would use it, against the same database the voice agent uses. Each journey clicks through the page and reads what is on screen. Date: 2026-10-17, local time 02:45.

| Journey | Steps | Result |
|---|---|---|
| FAQ | Asked about Saturday opening | Answered from the clinic hours |
| Medical question | Asked whether to take ibuprofen for a tooth | No advice given. The wording at the time implied a handoff; corrected after review, it now says the demo records the request and notifies no one. |
| Emergency | Said "chest pain right now" | Told to call 911, then handed off |
| Booking | Checked times for a checkup on 2026-10-20, picked 10:00, reviewed the preview, confirmed | Booked with a confirmation code |
| Wrong name | Looked up the code with a different name | Refused: no appointment matches |
| Reschedule | Previewed a move from 10:00 to 14:00, confirmed | Moved, and the lookup shows 14:00 |
| Cancel | Previewed, confirmed | Cancelled |
| Voice booking | Looked up the appointment the voice agent booked | Found: consultation, 2026-10-23 at 15:30 |
| 24-hour rule | Booked a cleaning for today at 09:00, then tried to cancel | Refused: changes need 24 hours' notice. Recorded as a request, not notified. |

The only console error during the journeys was the expected 404 for the wrong-name lookup.

Test rows still in the database: a booking for "Notice Window Check" today at 09:00, and the cancelled "Browser Journey" booking. Both are fictional and can be removed.

## Scripted live check after the fixes

`scripts/live_check.py` sends the same requests the agent sends, through the public URL. It uses a blank token, a stray idempotency key, and a `3:30 PM`-style time.

```bash
set -a; . ./.env; set +a
backend/.venv/bin/python scripts/live_check.py https://<public-host>
```

Result on 2026-10-17, through the Cloudflare tunnel:

| Check | Result |
|---|---|
| Request with no secret | 401, pass |
| Request with a wrong secret | 401, pass |
| Demo API through the tunnel | 404, pass |
| FAQ answers hours | 200, pass |
| Availability returns real slots | 200, 15 slots, pass |
| Preview with blank token and spoken time | 200, token issued, pass |
| Confirm with the token | 200, booked, pass |
| Reusing the token | 409, no second booking, pass |
| Lookup by code and name | 200, pass |
| Cancel preview, then confirm | 200 and 200, pass |
| Medical escalation | 200, recorded with reason only, pass |

12 of 12 checks passed. The script booked one fictional appointment and cancelled it.

## Browser retry check

The demo page was tested with a simulated lost response. The first confirm reached the server, but its reply was dropped before the page saw it. The page kept the preview and offered "Try again". The retry returned the original booking ("already booked for this request"), and the database held exactly one row.

## Not verified yet

- **Lookup for a caller who has lost their code.** Not supported by design. See call 5.

- **A full voice booking after the fixes.** The scripted check proves the tools accept what the agent sent in calls 2 to 4. A new spoken conversation has not been run since then.
- **Speech recognition quality.** In call 3 the agent heard "12:30" when the caller said "2:30". That is outside the server. The agent's read-back of the preview is the safeguard: the caller hears the time before saying yes.
- **Load, uptime, and long-running stability.** The tunnel is temporary and runs from a laptop.
