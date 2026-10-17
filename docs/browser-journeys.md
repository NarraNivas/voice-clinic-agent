# Browser journeys

These checks were run on 2026-10-17 with a browser tool, against the seeded demo database and the local CRM sandbox. Both services ran on localhost ports separate from the main demo, and the database was reset afterwards. No live voice call was made, and no ElevenLabs service was used.

| # | Journey | What was checked | Result |
|---|---|---|---|
| 1 | Booking, preview first | A checkup was previewed on a Thursday at 10:00 before anything was written. The preview said what would be booked. | Passed. The preview came before any write. |
| 2 | Confirm | Confirming the preview produced a booking and a confirmation code. | Passed. Status: booked. |
| 3 | Lookup | The code and name found the booking, with its start time and status. | Passed. |
| 4 | Reschedule | A move to 15:00 was previewed, confirmed, and reflected on screen. | Passed. The record showed 15:00 after the move. |
| 5 | Cancel | A cancellation was previewed, confirmed, and reflected on screen. | Passed. The record showed "Cancelled" and the change controls were hidden. |
| 6 | Handoff from chat | "Let me speak to someone" produced a queued handoff. | Passed. The reply said the request was queued and not yet delivered. |
| 7 | Staff queue | The staff page showed each request's team status separately from its records-system status. | Passed. Screenshot: `docs/images/staff-queue.png`. |
| 8 | CRM outage and recovery | With the CRM down, the worker retried each handoff and recorded the reason. A later run delivered them. | Passed. The CRM ended with one case per handoff. |

Console messages: no errors during the journeys, other than the expected 404 when a wrong name was looked up, and a favicon request on the staff page, which has since been fixed.

## What these checks do not cover

- They are a single run of each journey, not a repeatable browser suite.
- No recording was made. Screenshots were taken for the staff queue only.
- Speech recognition, the voice agent, and the ElevenLabs widget were not part of these checks.
