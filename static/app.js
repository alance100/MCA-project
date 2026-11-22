"use strict";
// All dynamic text is written with textContent (never innerHTML) to prevent XSS.
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};
const SVG = "http://www.w3.org/2000/svg";
function icon(name) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("class", "icon");
  const u = document.createElementNS(SVG, "use");
  u.setAttribute("href", "#i-" + name);
  s.appendChild(u);
  return s;
}
const fmt = (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
const money = (n) => Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pctText = (p) => (p === null || p === undefined ? "–" : (p > 0 ? "+" : "") + p + "%");
const rgba = (hex, a) => {
  const n = parseInt(hex.replace("#", ""), 16);
  return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
};
const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

const state = {
  data: null, type: "bar", range: "12",
  sortKey: "month", sortDir: -1, year: "all",
  hover: -1, pts: [], geo: null, editing: null,
};

/* ------------------------------------------------------------------ API */
async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function toast(msg, kind, action) {
  const t = el("div", "toast " + (kind || ""));
  t.appendChild(el("span", "", msg));
  if (action) {
    const b = el("button", "toast-btn", action.label);
    b.type = "button";
    b.addEventListener("click", () => { t.remove(); action.run(); });
    t.appendChild(b);
  }
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), action ? 7000 : 4000);
}
const fail = (e) => toast(e.message || "Something went wrong.", "err");

function setMsg(text, ok) {
  const m = $("msg");
  m.textContent = text;
  m.className = "msg " + (text ? (ok ? "ok" : "err") : "");
}

/* --------------------------------------------------------------- render */
function render(data) {
  state.data = data;
  $("main").classList.toggle("is-empty", data.summary.count === 0);
  renderCards();
  renderInsights();
  renderYears();
  renderTable();
  fillSettings();
  // Don't clobber a half-typed value or a record being edited.
  if (!state.editing && $("kwh").value === "") resetForm();
  drawChart();
  drawSparks();
}

function renderCards() {
  const s = state.data.summary;
  const dash = (id) => { $(id).textContent = "–"; $(id + "-sub").textContent = ""; };
  if (!s.count) {
    ["total", "average", "highest", "lowest", "forecast", "cost"].forEach(dash);
    $("forecast-label").textContent = "Next month forecast";
    $("forecast-method").textContent = "";
    $("range-vis").hidden = true;
    $("bill-bar-wrap").hidden = true;
    return;
  }
  const f = s.forecast;
  $("total").textContent = fmt(s.total) + " kWh";
  $("total-sub").textContent = s.count + " month" + (s.count > 1 ? "s" : "") + " recorded";
  $("average").textContent = fmt(s.average) + " kWh";
  $("average-sub").textContent = s.count < 2 || s.vs_average_pct === null ? "per month"
    : "Latest " + pctText(s.vs_average_pct) + " vs average";
  $("highest").textContent = fmt(s.highest.kwh) + " kWh";
  $("highest-sub").textContent = s.highest.label;
  $("lowest").textContent = fmt(s.lowest.kwh) + " kWh";
  $("lowest-sub").textContent = s.lowest.label;

  // Hero forecast card
  $("forecast-label").textContent = f.label;
  $("forecast-method").textContent = f.method_label;
  $("forecast").textContent = fmt(f.value);
  const latest = s.latest;
  const diff = latest.kwh > 0 ? Math.round(((f.value - latest.kwh) / latest.kwh) * 1000) / 10 : null;
  $("forecast-sub").textContent = f.note ||
    (diff === null ? "" : pctText(diff) + " vs " + latest.label + " (" + fmt(latest.kwh) + " kWh)");
  const spread = f.high - f.low;
  $("range-vis").hidden = spread <= 0;
  if (spread > 0) {
    const lo = Math.max(0, f.low - spread * 0.7), hi = f.high + spread * 0.7;
    const pos = (v) => ((v - lo) / (hi - lo)) * 100;
    $("range-band").style.left = pos(f.low) + "%";
    $("range-band").style.width = pos(f.high) - pos(f.low) + "%";
    $("range-marker").style.left = pos(f.value) + "%";
    $("range-low").textContent = fmt(f.low) + " kWh";
    $("range-high").textContent = fmt(f.high) + " kWh";
  }

  const wrap = $("bill-bar-wrap");
  if (s.cost === null) {
    $("cost").textContent = "–";
    $("cost-sub").textContent = "Set a rate in Settings to estimate your bill";
    wrap.hidden = true;
  } else {
    $("cost").textContent = money(s.cost);
    wrap.hidden = s.budget_pct === null;
    if (s.budget_pct === null) {
      $("cost-sub").textContent = "Forecast × " + state.data.settings.rate + " per kWh";
    } else {
      $("cost-sub").textContent = fmt(s.budget_pct) + "% of " + money(state.data.settings.budget) + " monthly budget";
      $("bill-bar").style.width = Math.min(100, s.budget_pct) + "%";
      wrap.className = "bar " + s.budget_status;
    }
  }
}

function renderInsights() {
  const ul = $("insights");
  ul.replaceChildren();
  const list = state.data.insights.length
    ? state.data.insights
    : [{ level: "info", text: "Add your first month of consumption to see insights." }];
  const ic = { good: "check", warn: "alert", info: "info" };
  list.forEach((i) => {
    const li = el("li", i.level);
    const chip = el("span", "chip");
    chip.appendChild(icon(ic[i.level] || "info"));
    li.append(chip, el("span", "txt", i.text));
    ul.appendChild(li);
  });
}

function renderYears() {
  const sel = $("year");
  sel.replaceChildren();
  const opt = (v, t) => { const o = el("option", "", t); o.value = v; return o; };
  sel.appendChild(opt("all", "All years"));
  state.data.years.slice().reverse().forEach((y) => sel.appendChild(opt(String(y), String(y))));
  if (state.year !== "all" && !state.data.years.includes(Number(state.year))) state.year = "all";
  sel.value = state.year;
}

function badge(p) {
  const cls = p === null ? "none" : p > 0 ? "up" : p < 0 ? "down" : "flat";
  return el("span", "badge " + cls, p === null ? "–" : Math.abs(p) + "%");
}

function renderTable() {
  const tbody = $("rows");
  tbody.replaceChildren();
  let rows = state.data.records.filter((r) => state.year === "all" || String(r.year) === state.year);
  rows = rows.slice().sort((a, b) =>
    (state.sortKey === "kwh" ? a.kwh - b.kwh : a.month.localeCompare(b.month)) * state.sortDir);

  document.querySelectorAll("th .sort").forEach((b) => {
    const active = b.dataset.sort === state.sortKey;
    b.parentElement.setAttribute("aria-sort", active ? (state.sortDir > 0 ? "ascending" : "descending") : "none");
    b.querySelector(".arrow").textContent = active ? (state.sortDir > 0 ? "▲" : "▼") : "";
  });

  if (!rows.length) {
    const tr = el("tr"), td = el("td", "empty", "No records for this selection.");
    td.colSpan = 5;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  const s = state.data.summary;
  const top = Math.max(...rows.map((r) => r.kwh), 1);
  rows.forEach((r) => {
    const tr = el("tr");
    const m = el("td");
    const [name, year] = r.label.split(" ");
    m.append(el("span", "mname", name), el("span", "myear", year));
    tr.appendChild(m);

    const u = el("td", "num");
    const cell = el("div", "usage-cell");
    const bar = el("div", "databar" + (state.data.records.length > 2 && r.month === s.highest.month ? " peak"
      : state.data.records.length > 2 && r.month === s.lowest.month ? " low" : ""));
    const fill = el("span");
    fill.style.width = Math.max(2, (r.kwh / top) * 100) + "%";
    bar.appendChild(fill);
    cell.append(bar, el("span", "usage-val", fmt(r.kwh)));
    u.appendChild(cell);
    tr.appendChild(u);

    const a = el("td", "num"); a.appendChild(badge(r.mom_pct)); tr.appendChild(a);
    const b = el("td", "num hide-sm"); b.appendChild(badge(r.yoy_pct)); tr.appendChild(b);

    const c = el("td", "num");
    const act = el("div", "actions");
    const edit = el("button", "row-btn");
    edit.type = "button"; edit.title = "Edit"; edit.setAttribute("aria-label", "Edit " + r.label);
    edit.appendChild(icon("edit"));
    edit.addEventListener("click", () => startEdit(r));
    const del = el("button", "row-btn del");
    del.type = "button"; del.title = "Delete"; del.setAttribute("aria-label", "Delete " + r.label);
    del.appendChild(icon("trash"));
    del.addEventListener("click", () => removeRecord(r));
    act.append(edit, del);
    c.appendChild(act);
    tr.appendChild(c);
    tbody.appendChild(tr);
  });
}

function fillSettings() {
  const sel = $("method"), st = state.data.settings;
  if (!sel.options.length) {
    Object.entries(state.data.methods).forEach(([k, v]) => {
      const o = el("option", "", v); o.value = k; sel.appendChild(o);
    });
  }
  if (!$("settings").contains(document.activeElement)) {   // don't overwrite while typing
    sel.value = st.method;
    $("rate").value = st.rate || "";
    $("budget").value = st.budget || "";
  }
  const f = state.data.summary.forecast;
  $("method-hint").textContent = f && f.note ? f.note : "";
}

/* ----------------------------------------------------------- form logic */
function nextMonth(m) {
  let y = Number(m.slice(0, 4)), mo = Number(m.slice(5));
  mo += 1; if (mo > 12) { mo = 1; y += 1; }
  return y + "-" + String(mo).padStart(2, "0");
}
function defaultMonth() {
  const recs = state.data && state.data.records;
  if (recs && recs.length) return nextMonth(recs[recs.length - 1].month);
  const n = new Date();
  return n.getFullYear() + "-" + String(n.getMonth() + 1).padStart(2, "0");
}
function resetForm() {
  state.editing = null;
  $("form-title").textContent = "Add record";
  $("save").textContent = "Save record";
  $("cancel").hidden = true;
  $("month").value = defaultMonth();
  $("kwh").value = "";
}
function startEdit(r) {
  state.editing = r.month;
  $("form-title").textContent = "Edit " + r.label;
  $("save").textContent = "Update record";
  $("cancel").hidden = false;
  $("month").value = r.month;
  $("kwh").value = r.kwh;
  setMsg("", true);
  $("form").scrollIntoView({ behavior: "smooth", block: "center" });
  $("kwh").focus();
}

async function removeRecord(r) {
  try {
    render(await api("DELETE", "/api/records/" + encodeURIComponent(r.month)));
    toast("Deleted " + r.label, "", {
      label: "Undo",
      run: async () => {
        try { render(await api("POST", "/api/records", { month: r.month, kwh: r.kwh })); }
        catch (e) { fail(e); }
      },
    });
  } catch (e) { fail(e); }
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const month = $("month").value.trim(), kwh = $("kwh").value;
  if (!MONTH_RE.test(month)) return setMsg("Enter the month as YYYY-MM.", false);
  if (kwh === "" || !isFinite(Number(kwh)) || Number(kwh) < 0) return setMsg("Enter consumption as a non-negative number.", false);
  try {
    const existed = state.data.records.some((r) => r.month === month);
    const d = await api("POST", "/api/records", { month, kwh: Number(kwh) });
    state.editing = null;
    $("kwh").value = "";           // so render() resets the form to the next month
    render(d);
    setMsg("", true);
    toast((existed ? "Updated " : "Saved ") + month);
    $("kwh").focus();
  } catch (err) { setMsg(err.message, false); }
});
$("cancel").addEventListener("click", () => { resetForm(); setMsg("", true); });

$("sample").addEventListener("click", async () => {
  const y = new Date().getFullYear();
  try {
    let d;
    for (const [m, v] of [["01", 150], ["02", 200], ["03", 180]]) {
      d = await api("POST", "/api/records", { month: y + "-" + m, kwh: v });
    }
    render(d);
    toast("Sample data loaded");
  } catch (err) { fail(err); }
});

$("settings").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    render(await api("POST", "/api/settings", {
      method: $("method").value,
      rate: $("rate").value === "" ? 0 : Number($("rate").value),
      budget: $("budget").value === "" ? 0 : Number($("budget").value),
    }));
    toast("Settings saved");
  } catch (err) { fail(err); }
});

/* ------------------------------------------------- table + data controls */
document.querySelectorAll("th .sort").forEach((b) => b.addEventListener("click", () => {
  const k = b.dataset.sort;
  if (state.sortKey === k) state.sortDir *= -1; else { state.sortKey = k; state.sortDir = -1; }
  renderTable();
}));
$("year").addEventListener("change", () => { state.year = $("year").value; renderTable(); });

["import", "import2"].forEach((id) => $(id).addEventListener("click", () => $("file").click()));
$("file").addEventListener("change", async () => {
  const f = $("file").files[0];
  $("file").value = "";
  if (!f) return;
  if (f.size > 100000) return toast("File is too large (max 100 KB).", "err");
  try {
    const d = await api("POST", "/api/import", { csv: await f.text() });
    render(d);
    const i = d.imported;
    toast("Imported " + i.added + " new, " + i.updated + " updated" + (i.skipped ? ", " + i.skipped + " skipped" : "") +
      (i.errors.length ? " - " + i.errors[0] : ""));
  } catch (err) { fail(err); }
});
$("clear").addEventListener("click", async () => {
  if (!state.data.records.length) return;
  if (!confirm("Delete ALL records? Export a CSV first if you want a backup.")) return;
  try { render(await api("DELETE", "/api/records")); toast("All records deleted"); }
  catch (err) { fail(err); }
});

/* ---------------------------------------------------------------- theme */
function resolveTheme() {
  try { const t = localStorage.getItem("theme"); if (t === "light" || t === "dark") return t; } catch (e) { /* ignore */ }
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  drawChart(); drawSparks();
}
$("theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem("theme", next); } catch (e) { /* storage may be unavailable */ }
  applyTheme(next);
});
document.documentElement.dataset.theme = resolveTheme();

/* ----------------------------------------------------------- sparklines */
function smoothPath(ctx, pts) {
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) {
    const mx = (pts[i - 1].x + pts[i].x) / 2;
    ctx.bezierCurveTo(mx, pts[i - 1].y, mx, pts[i].y, pts[i].x, pts[i].y);
  }
}
function spark(id, vals, color) {
  const cv = $(id);
  const w = cv.clientWidth, h = cv.clientHeight;
  if (!w || !h) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (vals.length < 2) return;
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = vals.map((v, i) => ({ x: 3 + (i * (w - 6)) / (vals.length - 1), y: h - 5 - ((v - min) / span) * (h - 12) }));
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, rgba(color, 0.28)); g.addColorStop(1, rgba(color, 0));
  ctx.beginPath(); smoothPath(ctx, pts);
  ctx.lineTo(pts[pts.length - 1].x, h); ctx.lineTo(pts[0].x, h); ctx.closePath();
  ctx.fillStyle = g; ctx.fill();
  ctx.beginPath(); smoothPath(ctx, pts);
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineCap = "round"; ctx.stroke();
  const last = pts[pts.length - 1];
  ctx.beginPath(); ctx.arc(last.x, last.y, 3, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
}
function drawSparks() {
  const d = state.data;
  if (!d || !d.records.length) return;
  const cs = getComputedStyle(document.documentElement);
  const vals = d.records.map((r) => r.kwh);
  let run = 0;
  const avg = vals.map((v, i) => (run += v) / (i + 1));
  spark("spark-total", vals.slice(-12), cs.getPropertyValue("--accent").trim());
  spark("spark-avg", avg.slice(-12), cs.getPropertyValue("--info").trim());
}

/* ---------------------------------------------------------------- chart */
function niceMax(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v * 1.05) return m * p;
  return v;
}
function rr(ctx, x, y, w, h, r) {   // rounded rect path with fallback
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h);
}

function drawChart() {
  const cv = $("chart"), ctx = cv.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 340;
  if (!W) return;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);   // crisp on HiDPI
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const cs = getComputedStyle(document.documentElement);
  const c = (v) => cs.getPropertyValue(v).trim();
  const FONT = "system-ui, 'Segoe UI', sans-serif";
  ctx.font = "12px " + FONT;
  state.pts = []; state.geo = null;

  const d = state.data;
  if (!d || !d.records.length) return;
  const s = d.summary, f = s.forecast;
  const recs = d.records.slice(-Number(state.range));
  const items = recs.map((r) => ({
    label: r.label.slice(0, 3) + " " + String(r.year).slice(2), full: r.label,
    v: r.kwh, month: r.month, mom: r.mom_pct, fc: false,
  }));
  items.push({ label: "Next", full: "Forecast · " + f.label, v: f.value, low: f.low, high: f.high, fc: true });

  const pad = { l: 52, r: 14, t: 28, b: 38 };
  const max = niceMax(Math.max(...items.map((i) => (i.fc ? i.high : i.v)), s.average, 1));
  const cw = (W - pad.l - pad.r) / items.length, ch = H - pad.t - pad.b;
  const yOf = (v) => pad.t + ch - (v / max) * ch;
  const base = pad.t + ch;
  state.geo = { l: pad.l, cw, n: items.length };

  // hovered column highlight
  if (state.hover >= 0 && state.hover < items.length) {
    ctx.fillStyle = rgba(c("--muted"), 0.1);
    ctx.beginPath(); rr(ctx, pad.l + state.hover * cw + 2, pad.t - 8, cw - 4, ch + 8, 8); ctx.fill();
  }
  // grid + y labels
  ctx.lineWidth = 1; ctx.textAlign = "right";
  for (let i = 0; i <= 4; i++) {
    const y = Math.round(yOf((max * i) / 4)) + 0.5;
    ctx.strokeStyle = i === 0 ? rgba(c("--muted"), 0.45) : c("--line");
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillStyle = c("--muted"); ctx.fillText(fmt((max * i) / 4), pad.l - 8, y + 4);
  }
  // average line
  const ay = yOf(s.average);
  ctx.save();
  ctx.setLineDash([5, 4]); ctx.strokeStyle = rgba(c("--muted"), 0.9); ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.moveTo(pad.l, ay); ctx.lineTo(W - pad.r, ay); ctx.stroke();
  ctx.restore();
  ctx.fillStyle = c("--muted"); ctx.textAlign = "left";
  ctx.fillText("avg " + fmt(s.average), pad.l + 6, ay - 6);

  const colorFor = (it) => it.fc ? c("--accent2")
    : items.length > 2 && it.month === s.highest.month ? c("--bad")
    : items.length > 2 && it.month === s.lowest.month ? c("--good") : c("--accent");
  const dim = (i) => (state.hover === -1 || state.hover === i ? 1 : 0.45);
  const whisker = (x, it) => {
    ctx.save();
    ctx.strokeStyle = c("--fg"); ctx.lineWidth = 1.6; ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x, yOf(it.high)); ctx.lineTo(x, yOf(it.low));
    ctx.moveTo(x - 6, yOf(it.high)); ctx.lineTo(x + 6, yOf(it.high));
    ctx.moveTo(x - 6, yOf(it.low)); ctx.lineTo(x + 6, yOf(it.low));
    ctx.stroke();
    ctx.restore();
  };

  if (state.type === "bar") {
    items.forEach((it, i) => {
      const w = Math.min(cw * 0.62, 56), x = pad.l + i * cw + (cw - w) / 2, y = yOf(it.v), col = colorFor(it);
      ctx.globalAlpha = dim(i);
      if (it.fc) {               // projected bar: translucent fill + dashed outline
        ctx.fillStyle = rgba(col, 0.22);
        ctx.beginPath(); rr(ctx, x, y, w, base - y, [8, 8, 0, 0]); ctx.fill();
        ctx.save(); ctx.setLineDash([5, 4]); ctx.strokeStyle = col; ctx.lineWidth = 2;
        ctx.beginPath(); rr(ctx, x + 1, y + 1, w - 2, base - y, [8, 8, 0, 0]); ctx.stroke(); ctx.restore();
      } else {
        const g = ctx.createLinearGradient(0, y, 0, base);
        g.addColorStop(0, col); g.addColorStop(1, rgba(col, 0.55));
        ctx.fillStyle = g;
        ctx.beginPath(); rr(ctx, x, y, w, base - y, [8, 8, 0, 0]); ctx.fill();
      }
      ctx.globalAlpha = 1;
      if (it.fc) whisker(x + w / 2, it);
      if (items.length <= 8 || state.hover === i) {
        ctx.fillStyle = c("--fg"); ctx.textAlign = "center"; ctx.font = "600 12px " + FONT;
        ctx.fillText(fmt(it.v), x + w / 2, (it.fc ? yOf(it.high) : y) - 8);
        ctx.font = "12px " + FONT;
      }
      state.pts.push({ cx: x + w / 2, y, it });
    });
  } else {
    const pts = items.map((it, i) => ({ x: pad.l + i * cw + cw / 2, y: yOf(it.v), it }));
    const hist = pts.filter((p) => !p.it.fc), fp = pts[pts.length - 1];
    const lastH = hist[hist.length - 1];
    const g = ctx.createLinearGradient(0, pad.t, 0, base);
    g.addColorStop(0, rgba(c("--accent"), 0.32)); g.addColorStop(1, rgba(c("--accent"), 0));
    ctx.beginPath(); smoothPath(ctx, hist);
    ctx.lineTo(lastH.x, base); ctx.lineTo(hist[0].x, base); ctx.closePath();
    ctx.fillStyle = g; ctx.fill();
    ctx.strokeStyle = c("--accent"); ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.beginPath(); smoothPath(ctx, hist); ctx.stroke();
    ctx.save();
    ctx.setLineDash([6, 5]); ctx.strokeStyle = c("--accent2"); ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(lastH.x, lastH.y); ctx.lineTo(fp.x, fp.y); ctx.stroke();
    ctx.restore();
    whisker(fp.x, fp.it);
    pts.forEach((p, i) => {
      const r = p.it.fc ? 6 : state.hover === i ? 6.5 : 4.5;
      ctx.globalAlpha = dim(i);
      ctx.fillStyle = c("--panel"); ctx.beginPath(); ctx.arc(p.x, p.y, r + 2, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = colorFor(p.it); ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      if (items.length <= 8 || state.hover === i) {
        ctx.fillStyle = c("--fg"); ctx.textAlign = "center"; ctx.font = "600 12px " + FONT;
        ctx.fillText(fmt(p.it.v), p.x, (p.it.fc ? yOf(p.it.high) : p.y) - 12);
        ctx.font = "12px " + FONT;
      }
      state.pts.push({ cx: p.x, y: p.y, it: p.it });
    });
  }

  // x labels (thinned so they never overlap; aligned to the forecast column)
  const step = Math.max(1, Math.ceil(items.length / Math.max(1, Math.floor((W - pad.l - pad.r) / 50))));
  ctx.fillStyle = c("--muted"); ctx.textAlign = "center";
  items.forEach((it, i) => {
    if ((items.length - 1 - i) % step === 0) {
      ctx.fillStyle = it.fc ? c("--accent2") : c("--muted");
      ctx.font = (it.fc ? "700 " : "") + "12px " + FONT;
      ctx.fillText(it.label, pad.l + i * cw + cw / 2, H - 14);
    }
  });
  ctx.font = "12px " + FONT;

  // tooltip
  const hp = state.pts[state.hover];
  if (hp) {
    const it = hp.it;
    const lines = [it.full, fmt(it.v) + " kWh" + (it.fc ? "  (range " + fmt(it.low) + "–" + fmt(it.high) + ")" : "")];
    if (!it.fc && it.mom !== null && it.mom !== undefined) lines.push(pctText(it.mom) + " vs previous month");
    ctx.font = "600 12px " + FONT;
    let w = ctx.measureText(lines[0]).width;
    ctx.font = "12px " + FONT;
    w = Math.max(w, ...lines.slice(1).map((l) => ctx.measureText(l).width)) + 28;
    const h = lines.length * 18 + 14;
    const x = Math.min(Math.max(hp.cx - w / 2, 4), W - w - 4);
    const y = Math.max(4, Math.min(hp.y - h - 14, H - h - 4));
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,.28)"; ctx.shadowBlur = 16; ctx.shadowOffsetY = 6;
    ctx.fillStyle = c("--panel");
    ctx.beginPath(); rr(ctx, x, y, w, h, 10); ctx.fill();
    ctx.restore();
    ctx.strokeStyle = c("--line"); ctx.lineWidth = 1;
    ctx.beginPath(); rr(ctx, x + 0.5, y + 0.5, w - 1, h - 1, 10); ctx.stroke();
    ctx.fillStyle = colorFor(it); ctx.beginPath(); rr(ctx, x + 10, y + 11, 4, 14, 2); ctx.fill();
    ctx.textAlign = "left";
    lines.forEach((l, i) => {
      ctx.fillStyle = i === 0 ? c("--fg") : c("--muted");
      ctx.font = (i === 0 ? "600 " : "") + "12px " + FONT;
      ctx.fillText(l, x + 20, y + 22 + i * 18);
    });
  }
}

function hoverAt(clientX) {
  if (!state.geo) return;
  const r = $("chart").getBoundingClientRect();
  const i = Math.floor((clientX - r.left - state.geo.l) / state.geo.cw);
  const idx = i >= 0 && i < state.geo.n ? i : -1;
  if (idx !== state.hover) { state.hover = idx; drawChart(); }
}
$("chart").addEventListener("mousemove", (e) => hoverAt(e.clientX));
$("chart").addEventListener("click", (e) => hoverAt(e.clientX));   // tap on touch screens
$("chart").addEventListener("mouseleave", () => { state.hover = -1; drawChart(); });
window.addEventListener("resize", () => { drawChart(); drawSparks(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  try { if (localStorage.getItem("theme")) return; } catch (e) { /* ignore */ }
  applyTheme(resolveTheme());
});

document.querySelectorAll("[data-type]").forEach((b) => b.addEventListener("click", () => {
  state.type = b.dataset.type;
  document.querySelectorAll("[data-type]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  drawChart();
}));
document.querySelectorAll("[data-range]").forEach((b) => b.addEventListener("click", () => {
  state.range = b.dataset.range;
  document.querySelectorAll("[data-range]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  drawChart();
}));

/* ----------------------------------------------------------------- init */
api("GET", "/api/records").then(render).catch(fail);
