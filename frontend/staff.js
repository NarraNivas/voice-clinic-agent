// Staff queue for the local demo. Server text is rendered with textContent only.

const STATUS_LABELS = { open: "Open", in_progress: "In progress", resolved: "Resolved" };
const REASON_LABELS = {
  emergency: "Emergency wording",
  medical: "Medical question",
  human_request: "Asked for a person",
  unsupported: "Outside the demo",
  ambiguous: "Unclear request",
  change_too_late: "Late change (24-hour rule)",
};
const HANDOFF_LABELS = { queued: "Queued", delivered: "Delivered", failed: "Failed" };

const $ = (id) => document.getElementById(id);

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

async function load() {
  const response = await fetch("/api/staff/requests");
  const body = await response.json();
  const rows = $("staff-rows");
  rows.replaceChildren();
  $("staff-status").textContent = `${body.items.length} request(s). Newest first.`;
  for (const item of body.items) {
    const tr = document.createElement("tr");
    tr.append(
      cell(REASON_LABELS[item.reason] ?? item.reason),
      cell(STATUS_LABELS[item.status] ?? item.status),
      cell(HANDOFF_LABELS[item.handoff_state] ?? "Not queued"),
      cell(item.created_at.replace("T", " ")),
    );
    const actions = document.createElement("td");
    for (const next of body.statuses.filter((s) => s !== item.status)) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = `Mark ${STATUS_LABELS[next].toLowerCase()}`;
      button.addEventListener("click", () => change(item.request_id, next));
      actions.append(button);
    }
    tr.append(actions);
    rows.append(tr);
  }
}

async function change(requestId, status) {
  await fetch(`/api/staff/requests/${requestId}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await load();
}

load();
