// Clinic analytics for the local demo. Text is set with textContent; charts are built as SVG nodes.

const NS = "http://www.w3.org/2000/svg";
const TYPE_LABELS = { checkup: "Checkup", cleaning: "Cleaning", consultation: "Consultation" };
const REASON_LABELS = {
  emergency: "Emergency wording",
  medical: "Medical question",
  human_request: "Asked for a person",
  unsupported: "Outside the demo",
  ambiguous: "Unclear request",
  change_too_late: "Late change (24-hour rule)",
};
const STATUS_ORDER = ["open", "in_progress", "resolved"];
const STATUS_LABELS = { open: "Open", in_progress: "In progress", resolved: "Resolved" };
const HANDOFF_ORDER = [
  ["delivered", "Delivered"],
  ["queued", "Queued"],
  ["failed", "Failed"],
  ["not_queued", "Not queued"],
];
const WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0];
const WEEK_LABELS = { 0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat" };
const FILTER_KEYS = ["provider_id", "appointment_type", "date_from", "date_to"];
const REFRESH_MS = 20000;

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  return node;
}

// --- filters live in the URL, so a filtered view can be shared ---------------

function readFilters() {
  const params = new URLSearchParams(location.search);
  const filters = {};
  for (const key of FILTER_KEYS) {
    const value = params.get(key);
    if (value) filters[key] = value;
  }
  return filters;
}

function writeFilters(filters) {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    if (filters[key]) params.set(key, filters[key]);
  }
  const query = params.toString();
  history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

function syncControls(filters) {
  $("f-provider").value = filters.provider_id ?? "";
  $("f-type").value = filters.appointment_type ?? "";
  $("f-from").value = filters.date_from ?? "";
  $("f-to").value = filters.date_to ?? "";
}

function chip(label, onRemove) {
  const button = el("button", "active-chip", `${label} ×`);
  button.type = "button";
  button.setAttribute("aria-label", `Remove filter ${label}`);
  button.addEventListener("click", onRemove);
  return button;
}

function renderActive(filters, providers) {
  const host = $("active-filters");
  host.replaceChildren();
  const remove = (key) => () => {
    const next = { ...filters };
    delete next[key];
    setFilters(next);
  };
  if (filters.provider_id) {
    const name = providers.find((p) => String(p.provider_id) === filters.provider_id)?.name;
    host.append(chip(name ?? "Provider", remove("provider_id")));
  }
  if (filters.appointment_type) {
    host.append(chip(TYPE_LABELS[filters.appointment_type], remove("appointment_type")));
  }
  if (filters.date_from) host.append(chip(`From ${filters.date_from}`, remove("date_from")));
  if (filters.date_to) host.append(chip(`To ${filters.date_to}`, remove("date_to")));
}

let currentFilters = {};

function setFilters(filters) {
  currentFilters = filters;
  writeFilters(filters);
  load();
}

function toggle(key, value) {
  const next = { ...currentFilters };
  if (String(next[key]) === String(value)) delete next[key];
  else next[key] = String(value);
  setFilters(next);
}

// --- tooltip ----------------------------------------------------------------

function showTip(event, lines) {
  const tip = $("tip");
  tip.replaceChildren(...lines.map((line, i) => el(i === 0 ? "strong" : "span", "", line)));
  tip.hidden = false;
  const x = Math.min(event.clientX + 14, window.innerWidth - tip.offsetWidth - 12);
  tip.style.left = `${x + window.scrollX}px`;
  tip.style.top = `${event.clientY + window.scrollY + 14}px`;
}

function hideTip() {
  $("tip").hidden = true;
}

function attachTip(node, lines) {
  node.addEventListener("mousemove", (event) => showTip(event, lines));
  node.addEventListener("mouseleave", hideTip);
  node.addEventListener("focus", () => {
    const rect = node.getBoundingClientRect();
    showTip({ clientX: rect.left, clientY: rect.top }, lines);
  });
  node.addEventListener("blur", hideTip);
}

// --- data tables under "View data" ------------------------------------------

function table(host, headers, rows) {
  host.replaceChildren();
  const t = el("table", "data-grid");
  const head = el("tr");
  for (const h of headers) head.append(el("th", "", h));
  t.append(el("thead"), el("tbody"));
  t.querySelector("thead").append(head);
  for (const row of rows) {
    const tr = el("tr");
    for (const value of row) tr.append(el("td", "", String(value)));
    t.querySelector("tbody").append(tr);
  }
  host.append(t);
}

function empty(host, message) {
  host.replaceChildren(el("p", "sheet-empty", message));
}

// --- KPIs -------------------------------------------------------------------

function renderKpis(data) {
  const t = data.totals;
  const staffTotal = data.staff.by_reason.reduce((sum, r) => sum + r.n, 0);
  const tracked = data.staff.handoff.filter((h) => h.state !== "not_queued");
  const trackedTotal = tracked.reduce((sum, h) => sum + h.n, 0);
  const delivered = tracked.find((h) => h.state === "delivered")?.n ?? 0;
  const share = trackedTotal ? `${Math.round((100 * delivered) / trackedTotal)}%` : "–";
  $("k-booked").textContent = String(t.booked);
  $("k-cancelled").textContent = String(t.cancelled);
  $("k-rate").textContent = `${t.cancel_rate}%`;
  $("k-hours").textContent = (t.booked_minutes / 60).toFixed(1);
  $("k-staff").textContent = String(staffTotal);
  $("k-delivered").textContent = share;
}

// --- trend: booked and cancelled per day ------------------------------------

function renderTrend(data) {
  const host = $("trend");
  const days = data.by_day;
  table($("trend-data"), ["Day", "Booked", "Cancelled"], days.map((d) => [d.day, d.booked, d.cancelled]));
  if (days.length === 0) return empty(host, "No bookings match these filters.");

  const W = 760, H = 260, L = 42, R = 14, T = 16, B = 30;
  const top = Math.max(1, ...days.map((d) => Math.max(d.booked, d.cancelled)));
  const yMax = Math.ceil(top * 1.15);
  const x = (i) => L + (days.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (days.length - 1));
  const y = (v) => T + (H - T - B) * (1 - v / yMax);

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Bookings by day" });
  for (let k = 0; k <= 4; k++) {
    const value = Math.round((yMax * k) / 4);
    root.append(svg("line", { x1: L, x2: W - R, y1: y(value), y2: y(value), class: "grid" }));
    const label = svg("text", { x: L - 8, y: y(value) + 4, "text-anchor": "end", class: "axis" });
    label.textContent = String(value);
    root.append(label);
  }
  const bookedPath = days.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.booked)}`).join(" ");
  const area = `${bookedPath} L${x(days.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  root.append(svg("path", { d: area, class: "area" }));
  root.append(svg("path", { d: bookedPath, class: "line line-booked", fill: "none" }));
  const cancelledPath = days.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.cancelled)}`).join(" ");
  root.append(svg("path", { d: cancelledPath, class: "line line-cancelled", fill: "none" }));

  const ticks = Math.min(6, days.length);
  for (let k = 0; k < ticks; k++) {
    const i = ticks === 1 ? 0 : Math.round((k * (days.length - 1)) / (ticks - 1));
    const label = svg("text", { x: x(i), y: H - 8, "text-anchor": "middle", class: "axis" });
    label.textContent = days[i].day.slice(5);
    root.append(label);
  }

  days.forEach((d, i) => {
    root.append(svg("circle", { cx: x(i), cy: y(d.booked), r: 3.5, class: "dot dot-booked" }));
    const hit = svg("rect", { x: x(i) - 12, y: T, width: 24, height: H - T - B, class: "hit", tabindex: 0 });
    attachTip(hit, [d.day, `Booked: ${d.booked}`, `Cancelled: ${d.cancelled}`]);
    root.append(hit);
  });

  host.replaceChildren(root);
  const legend = el("div", "legend-row");
  legend.append(
    el("span", "key key-booked", "Booked"),
    el("span", "key key-cancelled", "Cancelled"),
  );
  host.append(legend);
}

// --- horizontal bar rows (types, providers) ---------------------------------

function barRow(label, booked, cancelled, max, onClick, active) {
  const button = el("button", `bar-row${active ? " is-active" : ""}`);
  button.type = "button";
  button.setAttribute("aria-pressed", String(active));
  button.append(el("span", "bar-label", label));
  const track = el("span", "bar-track");
  const bookedFill = el("span", "bar-fill fill-booked");
  bookedFill.style.width = `${(booked / max) * 100}%`;
  const cancelledFill = el("span", "bar-fill fill-cancelled");
  cancelledFill.style.width = `${(cancelled / max) * 100}%`;
  track.append(bookedFill, cancelledFill);
  button.append(track, el("span", "bar-count", `${booked} / ${cancelled}`));
  button.addEventListener("click", onClick);
  return button;
}

function renderTypes(data) {
  const host = $("types");
  const rows = data.by_type;
  table($("types-data"), ["Type", "Booked", "Cancelled", "Booked minutes"],
    rows.map((r) => [TYPE_LABELS[r.name] ?? r.name, r.booked, r.cancelled, r.booked_minutes]));
  if (rows.length === 0) return empty(host, "No appointment types match these filters.");
  const max = Math.max(1, ...rows.map((r) => r.booked + r.cancelled));
  host.replaceChildren(...rows.map((r) =>
    barRow(TYPE_LABELS[r.name] ?? r.name, r.booked, r.cancelled, max,
      () => toggle("appointment_type", r.name), currentFilters.appointment_type === r.name)));
}

function renderProviders(data) {
  const host = $("providers");
  const rows = data.by_provider;
  table($("providers-data"), ["Provider", "Booked", "Cancelled", "Booked minutes"],
    rows.map((r) => [r.name, r.booked, r.cancelled, r.booked_minutes]));
  const max = Math.max(1, ...rows.map((r) => r.booked + r.cancelled));
  host.replaceChildren(...rows.map((r) =>
    barRow(r.name, r.booked, r.cancelled, max,
      () => toggle("provider_id", r.provider_id), currentFilters.provider_id === String(r.provider_id))));
}

// --- heatmap: weekday by start hour -----------------------------------------

function renderHeat(data) {
  const host = $("heat");
  const cells = data.heatmap;
  if (cells.length === 0) return empty(host, "No bookings match these filters.");
  const hours = cells.map((c) => c.hour);
  const first = Math.min(...hours), last = Math.max(...hours);
  const span = last - first + 1;
  const lookup = new Map(cells.map((c) => [`${c.weekday_index}-${c.hour}`, c.booked]));
  const max = Math.max(1, ...cells.map((c) => c.booked));

  const W = 760, H = 230, L = 52, T = 26, gap = 4;
  const cw = (W - L) / span - gap;
  const ch = (H - T) / WEEK_ORDER.length - gap;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Bookings by weekday and hour" });

  for (let h = first; h <= last; h++) {
    const label = svg("text", { x: L + (h - first) * (cw + gap) + cw / 2, y: 16, "text-anchor": "middle", class: "axis" });
    label.textContent = `${String(h).padStart(2, "0")}:00`;
    root.append(label);
  }
  WEEK_ORDER.forEach((weekday, row) => {
    const label = svg("text", { x: L - 10, y: T + row * (ch + gap) + ch / 2 + 4, "text-anchor": "end", class: "axis" });
    label.textContent = WEEK_LABELS[weekday];
    root.append(label);
    for (let h = first; h <= last; h++) {
      const value = lookup.get(`${weekday}-${h}`) ?? 0;
      const intensity = value === 0 ? 0 : 18 + Math.round((82 * value) / max);
      const cell = svg("rect", {
        x: L + (h - first) * (cw + gap),
        y: T + row * (ch + gap),
        width: cw,
        height: ch,
        rx: 6,
        class: "heat-cell",
        tabindex: 0,
      });
      cell.style.fill = value === 0 ? "var(--rule)" : `color-mix(in srgb, var(--heat) ${intensity}%, var(--paper))`;
      cell.style.opacity = value === 0 ? "0.35" : "1";
      attachTip(cell, [`${WEEK_LABELS[weekday]} ${String(h).padStart(2, "0")}:00`, `Booked: ${value}`]);
      root.append(cell);
      if (value > 0) {
        const text = svg("text", {
          x: L + (h - first) * (cw + gap) + cw / 2,
          y: T + row * (ch + gap) + ch / 2 + 5,
          "text-anchor": "middle",
          class: "cell-count",
        });
        text.textContent = String(value);
        root.append(text);
      }
    }
  });
  host.replaceChildren(root);
}

// --- staff requests and handoff ---------------------------------------------

function renderReasons(data) {
  const host = $("reasons");
  const legend = $("reasons-legend");
  const rows = data.staff.by_reason;
  const byReason = new Map();
  for (const row of rows) {
    if (!byReason.has(row.reason)) byReason.set(row.reason, { open: 0, in_progress: 0, resolved: 0 });
    byReason.get(row.reason)[row.status] = row.n;
  }
  const totals = [...byReason.entries()].map(([reason, s]) => [reason, s, s.open + s.in_progress + s.resolved]);
  totals.sort((a, b) => b[2] - a[2]);
  legend.replaceChildren();
  for (const status of STATUS_ORDER) {
    legend.append(el("span", `key key-${status}`, STATUS_LABELS[status]));
  }
  if (totals.length === 0) return empty(host, "No staff requests yet.");
  const max = Math.max(1, ...totals.map((t) => t[2]));
  host.replaceChildren(...totals.map(([reason, s, total]) => {
    const row = el("div", "stack-row");
    row.append(el("span", "bar-label", REASON_LABELS[reason] ?? reason));
    const track = el("span", "bar-track");
    for (const status of STATUS_ORDER) {
      if (!s[status]) continue;
      const seg = el("span", `bar-fill fill-${status}`);
      seg.style.width = `${(s[status] / max) * 100}%`;
      attachTip(seg, [REASON_LABELS[reason] ?? reason, `${STATUS_LABELS[status]}: ${s[status]}`]);
      track.append(seg);
    }
    row.append(track, el("span", "bar-count", String(total)));
    return row;
  }));
}

function renderHandoff(data) {
  const counts = new Map(data.staff.handoff.map((h) => [h.state, h.n]));
  const total = [...counts.values()].reduce((sum, n) => sum + n, 0) || 1;
  const donut = $("donut");
  donut.replaceChildren();
  const r = 46, C = 2 * Math.PI * r;
  donut.append(svg("circle", { cx: 60, cy: 60, r, class: "donut-track", fill: "none" }));
  let offset = 0;
  const legend = $("handoff-legend");
  legend.replaceChildren();
  for (const [key, label] of HANDOFF_ORDER) {
    const n = counts.get(key) ?? 0;
    const length = (n / total) * C;
    if (n > 0 && key !== "not_queued") {
      const arc = svg("circle", {
        cx: 60, cy: 60, r, fill: "none", class: `donut-arc arc-${key}`,
        "stroke-dasharray": `${length} ${C - length}`,
        "stroke-dashoffset": String(-offset),
        transform: "rotate(-90 60 60)",
      });
      attachTip(arc, [label, `${n} of ${total}`]);
      donut.append(arc);
      offset += length;
    }
    const item = el("li");
    item.append(el("span", `sw sw-${key}`), el("span", "", label), el("b", "", String(n)));
    legend.append(item);
  }
  const share = Math.round(((counts.get("delivered") ?? 0) / total) * 100);
  const center = svg("text", { x: 60, y: 66, "text-anchor": "middle", class: "donut-value" });
  center.textContent = `${share}%`;
  donut.append(center);
}

// --- orchestration ----------------------------------------------------------

function renderFilterControls(data) {
  const select = $("f-provider");
  const current = select.value;
  const all = el("option", "", "All providers");
  all.value = "";
  select.replaceChildren(all);
  for (const p of data.by_provider) {
    const option = el("option", "", p.name);
    option.value = String(p.provider_id);
    select.append(option);
  }
  select.value = current;
  syncControls(currentFilters);
}

function renderAll(data) {
  renderFilterControls(data);
  renderActive(currentFilters, data.by_provider);
  renderKpis(data);
  renderTrend(data);
  renderTypes(data);
  renderHeat(data);
  renderProviders(data);
  renderReasons(data);
  renderHandoff(data);
}

async function load() {
  const qs = new URLSearchParams(currentFilters).toString();
  try {
    const response = await fetch(`/api/analytics${qs ? `?${qs}` : ""}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderAll(data);
    $("dash-status").textContent = "";
    $("dash-updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
  } catch (error) {
    $("dash-updated").textContent = "Could not load";
    $("dash-status").textContent = `The figures did not load (${error.message}). Retrying shortly.`;
  }
}

function setup() {
  currentFilters = readFilters();
  syncControls(currentFilters);
  const onChange = () => {
    const filters = {};
    if ($("f-provider").value) filters.provider_id = $("f-provider").value;
    if ($("f-type").value) filters.appointment_type = $("f-type").value;
    if ($("f-from").value) filters.date_from = $("f-from").value;
    if ($("f-to").value) filters.date_to = $("f-to").value;
    setFilters(filters);
  };
  for (const id of ["f-provider", "f-type", "f-from", "f-to"]) $(id).addEventListener("change", onChange);
  $("f-reset").addEventListener("click", () => setFilters({}));
  load();
  setInterval(load, REFRESH_MS);
}

setup();
