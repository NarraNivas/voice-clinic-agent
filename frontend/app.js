// Demo page for the fictional clinic. Every write shows a preview first and needs a second click.
// All server text is rendered with textContent, never innerHTML.

const BOOKING_WINDOW_DAYS = 60;
const SAMPLE_PROMPTS = [
  "What are your hours?",
  "Where are you and is there parking?",
  "What is your cancellation policy?",
  "Is it normal for my tooth to hurt this much?",
  "I have chest pain right now",
  "Let me speak to someone",
];

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function setBox(box, text, kind = "") {
  box.className = `${box.id.includes("reply") ? "reply" : "review"} ${kind}`.trim();
  box.textContent = text;
}

function showStatus(text) {
  const box = $("status");
  box.hidden = !text;
  box.textContent = text || "";
}

function requestKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isoDate(offsetDays) {
  // Local calendar date. toISOString() would switch to UTC and can show tomorrow's date too early.
  const day = new Date();
  day.setDate(day.getDate() + offsetDays);
  const pad = (n) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

async function api(path, body) {
  const options = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let response;
  try {
    response = await fetch(`/api${path}`, options);
  } catch {
    throw new Error("Cannot reach the demo server. Is uvicorn running?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.error?.message || `Request failed (${response.status}).`);
    error.code = data?.error?.code;
    throw error;
  }
  return data;
}

// --- assistant ---------------------------------------------------------

function renderChips() {
  const chips = $("chips");
  const tomorrow = isoDate(1);
  const prompts = [...SAMPLE_PROMPTS, `Any cleaning times on ${tomorrow}?`];
  for (const prompt of prompts) {
    chips.append(
      el(
        "button",
        {
          type: "button",
          class: "chip",
          onclick: () => {
            $("message-input").value = prompt;
            $("message-form").requestSubmit();
          },
        },
        prompt,
      ),
    );
  }
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("message-input");
  const message = input.value.trim();
  if (!message) return;
  try {
    const result = await api("/assistant/message", { message });
    const box = $("message-reply");
    box.replaceChildren(el("span", { class: "route" }, `route: ${result.route}`), result.reply);
    box.className = `reply ${result.route.startsWith("escalate") ? "escalated" : ""}`.trim();
    input.value = "";
    await loadLog();
  } catch (error) {
    setBox($("message-reply"), error.message, "error");
  }
}

async function talkToPerson() {
  try {
    const result = await api("/escalations", { reason: "human_request" });
    setBox($("message-reply"), `${result.message} (case #${result.escalation_id})`, "");
    $("message-reply").classList.add("escalated");
    await loadLog();
  } catch (error) {
    setBox($("message-reply"), error.message, "error");
  }
}

// --- booking -----------------------------------------------------------

// One idempotency key per set of booking details. Choosing the same slot again reuses it,
// so a retry after a lost response returns the original booking and never creates a second one.
const bookingKeys = new Map();

function keyName(payload) {
  return [payload.patient_name.toLowerCase(), payload.appointment_type, payload.date, payload.start_time].join("|");
}

function keyFor(payload) {
  const name = keyName(payload);
  if (!bookingKeys.has(name)) bookingKeys.set(name, requestKey());
  return bookingKeys.get(name);
}

const RETRYABLE_TOKEN_ERRORS = new Set(["invalid_confirmation", "confirmation_expired"]);

function showBooked(done) {
  setBox($("book-review"), `${done.summary}\nConfirmation code: ${done.confirmation_code}`, "ok");
}

function bookingPayload(extra = {}) {
  return {
    patient_name: $("book-name").value.trim(),
    appointment_type: $("book-type").value,
    date: $("book-date").value,
    ...extra,
  };
}

async function checkTimes() {
  const type = $("book-type").value;
  const day = $("book-date").value;
  const slots = $("slots");
  slots.replaceChildren();
  $("book-review").replaceChildren();
  if (!day) return setBox($("book-review"), "Pick a date first.", "error");
  try {
    const result = await api("/availability", { date: day, appointment_type: type });
    setBox($("book-review"), result.message, "");
    for (const slot of result.slots) {
      slots.append(el("button", { type: "button", class: "secondary", onclick: () => reviewBooking(slot) }, slot));
    }
  } catch (error) {
    setBox($("book-review"), error.message, "error");
  }
}

async function reviewBooking(startTime) {
  const name = $("book-name").value.trim();
  if (name.length < 2) return setBox($("book-review"), "Enter a patient name first.", "error");
  const details = bookingPayload({ start_time: startTime });
  const payload = { ...details, idempotency_key: keyFor(details) };
  try {
    // The preview returns a single-use token. Confirming sends that token back with the same details.
    const preview = await api("/appointments", payload);
    if (preview.status === "booked") {
      // This exact request was already confirmed earlier. Show it instead of booking again.
      showBooked(preview);
      return;
    }
    let token = preview.confirmation_token;
    renderConfirm($("book-review"), preview.summary, "Confirm booking", async () => {
      let done;
      try {
        done = await api("/appointments", { ...payload, confirmation_token: token });
      } catch (error) {
        if (!RETRYABLE_TOKEN_ERRORS.has(error.code)) throw error;
        // The token was already used or has expired. Asking again with the same key is safe:
        // if the earlier attempt went through, the server returns that booking.
        const again = await api("/appointments", payload);
        if (again.status !== "booked") {
          token = again.confirmation_token;
          throw new Error("That confirmation expired. Check the details and confirm again.");
        }
        done = again;
      }
      showBooked(done);
      await loadLog();
    });
  } catch (error) {
    if (error.code === "idempotency_used") {
      // The earlier request for these details was cancelled. Use a new request for the next try.
      bookingKeys.delete(keyName(details));
    }
    setBox($("book-review"), error.message, "error");
  }
}

function renderConfirm(box, summary, label, onConfirm, onRetry) {
  let retrying = false;
  const confirm = el("button", {
    type: "button",
    class: "pill",
    onclick: async () => {
      if (retrying) {
        // A failed confirm never reuses its token. Ask for a fresh preview instead.
        confirm.disabled = true;
        try {
          await onRetry();
        } catch (error) {
          problem.textContent = error.message;
          problem.hidden = false;
        }
        confirm.disabled = false;
        return;
      }
      confirm.disabled = true;
      try {
        await onConfirm();
      } catch (error) {
        // Keep the preview on screen and say what happened. Never strand the person.
        problem.textContent = error.message;
        problem.hidden = false;
        retrying = true;
        confirm.textContent = "Preview again";
        confirm.disabled = false;
      }
    },
  }, label);
  const problem = el("p", { class: "problem", role: "alert" });
  problem.hidden = true;
  box.replaceChildren(el("p", {}, summary), problem, confirm);
  box.className = "review";
}

// --- manage an existing booking ----------------------------------------

// The booking shown in the manage panel. Re-read from the server after every change.
let currentBooking = null;

function describeBooking(found) {
  const state = found.status === "cancelled" ? "Cancelled" : "Booked";
  return `${found.confirmation_code}: ${found.appointment_type} for ${found.patient_name}\n` +
    `${state} · starts ${found.starts_at.replace("T", " ")}`;
}

function showBooking(found) {
  setBox($("booking-details"), describeBooking(found), found.status === "booked" ? "ok" : "");
  $("manage-actions").hidden = found.status !== "booked";
  $("manage-review").replaceChildren();
  return found;
}

async function refreshBooking() {
  if (!currentBooking) return null;
  return showBooking(await api("/appointments/lookup", currentBooking));
}

async function findBooking(event) {
  event.preventDefault();
  currentBooking = {
    confirmation_code: $("manage-code").value.trim().toUpperCase(),
    patient_name: $("manage-name").value.trim(),
  };
  try {
    await refreshBooking();
  } catch (error) {
    currentBooking = null;
    $("manage-actions").hidden = true;
    setBox($("booking-details"), error.message, "error");
  }
}

// Runs one change (reschedule or cancel). If the reply is lost, the server is asked what happened
// before anything is reported. The change is never resent with the same token.
async function runChange({ path, body, isDone, doneText, summaryText }) {
  try {
    const done = await api(path, body);
    setBox($("manage-review"), done.summary || summaryText, "ok");
    await refreshBooking();
    await loadLog();
  } catch (error) {
    const current = await refreshBooking().catch(() => null);
    if (current && isDone(current)) {
      setBox($("manage-review"), doneText, "ok");
      await loadLog();
      return;
    }
    throw error;
  }
}

function previewChange(path, extra, label, isDone, doneText, summaryText) {
  const attempt = async () => {
    const payload = { ...currentBooking, ...extra };
    const preview = await api(path, payload);
    renderConfirm(
      $("manage-review"),
      preview.summary,
      label,
      () => runChange({
        path,
        body: { ...payload, confirmation_token: preview.confirmation_token },
        isDone,
        doneText,
        summaryText,
      }),
      attempt,
    );
  };
  return attempt;
}

async function startPreview(makeAttempt) {
  if (!currentBooking) return setBox($("manage-review"), "Find a booking first.", "error");
  try {
    await makeAttempt();
  } catch (error) {
    setBox($("manage-review"), error.message, "error");
  }
}

function previewReschedule() {
  const newDate = $("new-date").value;
  const newTime = $("new-time").value;
  const target = `${newDate}T${newTime}`;
  return startPreview(previewChange(
    "/appointments/reschedule",
    { new_date: newDate, new_start_time: newTime },
    "Confirm reschedule",
    (booking) => booking.status === "booked" && booking.starts_at === target,
    `This booking was already moved to ${target.replace("T", " ")}.`,
    "Rescheduled.",
  ));
}

function previewCancel() {
  return startPreview(previewChange(
    "/appointments/cancel",
    {},
    "Confirm cancellation",
    (booking) => booking.status === "cancelled",
    "This booking was already cancelled.",
    "Cancelled.",
  ));
}

// --- voice, log, startup -----------------------------------------------

function renderVoice(health) {
  const area = $("voice-area");
  area.replaceChildren();
  if (health.elevenlabs_widget_configured) {
    // The agent ID is public. The widget script loads from unpkg, as documented by ElevenLabs.
    const script = el("script", {
      src: "https://unpkg.com/@elevenlabs/convai-widget-embed",
      async: "",
      type: "text/javascript",
    });
    document.head.append(script);
    const widget = document.createElement("elevenlabs-convai");
    widget.setAttribute("agent-id", health.elevenlabs_agent_id);
    area.append(
      el("p", { class: "hint" }, "Live voice agent (ElevenLabs). Calls may incur ElevenLabs charges."),
      widget,
    );
    return;
  }
  area.append(
    el(
      "p",
      { class: "hint" },
      "Voice is off in this local demo. Everything in the story still works from text and forms.",
    ),
    el(
      "p",
      { class: "hint" },
      "To turn it on, set the agent ID in your environment file and restart the server. " +
        "Setup steps are in docs/ELEVENLABS_SETUP.md.",
    ),
  );
}

async function loadLog() {
  const list = $("log");
  try {
    const { items } = await api("/interactions");
    list.replaceChildren(
      ...items.map((item) =>
        el(
          "li",
          {},
          el("span", { class: "when" }, item.created_at.replace("T", " ")),
          el(
            "span",
            { class: "what" },
            `${item.tool_name.replaceAll("_", " ")} · ${item.outcome}`,
            el("br"),
            el("span", { class: "muted" }, item.summary),
          ),
        ),
      ),
    );
    if (items.length === 0) {
      list.append(el("li", {}, el("span", { class: "muted" }, "Nothing yet. Try a question first.")));
    }
  } catch (error) {
    list.replaceChildren(el("li", {}, el("span", { class: "muted" }, error.message)));
  }
}

// Chapters fade in as they reach the reader. Without JavaScript they stay visible.
function revealOnScroll() {
  document.documentElement.classList.add("js");
  const nodes = document.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window)) {
    nodes.forEach((node) => node.classList.add("in-view"));
    return;
  }
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
          observer.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.12 },
  );
  nodes.forEach((node) => observer.observe(node));
}

async function start() {
  revealOnScroll();
  renderChips();
  $("book-date").min = isoDate(0);
  $("book-date").max = isoDate(BOOKING_WINDOW_DAYS);
  $("book-date").value = isoDate(1);
  $("new-date").min = isoDate(0);
  $("new-date").max = isoDate(BOOKING_WINDOW_DAYS);

  $("message-form").addEventListener("submit", sendMessage);
  $("human-button").addEventListener("click", talkToPerson);
  $("check-times").addEventListener("click", checkTimes);
  $("lookup-form").addEventListener("submit", findBooking);
  $("reschedule-button").addEventListener("click", previewReschedule);
  $("cancel-button").addEventListener("click", previewCancel);
  $("refresh-log").addEventListener("click", loadLog);

  try {
    const [clinic, health] = await Promise.all([api("/clinic"), api("/health")]);
    $("clinic-name").textContent = clinic.name;
    document.title = `${clinic.name} · Voice Agent Demo`;
    renderVoice(health);
    showStatus("");
  } catch (error) {
    showStatus(`${error.message} Start the server with: uvicorn app.main:create_app --factory`);
    $("voice-area").textContent = "Voice status unavailable.";
  }
  await loadLog();
}

start();
