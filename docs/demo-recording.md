# Recording a demo

Keep the recording short. Aim for about 90 seconds. The free ElevenLabs allowance is limited, so a local recording of the demo page is enough for most portfolio uses. Record a voice call only if you have approved the minutes.

## Before recording

1. Start a fresh database so the activity log is clean:
   ```bash
   cd backend
   rm -f data/clinic.db
   uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
   ```
2. Open <http://127.0.0.1:8000> in a window about 1280 px wide. Use light mode, or dark mode consistently.
3. Choose a fictional patient name (for example, "Demo Caller").
4. Check that the voice panel says voice is off. That is the expected state for a local demo without ElevenLabs.

## Suggested script (about 90 seconds)

| Time | Show | Say |
|---|---|---|
| 0:00 | Header and the "AI demo · fictional data" badge | "This is an AI appointment assistant for a fictional dental clinic. All data is invented." |
| 0:10 | Click "What are your hours?" chip | "FAQ answers come from a small fictional knowledge base. The route is shown above the answer." |
| 0:25 | Type "Any cleaning times on <a Tuesday>?" | "Availability comes from the server. The assistant can only offer times the backend returns." |
| 0:40 | Book: fill the name, pick a cleaning, click "Check open times", click a slot | "Booking is two steps. The first step shows a preview and writes nothing." |
| 0:55 | Click "Confirm booking" | "Once confirmed, the booking gets a code. Retrying the same request returns the same booking." |
| 1:05 | Click "Talk to a person" or type "I have chest pain" | "Medical and emergency questions are not answered. They are escalated, and emergency wording gives the 911 prompt." |
| 1:20 | Scroll to "Recent activity" | "Every action is logged with an outcome and a short summary. No transcripts are stored." |

## After recording

- Trim the first and last second.
- Do not show `.env`, the tool secret, or any ElevenLabs dashboard page with account details.
- If you record a voice call, state the minutes used and check the dashboard before and after.

## Captions to keep accurate

- Say "fictional clinic", "invented data", and "demo". Do not describe the tool as a production system.
- Do not claim the app is deployed or used with real patients.
