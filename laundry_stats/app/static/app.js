const DAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"];
const TYPE_NAME = { washer: "Vaskemaskine", dryer: "Tørretumbler" };
const ICONS = { calendar: "📅", clock: "🕒", wait: "⏳", sleep: "😴", cash: "💸", fire: "🔥", drop: "💧", bolt: "⚡", pause: "⏸️", timer: "⏱️" };
const SVG = {
  washer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="3.5" y="2.5" width="17" height="19" rx="2.5"/><path d="M3.5 7h17"/><circle cx="7" cy="4.8" r=".6" fill="currentColor"/><circle cx="9.5" cy="4.8" r=".6" fill="currentColor"/><circle cx="12" cy="13.5" r="5"/><g class="drum"><path d="M8.6 14.2c1.2-.9 2.2.9 3.4 0s2.2.9 3.4 0"/><circle cx="12" cy="11" r=".5" fill="currentColor"/></g></svg>`,
  dryer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="3.5" y="2.5" width="17" height="19" rx="2.5"/><path d="M3.5 7h17"/><path d="M15 4.8h2.5"/><circle cx="12" cy="13.5" r="5"/><g class="drum"><path d="M10.2 11.5c.8.8-.8 1.6 0 2.4s-.8 1.6 0 2.4M13.8 11.5c.8.8-.8 1.6 0 2.4s-.8 1.6 0 2.4"/></g></svg>`,
};

const state = { range: "30", machine: "", bucket: null, metric: "n", meta: null, view: "dashboard", quiet: false };
const charts = {};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const fmt = (n, d = 0) => Number(n || 0).toLocaleString("da-DK", { maximumFractionDigits: d, minimumFractionDigits: d });
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const colorOf = (type) => css(type === "dryer" ? "--dryer" : "--washer");
const dur = (min) => { const m = Math.round(min || 0); return m >= 60 ? `${Math.floor(m / 60)} t ${m % 60} min` : `${m} min`; };
const kr = (n) => `${fmt(n, 2)} kr`;
const when = (ts) => new Date(ts * 1000).toLocaleString("da-DK", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
const machineOf = (id) => (state.meta?.machines || []).find((m) => m.id === id) || { id, name: id, type: "washer" };

function rangeParams() {
  const now = Math.floor(Date.now() / 1000);
  let start = 0;
  if (state.range === "year") start = Math.floor(new Date(new Date().getFullYear(), 0, 1) / 1000);
  else if (state.range !== "all") start = now - Number(state.range) * 86400;
  const p = new URLSearchParams({ start, end: now + 60 });
  if (state.machine) p.set("machine", state.machine);
  return p;
}

const autoBucket = () => (state.range === "7" || state.range === "30" ? "day" : state.range === "90" ? "week" : "month");

async function api(path, extra = {}, withRange = true) {
  const p = withRange ? rangeParams() : new URLSearchParams();
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  const r = await fetch(`api/${path}${p.toString() ? `?${p}` : ""}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function chart(id) {
  const el = document.getElementById(id);
  if (charts[id] && charts[id].getDom() !== el) charts[id].dispose();
  if (!charts[id] || charts[id].isDisposed()) charts[id] = echarts.init(el, null, { renderer: "canvas" });
  return charts[id];
}

function baseOption() {
  const text = css("--muted"), line = css("--line");
  return {
    animation: !state.quiet,
    textStyle: { color: text, fontFamily: "inherit" },
    grid: { left: 44, right: 12, top: 34, bottom: 30 },
    tooltip: { trigger: "axis", backgroundColor: css("--card"), borderColor: line, textStyle: { color: css("--text") } },
    legend: { top: 0, textStyle: { color: text }, itemWidth: 10, itemHeight: 10 },
    xAxis: { type: "category", axisLine: { lineStyle: { color: line } }, axisTick: { show: false } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: line } } },
  };
}

function empty(id, text = "Ingen ture i perioden") {
  const c = charts[id];
  if (c && !c.isDisposed()) c.dispose();
  document.getElementById(id).innerHTML = `<div class="empty">${text}</div>`;
}

// --- live --------------------------------------------------------------------------

function renderLive(list) {
  $("#live").innerHTML = list.map((m) => {
    const c = colorOf(m.type);
    let sub = "Klar";
    let bar = "";
    if (m.running) {
      sub = `Startet ${clock(m.started_at)} · kørt ${dur(m.minutes)}`;
      if (m.expected_end) {
        const left = Math.max(0, Math.round((m.expected_end * 1000 - Date.now()) / 60000));
        sub += ` · færdig ca. ${clock(m.expected_end)} (${left ? `om ${dur(left)}` : "snart"})`;
        bar = `<progress max="${m.expected_minutes}" value="${Math.min(m.minutes, m.expected_minutes)}"></progress>`;
      }
    } else if (m.updated == null) {
      sub = "Venter på data fra Home Assistant";
    }
    const watt = m.watt == null ? "–" : fmt(m.watt);
    return `<div class="machine ${m.running ? "running" : ""}" style="--c:${c}">
      <div class="ico">${SVG[m.type] || SVG.washer}</div>
      <div class="info"><div class="name">${esc(m.name)} <span class="pill ${m.running ? "on" : ""}">${m.running ? "KØRER" : "SLUKKET"}</span></div>
      <div class="sub">${sub}</div>${bar}</div>
      <div class="watt">${watt} <small>W</small></div></div>`;
  }).join("");
}

// --- dashboard -----------------------------------------------------------------------

function delta(cur, prev, kind = "neutral") {
  if (!prev) return `<div class="delta">&nbsp;</div>`;
  const pct = ((cur - prev) / prev) * 100;
  const cls = Math.abs(pct) < 1 || kind === "neutral" ? "" : pct > 0 ? "up" : "down";
  return `<div class="delta ${cls}">${pct > 0 ? "▲" : "▼"} ${fmt(Math.abs(pct))} % vs. forrige periode</div>`;
}
const kpi = (l, v, d = `<div class="delta">&nbsp;</div>`) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div>${d}</div>`;
const note = (t) => `<div class="delta">${t}</div>`;

function renderKpis(s) {
  const p = s.previous || {};
  const byType = (t) => s.machines.filter((m) => m.type === t);
  const avg = (t, key) => { const ms = byType(t); const n = ms.reduce((a, m) => a + m.n, 0); return n ? ms.reduce((a, m) => a + m[key] * m.n, 0) / n : 0; };
  const cards = [kpi("Ture", fmt(s.n), delta(s.n, p.n))];
  if (byType("washer").length) cards.push(kpi("Vaske", fmt(s.washes), note(`${fmt(s.per_week, 1)} ture om ugen i alt`)));
  if (byType("dryer").length) cards.push(kpi("Tørringer", fmt(s.dries), note(s.dried_share != null ? `${fmt(s.dried_share * 100)} % af vaskene tørres` : "&nbsp;")));
  cards.push(kpi("Strøm", `${fmt(s.kwh, 1)} kWh`, delta(s.kwh, p.kwh, "cost")));
  cards.push(kpi("Pris", kr(s.cost), delta(s.cost, p.cost, "cost")));
  if (byType("washer").length) cards.push(kpi("Pris pr. vask", kr(avg("washer", "avg_cost")), note(`${dur(avg("washer", "avg_minutes"))} i snit`)));
  if (byType("dryer").length) cards.push(kpi("Pris pr. tørring", kr(avg("dryer", "avg_cost")), note(`${dur(avg("dryer", "avg_minutes"))} i snit`)));
  if (s.wait_median != null) cards.push(kpi("Ventetid", dur(s.wait_median), note("fra vask til tørretumbler")));
  $("#kpis").innerHTML = cards.join("");

  $("#machines").innerHTML = `<tr><th>Maskine</th><th>Ture</th><th>Tid i snit</th><th>kWh i snit</th><th>Pris i snit</th><th>kWh i alt</th><th>Pris i alt</th></tr>` +
    s.machines.map((m) => `<tr><td><span class="dot" style="--c:${colorOf(m.type)}"></span>${esc(m.name)}</td><td>${fmt(m.n)}</td>
      <td>${dur(m.avg_minutes)}</td><td>${fmt(m.avg_kwh, 2)}</td><td>${kr(m.avg_cost)}</td><td>${fmt(m.kwh, 1)}</td><td>${kr(m.cost)}</td></tr>`).join("");
}

function fmtLabel(iso, bucket) {
  const d = new Date(iso + "T00:00:00");
  if (bucket === "month") return d.toLocaleDateString("da-DK", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("da-DK", { day: "numeric", month: "short" });
}

function renderTimeline(t, bucket) {
  if (!t.buckets.length) return empty("timeline");
  const unit = { n: "ture", kwh: "kWh", cost: "kr" }[state.metric];
  const o = baseOption();
  o.xAxis.data = t.buckets.map((b) => fmtLabel(b, bucket));
  o.yAxis.name = unit;
  o.tooltip.valueFormatter = (v) => `${fmt(v, state.metric === "n" ? 0 : 2)} ${unit}`;
  o.series = t.machines.map((m) => ({
    name: m.name, type: "bar", stack: "a", barMaxWidth: 26, data: m[state.metric],
    itemStyle: { color: colorOf(m.type), borderRadius: 2 },
  }));
  // two machines of the same type need telling apart
  const seen = {};
  o.series.forEach((s, i) => { const ty = t.machines[i].type; if (seen[ty]) s.itemStyle.opacity = 0.55; seen[ty] = true; });
  chart("timeline").setOption(o, true);
}

function renderHeatmap(cells) {
  if (!cells.length) return empty("heatmap");
  const max = Math.max(...cells.map((c) => c[2]));
  chart("heatmap").setOption({
    animation: !state.quiet,
    tooltip: { formatter: (p) => `${DAYS[p.value[1]]} kl. ${p.value[0]}: ${p.value[2]} ture`, backgroundColor: css("--card"), borderColor: css("--line"), textStyle: { color: css("--text") } },
    grid: { left: 40, right: 12, top: 10, bottom: 50 },
    xAxis: { type: "category", data: [...Array(24).keys()], splitArea: { show: true }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: css("--muted") } },
    yAxis: { type: "category", data: DAYS, inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: css("--muted") } },
    visualMap: { min: 0, max, calculable: false, orient: "horizontal", left: "center", bottom: 0, itemHeight: 120, itemWidth: 10,
      inRange: { color: [css("--accent-soft"), css("--accent")] }, textStyle: { color: css("--muted") } },
    series: [{ type: "heatmap", data: cells.map(([d, h, n]) => [h, d, n]), itemStyle: { borderColor: css("--card"), borderWidth: 2, borderRadius: 3 } }],
  }, true);
}

function renderDurations(d) {
  if (!d.bins.length) return empty("durations");
  const o = baseOption();
  o.xAxis.data = d.bins;
  o.xAxis.name = "min";
  o.yAxis.name = "ture";
  o.yAxis.minInterval = 1;
  o.series = d.machines.map((m) => ({ name: m.name, type: "bar", barGap: "10%", data: m.counts, itemStyle: { color: colorOf(m.type), borderRadius: 2 } }));
  chart("durations").setOption(o, true);
}

function renderInsights(list) {
  $("#insights").innerHTML = list.length
    ? list.map((i) => `<li><span class="ico">${ICONS[i.icon] || "•"}</span><span>${esc(i.text)}</span></li>`).join("")
    : `<li class="muted">Ingen indsigt endnu – der skal et par ture til.</li>`;
}

function cycleRows(rows) {
  if (!rows.length) return `<tr><td class="empty">Ingen ture i perioden</td></tr>`;
  return `<tr><th>Maskine</th><th>Start</th><th>Tid</th><th>kWh</th><th>Pris</th><th></th></tr>` + rows.map((r) => {
    const m = machineOf(r.machine);
    const tags = [r.heat_minutes ? `<span class="tag heat">varme ${r.heat_minutes} min</span>` : "",
      r.excluded ? `<span class="tag" title="Startet mens ${esc(m.skip_entity || "skip_entity")} var aktiv">udeladt</span>` : ""].join(" ");
    return `<tr class="link" onclick="location.hash='#/cycle/${r.id}'"><td><span class="dot" style="--c:${colorOf(r.type)}"></span>${esc(m.name)}</td>
      <td>${when(r.started_at)}</td><td>${dur(r.minutes)}</td><td>${fmt(r.kwh, 2)}</td><td>${kr(r.cost)}</td><td class="grow">${tags}</td></tr>`;
  }).join("");
}

async function loadDashboard() {
  const bucket = state.bucket || autoBucket();
  document.querySelectorAll("#bucket button").forEach((b) => b.classList.toggle("on", b.dataset.bucket === bucket));
  const [s, t, h, d, ins, rec] = await Promise.all([
    api("summary"), api("timeline", { bucket }), api("heatmap"), api("durations"), api("insights"), api("cycles", { limit: 8 }),
  ]);
  renderKpis(s);
  renderTimeline(t, bucket);
  renderHeatmap(h);
  renderDurations(d);
  renderInsights(ins);
  $("#recent").innerHTML = cycleRows(rec);
  state.timeline = { t, bucket };
}

async function loadCycles() {
  const rows = await api("cycles", { limit: 500 });
  $("#cycles-hint").textContent = `${rows.length} ture`;
  $("#all-cycles").innerHTML = cycleRows(rows);
}

// --- one cycle ---------------------------------------------------------------------------

async function loadCycle(id) {
  let c;
  try { c = await api(`cycle/${id}`, {}, false); } catch { $("#cycle-hero").innerHTML = `<div class="empty">Turen findes ikke</div>`; return; }
  const m = machineOf(c.machine);
  const col = colorOf(c.type);
  $("#cycle-hero").innerHTML = `<div class="ico" style="--c:${col}">${SVG[c.type]}</div>
    <div><h2>${esc(m.name)}</h2><div class="sub">${when(c.started_at)} – ${clock(c.ended_at)}${c.excluded ? " · udeladt af statistikken" : ""}</div></div>`;
  $("#cycle-kpis").innerHTML = [
    kpi("Varighed", dur(c.minutes)), kpi("Strøm", `${fmt(c.kwh, 2)} kWh`), kpi("Pris", kr(c.cost), note(`${fmt(c.price, 2)} kr/kWh`)),
    kpi("Højeste effekt", `${fmt(c.peak_w)} W`), kpi("Opvarmning", dur(c.heat_minutes), note(c.kwh ? `${fmt((c.heat_kwh / c.kwh) * 100)} % af strømmen` : "&nbsp;")),
  ].join("");
  const o = baseOption();
  o.xAxis.data = c.profile.map((_, i) => i);
  o.xAxis.name = "min";
  o.yAxis.name = "W";
  o.tooltip.formatter = (ps) => ps.map((p) => `${p.marker}${esc(p.seriesName)}: ${fmt(p.value)} W`).join("<br>") + `<br><span style="color:${css("--muted")}">minut ${ps[0].axisValue}</span>`;
  const sim = c.similar[0];
  o.series = [{ name: "Denne tur", type: "line", step: "end", symbol: "none", data: c.profile, lineStyle: { color: col, width: 2 }, itemStyle: { color: col },
    areaStyle: { color: col, opacity: 0.12 } }];
  if (sim) {
    o.xAxis.data = [...Array(Math.max(c.profile.length, sim.profile.length)).keys()];
    o.series.push({ name: `Mest lig (${when(sim.started_at)})`, type: "line", step: "end", symbol: "none", data: sim.profile,
      lineStyle: { color: css("--muted"), width: 1, type: "dashed" }, itemStyle: { color: css("--muted") } });
  }
  chart("cycle-chart").setOption(o, true);
  $("#cycle-similar").innerHTML = c.similar.length
    ? c.similar.map((s) => `<li><a href="#/cycle/${s.id}"><span>${when(s.started_at)}</span><span class="count">${dur(s.minutes)} · ${fmt(s.kwh, 2)} kWh · ${kr(s.cost)}</span></a></li>`).join("")
    : `<li class="muted">Ingen andre ture endnu</li>`;
  const p = c.pair;
  $("#cycle-pair").innerHTML = p
    ? `<p>${c.type === "washer" ? "Tøjet kom i tørretumbleren" : "Tøjet kom fra vaskemaskinen"} <b>${dur(p.wait)}</b> ${c.type === "washer" ? "efter vasken" : "efter vasken var færdig"}.</p>
       <ol class="top"><li><a href="#/cycle/${p.wash.id}"><span>Vask ${when(p.wash.started_at)}</span><span class="count">${dur(p.wash.minutes)} · ${kr(p.wash.cost)}</span></a></li>
       <li><a href="#/cycle/${p.dry.id}"><span>Tørring ${when(p.dry.started_at)}</span><span class="count">${dur(p.dry.minutes)} · ${kr(p.dry.cost)}</span></a></li></ol>
       <p class="muted">Tilsammen ${kr((p.wash.cost || 0) + (p.dry.cost || 0))} og ${fmt(p.wash.kwh + p.dry.kwh, 2)} kWh.</p>`
    : `<p class="muted">${c.type === "washer" ? "Tøjet fra denne vask kom ikke i tørretumbleren (inden for 12 timer)." : "Ingen vask lige før denne tørring."}</p>`;
}

// --- setup ----------------------------------------------------------------------------------

function renderSetup() {
  const m = state.meta;
  $("#setup-machines").innerHTML = `<tr><th>Maskine</th><th>Sensor</th><th>Start</th><th>Færdig</th><th>Mindst</th><th>Udelad når</th></tr>` +
    m.machines.map((x) => `<tr><td><span class="dot" style="--c:${colorOf(x.type)}"></span>${esc(x.name)} <span class="tag">${TYPE_NAME[x.type]}</span></td>
      <td><code>${esc(x.power_entity || "mangler")}</code></td>
      <td>over ${fmt(x.start_watt)} W${x.start_seconds ? ` i ${x.start_seconds} sek` : ""}</td>
      <td>under ${fmt(x.stop_watt)} W i ${fmt(x.stop_minutes, 1)} min</td><td>${x.min_minutes} min</td>
      <td class="grow">${x.skip_entity ? `<code>${esc(x.skip_entity)}</code> er aktiv` : "–"}</td></tr>`).join("");
  const ha = m.home_assistant;
  $("#ha-hint").textContent = m.price.entity ? `pris fra ${m.price.entity}` : `fast pris ${fmt(m.price.fixed, 2)} kr/kWh`;
  $("#ha-status").innerHTML = !ha.available ? "Ingen forbindelse til Home Assistant (kører uden for Home Assistant)."
    : `Sensorer: ${ha.sensors_enabled ? `${ha.sensors} sendt${ha.last_update ? `, senest ${clock(ha.last_update)}` : ""}` : "slået fra"}.
       Når en tur er færdig, sendes eventet <code>${esc(ha.event)}</code>${ha.notify_services.length ? ` og en besked til ${ha.notify_services.map((s) => `<code>${esc(s)}</code>`).join(", ")}` : ""}.`;
  $("#ha-sensors").innerHTML = (ha.entities || []).map((e) => `<li>${esc(e)}</li>`).join("");
  const col = m.collector;
  $("#import-status").innerHTML = !col.enabled ? "Opsamlingen kører ikke."
    : col.importing ? "Læser historikken fra Home Assistant …"
    : `Første start læste de seneste ${col.import_days} dage fra Home Assistants historik (så langt tilbage, som recorderen gemmer).
       ${m.first_cycle ? `Første tur: ${when(m.first_cycle)}.` : ""} Ture, der allerede er gemt, springes over.`;
  $("#import-btn").disabled = !col.enabled || col.importing;
}

// --- plumbing ---------------------------------------------------------------------------------

function setStatus() {
  const c = state.meta?.collector;
  const el = $("#status");
  if (!c || !c.enabled) { el.className = "status"; el.title = "Viser gemte data – ingen forbindelse til Home Assistant"; return; }
  el.className = `status ${c.last_error ? "err" : "ok"}`;
  el.title = c.last_error ? `Fejl: ${c.last_error}` : c.last_poll ? `Opdateret ${clock(c.last_poll)}` : "Starter …";
}

function route() {
  const hash = location.hash || "#/";
  const [, view, id] = hash.split("/");
  state.view = view === "cycle" ? "cycle" : ["cycles", "setup"].includes(view) ? view : "dashboard";
  document.querySelectorAll(".view").forEach((v) => (v.hidden = v.id !== `view-${state.view}`));
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === state.view));
  state.cycleId = id;
  load();
}

async function load(quiet = false) {
  state.quiet = quiet;
  try {
    if (state.view === "dashboard") await loadDashboard();
    else if (state.view === "cycles") await loadCycles();
    else if (state.view === "cycle") await loadCycle(state.cycleId);
    else if (state.view === "setup") { state.meta = await api("meta", {}, false); renderSetup(); }
  } catch (e) { console.error(e); }
  $("#export").href = `api/export.csv?${rangeParams()}`;
}

async function refreshLive() {
  try { renderLive(await api("live", {}, false)); } catch (e) { console.error(e); }
}

let marker = null;
async function tick() {
  await refreshLive();
  try {
    state.meta = await api("meta", {}, false);
    setStatus();
    const { marker: m } = await api("latest", {}, false);
    if (marker !== null && m !== marker) load(true);
    marker = m;
  } catch (e) { console.error(e); }
}

async function init() {
  state.meta = await api("meta", {}, false);
  setStatus();
  const sel = $("#machine");
  for (const m of state.meta.machines) sel.insertAdjacentHTML("beforeend", `<option value="${esc(m.id)}">${esc(m.name)}</option>`);
  if (state.meta.machines.length < 2) sel.hidden = true;
  sel.onchange = () => { state.machine = sel.value; load(); };
  document.querySelectorAll("#range button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("on", x === b));
    state.range = b.dataset.range; state.bucket = null; load();
  }));
  document.querySelectorAll("#bucket button").forEach((b) => (b.onclick = () => { state.bucket = b.dataset.bucket; load(); }));
  document.querySelectorAll("#metric button").forEach((b) => (b.onclick = () => {
    document.querySelectorAll("#metric button").forEach((x) => x.classList.toggle("on", x === b));
    state.metric = b.dataset.metric;
    if (state.timeline) renderTimeline(state.timeline.t, state.timeline.bucket);
  }));
  $("#import-btn").onclick = async () => {
    $("#import-btn").disabled = true;
    await fetch("api/reimport", { method: "POST" });
    setTimeout(async () => { state.meta = await api("meta", {}, false); renderSetup(); }, 1500);
  };
  window.addEventListener("hashchange", route);
  window.addEventListener("resize", () => Object.values(charts).forEach((c) => !c.isDisposed() && c.resize()));
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => load(true));
  route();
  refreshLive();
  setInterval(tick, 15000);
}

init();
