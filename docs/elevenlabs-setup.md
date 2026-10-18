# ElevenLabs setup (optional)

The app works without ElevenLabs. Voice is optional. This guide covers the manual steps to connect a voice agent in the ElevenLabs dashboard. Those steps need your account, so the app does not create anything for you.

## Before you start: cost control

- The free Agents plan currently includes 15 call minutes. Calls beyond that, and LLM usage, can cost extra. Check current pricing at [ElevenAgents pricing](https://elevenlabs.io/pricing/agents) and [How agent costs work](https://elevenlabs.io/docs/help-center/product/eleven-agents/how-much-does-eleven-agents-cost).
- Do not enable paid usage without approval.
- The browser widget requires a public agent with **authentication disabled**. Anyone who has the agent ID can start calls on your account. Set an allowlist (step 4) and a spend cap, and keep the widget off the public internet unless you intend to pay for traffic.
- Keep test calls short. Ten short calls is enough to demo the flow.

## 1. Run the app locally

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export TOOL_SHARED_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn app.main:create_tools_app --factory --host 127.0.0.1 --port 8001
```

This starts the **tools-only** app on port 8001. It is the only app you should expose through a tunnel. The full demo (`create_app`, port 8000) includes unauthenticated `/api/*` routes and the activity log. Do not tunnel it.

**About `.env`:** the app reads environment variables. It does not load a `.env` file. If you keep your secret in `.env`, load it into the same shell before you start the server:

```bash
set -a; . ../.env; set +a      # run from backend/, and in the same terminal as uvicorn
```

Otherwise the server starts with the tools disabled and returns `503 tools_disabled`. Never commit `.env`.

## 2. Create the agent

1. In the ElevenLabs dashboard, create a new agent (Conversational AI / ElevenAgents).
2. Set the first message to say that this is an AI demo for a fictional clinic with invented data.
3. Paste the system prompt from [docs/agent-instructions.md](agent-instructions.md) (section 1). It covers the booking steps, intent changes, reading the confirmation code back, and the rules on what the agent may claim. The short version:
   - Only offer booking, rescheduling, cancelling, FAQ answers, and escalation.
   - Never give medical advice. Escalate medical or emergency questions.
   - Read the booking summary back and get an explicit "yes". Then call `book-appointment` again with the same details and the `confirmation_token` from the preview response.
   - Never invent slots. Only offer times returned by `check-availability`.
4. Under the agent's security settings, turn on **allowed hosts** and list only `127.0.0.1` / `localhost` and any demo host you use.
5. Under advanced settings, turn **authentication off** so the browser widget can connect. Read the warning in section "Cost control" above first.
6. Copy the **agent ID** (public).

## 3. Add the server tools

ElevenLabs calls server tools over HTTPS. Your local `127.0.0.1` address is not reachable from the cloud, so tool calls need a public URL. Options:

- A tunnel you run yourself, pointed at **port 8001 (the tools-only app) only**. Tunnels are third-party services. Do not start one without approval.
- Or deploy the app somewhere. Not covered in this release.

For each tool, add a server tool with:

- **Method:** POST
- **URL:** `https://<your-public-host>/tools/<name>`
- **Header:** `X-Tool-Secret: <your TOOL_SHARED_SECRET>`
- **Body schema:** copy the matching request model from `http://127.0.0.1:8001/openapi.json` (the tools-only app's schema).

| Tool name | Path | When the agent should use it |
|---|---|---|
| check_availability | `/tools/check-availability` | Caller asks for times on a date |
| book_appointment | `/tools/book-appointment` | First call without a token (preview). After a spoken yes, call again with the same details and the `confirmation_token` from the preview. |
| lookup_appointment | `/tools/lookup-appointment` | Caller gives a code and name |
| reschedule_appointment | `/tools/reschedule-appointment` | Preview first. After a spoken yes, send the same details plus the `confirmation_token`. |
| cancel_appointment | `/tools/cancel-appointment` | Preview first. After a spoken yes, send the same details plus the `confirmation_token`. |
| answer_faq | `/tools/answer-faq` | Questions about hours, location, policies |
| escalate_to_human | `/tools/escalate-to-human` | Medical, emergency, unsupported, or caller asks for a person |

The tool flow is **preview, then confirm**. A request with no `confirmation_token` returns `confirmation_required` and a single-use token, and writes nothing. The token expires after five minutes, works only for the exact details it was issued for, and is consumed on use. A flag such as `confirmed: true` does not write anything on its own.

## 4. Embed the widget

When `ELEVENLABS_AGENT_ID` is set in your environment and the server restarts, the demo page loads the widget from the ElevenLabs package. The page renders:

```html
<script src="https://unpkg.com/@elevenlabs/convai-widget-embed@0.18.3" integrity="sha384-BpmvKCW/TFrpO8oObmUgZzUCIMHI00QbpGA4/jfXcfTosbgtuEUN1wYT7nNIsV3v" crossorigin="anonymous" async type="text/javascript"></script>
<elevenlabs-convai agent-id="YOUR_AGENT_ID"></elevenlabs-convai>
```

Check the current widget snippet in the [ElevenLabs widget docs](https://elevenlabs.io/docs/eleven-agents/customization/widget) if the embed changes.

## 5. Test within the free allowance

1. Run the app and open `http://127.0.0.1:8000`.
2. Confirm the voice panel shows the widget, not the fallback text.
3. Run three short scenarios: an FAQ question, an availability check, and a booking that you then cancel.
4. Check the activity log on the demo page. Calls through the tools appear with channel `elevenlabs`.
5. Check your minutes in the ElevenLabs dashboard before you run more calls.

## Troubleshooting

- **Tool returns 503 `tools_disabled`:** `TOOL_SHARED_SECRET` is not set in the server's environment.
- **Tool returns 401 `unauthorized`:** the header value in ElevenLabs does not match the server secret.
- **Tool never reaches the server:** the public URL is not forwarding to port 8001 (the tools-only app), or the tunnel is down.
- **Widget shows an error about the agent:** check that authentication is off and the allowed hosts include your demo host.
