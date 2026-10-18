// Staff dashboard for the local demo. Server text is rendered with textContent only.

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
const REFRESH_MS = 15000;

const state = { items: [], statuses: [], filter: "all", query: "" };
const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function count(items, predicate) {
  return items.filter(predicate).length;
}

function percent(part, whole) {
  return whole === 0 ? 0 : Math.round((part / whole) * 100);
}

function setValue(node, value) {
  if (node.textContent === String(value)) return;
  node.textContent = String(value);
  node.classList.remove("bump");
  void node.offsetWidth;
  node.classList.add("bump");
}

function renderKpis(items) {
  setValue($("kpi-total"), items.length);
  setValue($("kpi-open"), count(items, (i) => i.status === "open"));
  setValue($("kpi-progress"), count(items, (i) => i.status === "in_progress"));
  setValue($("kpi-resolved"), count(items, (i) => i.status === "resolved"));
}

function renderStatus(items) {
  const total = items.length || 1;
  const parts = [
    ["open", "Open", count(items, (i) => i.status === "open")],
    ["progress", "In progress", count(items, (i) => i.status === "in_progress")],
    ["resolved", "Resolved", count(items, (i) => i.status === "resolved")],
  ];
  const bar = $("stack-bar");
  const legend = $("stack-legend");
  bar.replaceChildren();
  legend.replaceChildren();
  for (const [key, label, value] of parts) {
    const segment = el("span", `seg-${key}`);
    segment.style.width = `${(value / total) * 100}%`;
    segment.title = `${label}: ${value}`;
    bar.append(segment);
    const item = el("li");
    item.append(el("span", `sw seg-${key}`), el("span", "", label), el("b", "", String(value)));
    legend.append(item);
  }
}

function renderHandoff(items) {
  const tracked = items.filter((i) => i.handoff_state);
  const delivered = count(tracked, (i) => i.handoff_state === "delivered");
  const share = percent(delivered, tracked.length);
  const ring = $("ring");
  ring.style.setProperty("--share", String(share));
  $("ring-value").textContent = tracked.length ? `${share}%` : "–";
  ring.setAttribute("aria-label", `${share} percent of tracked requests delivered`);

  const legend = $("handoff-legend");
  legend.replaceChildren();
  for (const key of ["delivered", "queued", "failed"]) {
    const value = count(tracked, (i) => i.handoff_state === key);
    const item = el("li");
    item.append(
      el("span", `sw seg-${key}`),
      el("span", "", HANDOFF_LABELS[key]),
      el("b", "", String(value)),
    );
    legend.append(item);
  }
  const untracked = items.length - tracked.length;
  if (untracked > 0) {
    const item = el("li");
    item.append(el("span", "sw", ""), el("span", "", "Not queued"), el("b", "", String(untracked)));
    legend.append(item);
  }
}

function renderReasons(items) {
  const list = $("reason-bars");
  list.replaceChildren();
  const tally = new Map();
  for (const item of items) tally.set(item.reason, (tally.get(item.reason) ?? 0) + 1);
  const ranked = [...tally.entries()].sort((a, b) => b[1] - a[1]);
  const max = ranked.length ? ranked[0][1] : 1;
  if (ranked.length === 0) {
    list.append(el("li", "", "No requests yet."));
    return;
  }
  for (const [reason, value] of ranked) {
    const row = el("li");
    const track = el("span", "track");
    const fill = el("span", "fill");
    fill.style.width = `${(value / max) * 100}%`;
    track.append(fill);
    row.append(el("span", "", REASON_LABELS[reason] ?? reason), track, el("span", "count", String(value)));
    list.append(row);
  }
}

function renderFilters(items) {
  const host = $("filters");
  host.replaceChildren();
  const options = [
    ["all", "All", items.length],
    ["open", "Open", count(items, (i) => i.status === "open")],
    ["in_progress", "In progress", count(items, (i) => i.status === "in_progress")],
    ["resolved", "Resolved", count(items, (i) => i.status === "resolved")],
  ];
  for (const [key, label, value] of options) {
    const button = el("button");
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.filter === key));
    button.append(el("span", "", label), el("span", "n", String(value)));
    button.addEventListener("click", () => {
      state.filter = key;
      renderQueue();
    });
    host.append(button);
  }
}

function visibleItems() {
  const query = state.query.trim().toLowerCase();
  return state.items.filter((item) => {
    if (state.filter !== "all" && item.status !== state.filter) return false;
    if (!query) return true;
    const label = (REASON_LABELS[item.reason] ?? item.reason).toLowerCase();
    return label.includes(query);
  });
}

function pill(kind, text) {
  return el("span", `pill pill-${kind}`, text);
}

function renderQueue() {
  renderFilters(state.items);
  const list = $("queue-list");
  list.replaceChildren();
  const items = visibleItems();
  $("queue-empty").hidden = items.length > 0;
  for (const item of items) {
    const row = el("li", "queue-item");
    row.dataset.status = item.status;

    const body = el("div");
    body.append(el("h3", "queue-title", REASON_LABELS[item.reason] ?? item.reason));
    const meta = [item.created_at.replace("T", " ")];
    if (item.attempts > 0) meta.push(`${item.attempts} delivery ${item.attempts === 1 ? "try" : "tries"}`);
    body.append(el("p", "queue-meta", meta.join(" · ")));

    const pills = el("div", "pills");
    pills.append(pill(item.status, STATUS_LABELS[item.status] ?? item.status));
    if (item.handoff_state) {
      pills.append(pill(item.handoff_state, HANDOFF_LABELS[item.handoff_state]));
    } else {
      pills.append(pill("none", "Not queued"));
    }
    body.append(pills);

    const actions = el("div", "queue-actions");
    for (const next of state.statuses.filter((s) => s !== item.status)) {
      const button = el("button", "chip", `Mark ${STATUS_LABELS[next].toLowerCase()}`);
      button.type = "button";
      button.addEventListener("click", () => change(item.request_id, next));
      actions.append(button);
    }

    row.append(body, actions);
    list.append(row);
  }
  $("staff-status").textContent = `${items.length} of ${state.items.length} request(s) shown. Newest first.`;
}

function renderAll() {
  renderKpis(state.items);
  renderStatus(state.items);
  renderHandoff(state.items);
  renderReasons(state.items);
  renderQueue();
}

function stampUpdated(when) {
  $("staff-updated").textContent = `Updated ${when.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
}

async function load() {
  try {
    const response = await fetch("/api/staff/requests", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body = await response.json();
    state.items = body.items;
    state.statuses = body.statuses;
    renderAll();
    stampUpdated(new Date());
  } catch (error) {
    $("staff-updated").textContent = "Could not load";
    $("staff-status").textContent = `The queue did not load (${error.message}). Retrying shortly.`;
  }
}

async function change(requestId, status) {
  try {
    await fetch(`/api/staff/requests/${requestId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
  } finally {
    await load();
  }
}

function setup() {
  $("search").addEventListener("input", (event) => {
    state.query = event.target.value;
    renderQueue();
  });
  $("staff-refresh").addEventListener("click", load);
  load();
  setInterval(load, REFRESH_MS);
}

setup();
