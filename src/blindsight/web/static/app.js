"use strict";
// Reine Darstellung und Eingabe. Alle Berechnungen laufen im Python Kern.
const $ = (s) => document.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"];
const col = (p) => PALETTE[(p - 1) % PALETTE.length];
const UNIT = { mm: 1, cm: 10, in: 25.4 };
const LIST_KINDS = ["list", "listint", "liststr"];
const LEN_LISTS = new Set(["stack.gaps", "stack.distances", "stack.thicknesses"]);
let unit = "mm", cfg = null, schema = null, defaults = null;
let jobId = null, poll = null, livePoll = null;
let lastGeo = null, lastResult = null, solIndex = 0, solCache = {};
let editMode = false, edited = false, selUnit = null, validateTimer = null;
let drawing = false, rot = { a: 35, tilt: 0.55 };

const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
const set = (o, p, v) => { const ks = p.split("."); const l = ks.pop(); ks.reduce((a, k) => a[k], o)[l] = v; };
const round = (v, n = 4) => (v == null || isNaN(v) ? v : Math.round(v * 10 ** n) / 10 ** n);
const toU = (mm) => round(mm / UNIT[unit]);
const fromU = (v) => v * UNIT[unit];
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const lenLabel = (l, kind, p) => (kind === "len" || LEN_LISTS.has(p) ? `${l} [${unit}]` : l);

function el(name, attrs = {}, parent) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", body: JSON.stringify(body) });
  const ct = r.headers.get("Content-Type") || "";
  if (ct.includes("json")) return { status: r.status, data: await r.json() };
  return { status: r.status, data: await r.text() };
}

// --- Formulare aus dem Schema ------------------------------------------------------
const GROUP_TARGET = { general: "f-general", rod: "f-rod", motor: "f-motor", stack: "f-stack", bounds: "f-bounds", search: "f-search" };

function buildForms() {
  for (const id of Object.values(GROUP_TARGET)) $("#" + id).innerHTML = "";
  for (const f of schema.fields) {
    if (f.group === "weights") continue;
    const box = $("#" + GROUP_TARGET[f.group]);
    const l = document.createElement("label");
    l.textContent = lenLabel(f.label, f.kind, f.path); l.title = f.tip; l.dataset.labelFor = f.path;
    box.appendChild(l);
    let inp;
    if (f.kind === "enum") {
      inp = document.createElement("select");
      for (const [v, t] of f.options) inp.add(new Option(t, v));
    } else {
      inp = document.createElement("input");
      inp.type = f.kind === "text" || LIST_KINDS.includes(f.kind) ? "text" : "number";
      inp.step = "any";
    }
    inp.title = f.tip; inp.dataset.path = path(f); inp.dataset.kind = f.kind; inp.dataset.optional = f.optional ? "1" : "";
    inp.id = "in-" + f.path.replace(/\./g, "-");
    inp.addEventListener("change", () => { readInput(inp); refresh(); });
    box.appendChild(inp);
  }
  buildWeights();
}
const path = (f) => f.path;

function readInput(inp) {
  const k = inp.dataset.kind, p = inp.dataset.path; let v = inp.value;
  if (v.trim() === "" && inp.dataset.optional) { set(cfg, p, null); return; }
  if (k === "len") v = fromU(parseFloat(v));
  else if (k === "num") v = parseFloat(v);
  else if (k === "int") v = parseInt(v, 10);
  else if (k === "list") { v = v.trim() === "" ? [] : v.split(/[,; ]+/).filter(Boolean).map(parseFloat); if (LEN_LISTS.has(p)) v = v.map(fromU); }
  else if (k === "listint") v = v.split(/[,; ]+/).filter(Boolean).map((x) => parseInt(x, 10));
  else if (k === "liststr") v = v.split(/[,; ]+/).filter(Boolean);
  set(cfg, p, v);
}

function writeInputs() {
  for (const inp of document.querySelectorAll("[data-path]")) {
    const k = inp.dataset.kind, v = get(cfg, inp.dataset.path);
    if (v == null) inp.value = "";
    else if (k === "len") inp.value = toU(v);
    else if (k === "list") inp.value = v.map((x) => (LEN_LISTS.has(inp.dataset.path) ? toU(x) : round(x))).join(", ");
    else if (LIST_KINDS.includes(k)) inp.value = v.join(", ");
    else inp.value = v;
  }
  for (const l of document.querySelectorAll("[data-label-for]")) {
    const f = schema.fields.find((x) => x.path === l.dataset.labelFor);
    l.textContent = lenLabel(f.label, f.kind, f.path);
  }
  writeWeights(); renderPlaneTable(); renderObstacles(); renderZones();
}

function showFieldErrors(errors) {
  document.querySelectorAll(".err").forEach((e) => e.classList.remove("err"));
  document.querySelectorAll(".errmsg").forEach((e) => e.remove());
  const rest = [];
  for (const msg of errors) {
    const m = /^([\w.\[\]]+)\. (.*)$/.exec(msg);
    const inp = m && document.querySelector(`[data-path="${m[1]}"]`);
    if (inp) {
      inp.classList.add("err");
      const d = document.createElement("div"); d.className = "errmsg"; d.textContent = m[2];
      inp.insertAdjacentElement("afterend", d);
    } else rest.push(msg);
  }
  const b = $("#banner");
  b.hidden = errors.length === 0;
  b.innerHTML = errors.length ? "<ul>" + errors.map((e) => `<li>${esc(e)}</li>`).join("") + "</ul>" : "";
}

// --- Gewichte ------------------------------------------------------------------------
const WEIGHTS = [["count", "Anzahl Stangen"], ["area", "Kleine Grundflaeche"], ["uniformity", "Gleichmaessige Verteilung"], ["regularity", "Regelmaessiges Muster"]];
const PRESETS = { count: [20, 3, 1, 1], area: [8, 20, 2, 1], uniform: [6, 3, 15, 4], balanced: [10, 8, 2, 1] };
function buildWeights() {
  const box = $("#weights"); box.innerHTML = "";
  for (const [k, label] of WEIGHTS) {
    const l = document.createElement("label"); l.textContent = label; box.appendChild(l);
    const r = document.createElement("input"); r.type = "range"; r.min = 0; r.max = 20; r.step = 0.5; r.dataset.w = k;
    const n = document.createElement("span"); n.id = "wv-" + k;
    r.addEventListener("input", () => { cfg.search.weights[k] = parseFloat(r.value); n.textContent = r.value; });
    box.append(r, n);
  }
}
function writeWeights() {
  for (const [k] of WEIGHTS) { const r = document.querySelector(`[data-w=${k}]`); r.value = cfg.search.weights[k]; $("#wv-" + k).textContent = cfg.search.weights[k]; }
}

// --- Tabellen: Ebenen, Hindernisse, Montagebereiche ----------------------------------------
function renderPlaneTable() {
  const n = cfg.stack.n_motor_planes; const s = cfg.stack;
  if (!(n >= 1 && n <= 200)) { $("#planeTable").innerHTML = ""; return; }
  let h = `<table class="grid"><tr><th>Ebene</th><th>erlaubt</th><th>max. Motoren</th><th>Winkel (Grad)</th><th>Dicke [${unit}]</th></tr>`;
  for (let i = 1; i <= n; i++) {
    const allowed = s.allowed_planes == null || s.allowed_planes.includes(i);
    const th = s.thicknesses && s.thicknesses[i - 1] != null ? toU(s.thicknesses[i - 1]) : "";
    h += `<tr><td>G${i}</td><td><input type="checkbox" data-pt="allowed" data-i="${i}" ${allowed ? "checked" : ""}></td>
      <td><input type="number" min="0" step="1" data-pt="cap" data-i="${i}" value="${s.max_per_plane[i] ?? ""}"></td>
      <td><input type="text" data-pt="ang" data-i="${i}" value="${(s.plane_angles[i] || []).join(", ")}"></td>
      <td><input type="number" step="any" min="0" data-pt="th" data-i="${i}" value="${th}" placeholder="${toU(s.thickness)}"></td></tr>`;
  }
  const box = $("#planeTable"); box.innerHTML = h + "</table>";
  box.querySelectorAll("input").forEach((inp) => inp.addEventListener("change", () => { readPlaneTable(); refresh(); }));
}
function readPlaneTable() {
  const n = cfg.stack.n_motor_planes, s = cfg.stack;
  const allowed = [], cap = {}, ang = {}; const th = []; let anyTh = false, allAllowed = true;
  for (let i = 1; i <= n; i++) {
    const q = (t) => document.querySelector(`[data-pt=${t}][data-i="${i}"]`);
    if (q("allowed").checked) allowed.push(i); else allAllowed = false;
    if (q("cap").value !== "") cap[i] = parseInt(q("cap").value, 10);
    const a = q("ang").value.split(/[,; ]+/).filter(Boolean).map(parseFloat); if (a.length) ang[i] = a;
    if (q("th").value !== "") { th.push(fromU(parseFloat(q("th").value))); anyTh = true; } else th.push(s.thickness);
  }
  s.allowed_planes = allAllowed ? null : allowed; s.max_per_plane = cap; s.plane_angles = ang; s.thicknesses = anyTh ? th : null;
}

const OBS_COLS = [["shape", "Form", "sel"], ["x", "x", "len"], ["y", "y", "len"], ["w", "Breite", "len"], ["h", "Hoehe", "len"], ["r", "Radius", "len"], ["angle", "Winkel", "num"], ["plane", "Ebene", "int"], ["name", "Name", "text"]];
function renderObstacles() {
  let h = "<table class=\"grid\"><tr>" + OBS_COLS.map(([, l, k]) => `<th>${l}${k === "len" ? ` [${unit}]` : ""}</th>`).join("") + "<th></th></tr>";
  cfg.obstacles.forEach((o, i) => {
    h += "<tr>" + OBS_COLS.map(([f, , k]) => {
      if (k === "sel") return `<td><select data-ob="${i}" data-f="${f}"><option value="rect" ${o.shape === "rect" ? "selected" : ""}>Rechteck</option><option value="circle" ${o.shape === "circle" ? "selected" : ""}>Kreis</option></select></td>`;
      const v = o[f]; const val = v == null ? "" : k === "len" ? toU(v) : v;
      return `<td><input ${k === "text" ? "type=text" : "type=number step=any"} data-ob="${i}" data-f="${f}" value="${esc(val)}"></td>`;
    }).join("") + `<td><button data-obdel="${i}">x</button></td></tr>`;
  });
  const box = $("#obsTable"); box.innerHTML = h + "</table>";
  box.querySelectorAll("[data-ob]").forEach((inp) => inp.addEventListener("change", () => {
    const o = cfg.obstacles[+inp.dataset.ob], f = inp.dataset.f, k = OBS_COLS.find((c) => c[0] === f)[2];
    if (k === "sel" || k === "text") o[f] = inp.value;
    else if (inp.value === "") o[f] = f === "plane" ? null : 0;
    else o[f] = k === "len" ? fromU(parseFloat(inp.value)) : k === "int" ? parseInt(inp.value, 10) : parseFloat(inp.value);
    refresh();
  }));
  box.querySelectorAll("[data-obdel]").forEach((b) => b.addEventListener("click", () => { cfg.obstacles.splice(+b.dataset.obdel, 1); renderObstacles(); refresh(); }));
}
function renderZones() {
  const rows = [];
  for (const [pl, zs] of Object.entries(cfg.stack.mount_zones || {})) zs.forEach((z, j) => rows.push([pl, j, z]));
  let h = `<table class="grid"><tr><th>Ebene</th>${["x min", "y min", "x max", "y max"].map((t) => `<th>${t} [${unit}]</th>`).join("")}<th></th></tr>`;
  rows.forEach(([pl, j, z]) => {
    h += `<tr><td><input type="number" min="1" step="1" data-z="${pl}:${j}" data-f="plane" value="${pl}"></td>` +
      z.map((v, q) => `<td><input type="number" step="any" data-z="${pl}:${j}" data-f="${q}" value="${toU(v)}"></td>`).join("") +
      `<td><button data-zdel="${pl}:${j}">x</button></td></tr>`;
  });
  const box = $("#zoneTable"); box.innerHTML = h + "</table>";
  box.querySelectorAll("[data-z]").forEach((inp) => inp.addEventListener("change", () => { readZones(); refresh(); }));
  box.querySelectorAll("[data-zdel]").forEach((b) => b.addEventListener("click", () => {
    const [pl, j] = b.dataset.zdel.split(":"); cfg.stack.mount_zones[pl].splice(+j, 1);
    if (!cfg.stack.mount_zones[pl].length) delete cfg.stack.mount_zones[pl];
    renderZones(); refresh();
  }));
}
function readZones() {
  const out = {};
  const rows = {};
  document.querySelectorAll("#zoneTable [data-z]").forEach((inp) => { (rows[inp.dataset.z] ||= {})[inp.dataset.f] = inp.value; });
  for (const r of Object.values(rows)) {
    const pl = String(parseInt(r.plane, 10));
    (out[pl] ||= []).push([0, 1, 2, 3].map((q) => fromU(parseFloat(r[q]))));
  }
  cfg.stack.mount_zones = out;
}

// --- Motor Vorschau (Geometrie Reiter, nur Anzeige. Bearbeiten im Reiter Motor Skizze) ----------------------
function motorPolygonRod(m) {
  // Gehaeusekontur im Stangenrahmen (Ursprung = Stangenachse, y nach oben). Mit Skizze direkt deren Punkte.
  if (m.sketch && m.sketch.points && m.sketch.points.length >= 3) return m.sketch.points;
  const top = m.outline && m.outline.length ? Math.max(...m.outline.map((p) => p[1])) : m.depth / 2;
  const rx = m.shaft_x + m.center_distance, ry = top + m.gear_gap + m.gear_width / 2;
  const poly = m.outline && m.outline.length >= 3 ? m.outline : [[-m.width / 2, -m.depth / 2], [m.width / 2, -m.depth / 2], [m.width / 2, m.depth / 2], [-m.width / 2, m.depth / 2]];
  return poly.map(([x, y]) => [x - rx, y - ry]);
}
function drawMotor() {
  const svg = $("#motorPreview"); svg.innerHTML = "";
  const m = cfg.motor, r = cfg.rod.diameter / 2;
  if (![m.width, m.depth, cfg.rod.diameter, m.gear_diameter, m.gear_width].every((v) => v > 0)) return;
  const poly = motorPolygonRod(m), gr = m.gear_diameter / 2, gh = m.gear_width / 2, cd = m.center_distance;
  const xs = poly.map((p) => p[0]).concat([-cd - gr, -cd + gr, r, -r]), ys = poly.map((p) => p[1]).concat([-gh, gh, r, -r]);
  const pad = 8, x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  svg.setAttribute("viewBox", `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`);
  const Y = (y) => -y, sw = (x1 - x0) / 300;
  el("polygon", { points: poly.map((p) => `${p[0]},${Y(p[1])}`).join(" "), fill: "#999", "fill-opacity": 0.5, stroke: "#555", "stroke-width": sw }, svg);
  el("rect", { x: -cd - gr, y: Y(gh), width: 2 * gr, height: 2 * gh, fill: "#f28e2b", stroke: "#333", "stroke-width": sw }, svg);
  el("circle", { cx: 0, cy: 0, r: r + cfg.rod.hole_clearance, fill: "none", stroke: "currentColor", "stroke-dasharray": `${sw * 3} ${sw * 3}`, "stroke-width": sw }, svg);
  el("circle", { id: "previewRod", cx: 0, cy: 0, r, fill: "#222" }, svg);
  el("line", { x1: -cd, y1: 0, x2: 0, y2: 0, stroke: "#e00", "stroke-width": sw, "stroke-dasharray": `${sw * 3} ${sw * 3}` }, svg);
  const sk = !!(m.sketch && m.sketch.points && m.sketch.points.length);
  $("#sketchNote").hidden = !sk;
  for (const f of ["motor.width", "motor.depth", "motor.shaft_x", "motor.gear_gap"]) { const inp = document.querySelector(`[data-path="${f}"]`); if (inp) { inp.disabled = sk; inp.title = sk ? "Wird von der Motor Skizze bestimmt" : ""; } }
}
function svgPoint(svg, ev) { const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY; const p = pt.matrixTransform(svg.getScreenCTM().inverse()); return [p.x, -p.y]; }
function initMotorPreview() {
  $("#btnOpenSketch").addEventListener("click", () => switchTab("sketch"));
  $("#btnDropSketch").addEventListener("click", () => { cfg.motor.sketch = null; writeInputs(); refresh(); if (window.skReload) skReload(); });
}

// --- Motor Bibliothek ------------------------------------------------------------------------
function libLoad() { try { return JSON.parse(localStorage.getItem("blindsight.motors") || "{}"); } catch (e) { return {}; } }
function libStore(obj) { try { localStorage.setItem("blindsight.motors", JSON.stringify(obj)); return true; } catch (e) { alert("Speichern im Browser nicht moeglich."); return false; } }
function libRender() { const l = libLoad(); $("#libSel").innerHTML = Object.keys(l).map((n) => `<option>${esc(n)}</option>`).join(""); }
function initLibrary() {
  libRender();
  $("#libSave").addEventListener("click", () => { const n = $("#libName").value.trim(); if (!n) return; const l = libLoad(); l[n] = cfg.motor; if (libStore(l)) libRender(); });
  $("#libLoad").addEventListener("click", () => { const l = libLoad(), n = $("#libSel").value; if (l[n]) { cfg.motor = { ...defaults.motor, ...l[n] }; writeInputs(); refresh(); if (window.skReload) skReload(); } });
  $("#libDel").addEventListener("click", () => { const l = libLoad(); delete l[$("#libSel").value]; libStore(l); libRender(); });
  $("#libExport").addEventListener("click", () => download("blindsight-motor.json", JSON.stringify(cfg.motor, null, 2), "application/json"));
  $("#libImport").addEventListener("change", async (e) => { const f = e.target.files[0]; if (!f) return; try { cfg.motor = { ...defaults.motor, ...JSON.parse(await f.text()) }; writeInputs(); refresh(); if (window.skReload) skReload(); } catch (er) { alert("Keine gueltige Motor Datei."); } });
  $("#svgMotor").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return; const body = { svg: await f.text() };
    for (;;) {
      body.motor = cfg.motor; const { data: j } = await api("/api/svg-motor-import", body);
      if (j.errors) { $("#svgMotorMsg").textContent = j.errors.join(" "); return; }
      if (j.scale_required) {
        const v = prompt(j.message + "\nmm pro SVG Einheit (zum Beispiel 1 bei Einheit mm, 0.2646 bei px mit 96 dpi):");
        if (!v) { $("#svgMotorMsg").textContent = "Abgebrochen. Kein Massstab."; return; }
        body.mm_per_unit = parseFloat(v); continue;
      }
      cfg.motor.outline = null; cfg.motor.sketch = { points: j.sketch.points, constraints: [] }; cfg.motor.width = j.width; cfg.motor.depth = j.depth;
      writeInputs(); drawMotor(); refresh(); if (window.skReload) skReload();
      $("#svgMotorMsg").textContent = `Uebernommen. ${j.width.toFixed(2)} x ${j.depth.toFixed(2)} mm ${j.notes.join(" ")}`; return;
    }
  });
}
function download(name, text, type) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000); }

// --- Analyse (Ebenen, Probleme) -----------------------------------------------------------------
let refreshSeq = 0;
async function refresh() {
  drawMotor(); drawBounds();
  const seq = ++refreshSeq;
  let r;
  try { r = await api("/api/analyze", cfg); } catch (e) { return; }
  if (seq !== refreshSeq) return;
  if (r.data.errors) { showFieldErrors(r.data.errors); $("#levelInfo").innerHTML = ""; return; }
  showFieldErrors([]);
  renderLevelInfo(r.data);
}
function renderLevelInfo(a) {
  let h = `<table class="grid"><tr><th>Ebene</th><th>z oben [mm]</th><th>Stange gesamt</th><th>unter Montage</th><th>Gewinde unten / oben</th></tr>`;
  for (const p of a.planes) {
    if (p.index === 0) { h += `<tr><td>G0</td><td>${round(p.z_top, 2)}</td><td colspan=3>Referenzebene, Hub ${round(cfg.rod.stroke, 2)} mm darueber</td></tr>`; continue; }
    const r = p.rod;
    h += `<tr><td>${p.name}</td><td>${round(p.z_top, 2)}</td><td>${round(r.length, 1)}</td><td>${round(r.length_below_mount, 1)}</td><td>${round(r.engage_below_actual, 1)} / ${round(r.engage_above_actual, 1)}</td></tr>`;
    if (p.problems.length) h += `<tr><td colspan=5 class="bad">${p.problems.map(esc).join("<br>")}</td></tr>`;
  }
  $("#levelInfo").innerHTML = h + `</table><p class="hint">Alle Stangen erreichen ${round(cfg.rod.stroke, 2)} mm ueber G0. Laengen in mm. Wirksamer Mindestabstand ${round(a.required_gap, 2)} mm.</p>`;
  const svg = $("#sectionPreview"); svg.innerHTML = "";
  const zmin = Math.min(...a.planes.map((p) => p.z_bottom), ...a.planes.slice(1).map((p) => p.rod.bottom_retracted)) - 10, zmax = cfg.rod.stroke + 10;
  svg.setAttribute("viewBox", `0 ${-zmax} 300 ${zmax - zmin}`);
  a.planes.forEach((p) => {
    el("rect", { x: 10, y: -p.z_top, width: 280, height: p.thickness, fill: p.index ? col(p.index) : "#a1887f", "fill-opacity": 0.6 }, svg);
    const t = el("text", { x: 14, y: -p.z_top - 1, "font-size": 6, fill: "currentColor" }, svg); t.textContent = p.name;
    if (p.index) {
      const x = 40 + p.index * Math.min(40, 220 / a.planes.length);
      el("rect", { x: x - cfg.rod.diameter / 2, y: -p.rod.tip_extended, width: cfg.rod.diameter, height: p.rod.length, fill: "#222", "fill-opacity": 0.35 }, svg);
      el("rect", { x: x - cfg.rod.diameter / 2, y: -p.rod.tip_extended, width: cfg.rod.diameter, height: p.rod.tip_extended - p.rod.bottom_extended, fill: "#222" }, svg);
      const mh = cfg.motor.height, top = cfg.motor.mount === "top";
      el("rect", { x: x + 5, y: top ? -(p.z_top + mh) : -p.z_bottom, width: 22, height: mh, fill: col(p.index), "fill-opacity": 0.5 }, svg);
    }
  });
}
function drawBounds() {
  const svg = $("#boundsPreview"); svg.innerHTML = ""; const b = cfg.bounds;
  if (!(b.xmax > b.xmin && b.ymax > b.ymin)) return;
  const w = b.xmax - b.xmin, h = b.ymax - b.ymin, m = Math.max(w, h) * 0.04;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-b.ymax - m} ${w + 2 * m} ${h + 2 * m}`);
  el("rect", { x: b.xmin, y: -b.ymax, width: w, height: h, fill: "none", stroke: "currentColor", "stroke-width": w / 400 }, svg);
  if (b.edge_margin > 0) el("rect", { x: b.xmin + b.edge_margin, y: -b.ymax + b.edge_margin, width: w - 2 * b.edge_margin, height: h - 2 * b.edge_margin, fill: "none", stroke: "#888", "stroke-dasharray": "2 2", "stroke-width": w / 600 }, svg);
  for (const o of cfg.obstacles) {
    if (o.shape === "circle") el("circle", { cx: o.x, cy: -o.y, r: o.r, fill: "#bbb", stroke: "#555", "stroke-width": w / 600 }, svg);
    else el("rect", { x: o.x - o.w / 2, y: -o.y - o.h / 2, width: o.w, height: o.h, transform: `rotate(${-o.angle} ${o.x} ${-o.y})`, fill: "#bbb", stroke: "#555", "stroke-width": w / 600 }, svg);
  }
  for (const [pl, zs] of Object.entries(cfg.stack.mount_zones || {})) for (const z of zs) {
    el("rect", { x: z[0], y: -z[3], width: z[2] - z[0], height: z[3] - z[1], fill: col(+pl), "fill-opacity": 0.12, stroke: col(+pl), "stroke-width": w / 600 }, svg);
  }
}

// --- Berechnung ----------------------------------------------------------------------------------
const STATE_DE = { queued: "wartet", running: "laeuft", finished: "fertig", failed: "Fehler", cancelled: "abgebrochen" };
async function start() {
  $("#errors").innerHTML = "";
  const { status, data } = await api("/api/start", cfg);
  if (status !== 200) { showFieldErrors(data.errors || [data.error || "Fehler"]); $("#errors").innerHTML = "<ul>" + (data.errors || []).map((e) => `<li>${esc(e)}</li>`).join("") + "</ul>"; return; }
  showFieldErrors([]);
  jobId = data.job_id; $("#btnStart").disabled = true; $("#btnCancel").disabled = false;
  clearInterval(poll); clearInterval(livePoll);
  poll = setInterval(tick, 400); livePoll = setInterval(live, 1200); tick(); live();
}
async function live() {
  if (!jobId) return;
  const { data } = await api("/api/live/" + jobId); if (data && data.geometry) drawPlan($("#liveView"), data.geometry, null, true);
}
async function tick() {
  const { data: s } = await api("/api/status/" + jobId); const p = s.progress;
  $("#bar").style.width = (p ? Math.round(p.fraction * 100) : 0) + "%";
  const rows = [["Status", STATE_DE[s.state] || s.state], ["Phase", p ? p.phase : "-"], ["Untersuchte Kandidaten", s.candidates.toLocaleString("de") + " von " + s.max_candidates.toLocaleString("de")],
    ["Verstrichene Zeit", p ? p.elapsed.toFixed(1) + " s von " + s.time_limit + " s" : "-"], ["Beste Anzahl bisher", p ? p.best_count : "-"],
    ["Beste Bewertung bisher", p ? p.best_score.toFixed(3) : "-"], ["Info", p ? esc(p.message) : ""]];
  $("#progTable").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  if (["finished", "failed", "cancelled"].includes(s.state)) {
    clearInterval(poll); clearInterval(livePoll); $("#btnStart").disabled = false; $("#btnCancel").disabled = true; $("#bar").style.width = "100%";
    if (s.state === "failed") { $("#errors").textContent = s.error; return; }
    solCache = {}; edited = false; selUnit = null;
    await loadResult(0); switchTab("results");
  }
}
async function loadResult(idx) {
  const { status, data: j } = await api(`/api/result/${jobId}?solution=${idx}`);
  if (status !== 200) return;
  lastResult = j.result; solIndex = j.solution_index || 0; lastGeo = j.geometry; solCache[solIndex] = j.geometry; edited = false;
  renderResult();
}
function placementsOf(geo) { return geo.units.map((u) => ({ x: u.x, y: u.y, plane: u.plane, angle: u.angle, ...(u.cd != null ? { cd: u.cd } : {}) })); }

function renderResult() {
  const r = lastResult;
  $("#noResult").hidden = true; $("#resultBox").hidden = false;
  const ST = { completed: "Suche abgeschlossen", time_limit: "Zeitlimit erreicht", candidate_limit: "Kandidatenlimit erreicht", cancelled: "Abgebrochen", infeasible: "Keine gueltige Loesung", stagnation: "Beendet bei Stagnation", manual: "Manuell bearbeitet" };
  const best = r.solutions[0], n = lastGeo ? lastGeo.units.length : 0;
  $("#statusBox").className = "statusBox" + (n < r.target || (lastGeo && lastGeo.collisions.length) ? " warn" : "");
  $("#statusBox").innerHTML = `<b>${ST[r.status] || esc(r.status)}.</b> ${n} von ${r.target} Stangen platziert (${esc(r.optimizer)}). ` +
    (edited ? "<b>Manuell bearbeitet. Die Bewertung der Suche gilt nicht mehr.</b>" : `<b>${r.proven_optimal ? "Optimalitaet bewiesen." : "Beste gefundene Loesung, nicht als global optimal bewiesen."}</b><br>${esc(r.optimality_note)}`);
  const sel = $("#solSel"); sel.innerHTML = r.solutions.map((s, i) => `<option value="${i}">${i + 1}. Score ${s.score.total.toFixed(3)} (${s.count} Stangen)</option>`).join(""); sel.value = solIndex;
  $("#messages").innerHTML = r.messages.map((m) => `<li>${esc(m)}</li>`).join("") || "<li>Keine</li>";
  $("#compare").innerHTML = "<tr><td><b>Nr</b></td><td><b>Anzahl / Flaeche / Score</b></td></tr>" + r.solutions.map((s, i) =>
    `<tr><td>${i + 1}${i === solIndex ? " (aktiv)" : ""}</td><td>${s.count} / ${(s.score.metrics.footprint_area || 0).toFixed(0)} mm² / ${s.score.total.toFixed(3)}</td></tr>`).join("");
  if (!lastGeo) return;
  const ps = $("#planeSel"), cur = ps.value; ps.innerHTML = lastGeo.planes.slice(1).map((p) => `<option value="${p.index}">${p.name}</option>`).join(""); if (cur) ps.value = cur;
  const sc = r.solutions[solIndex] && r.solutions[solIndex].score, M = sc ? sc.metrics : null;
  if (M && !edited) {
    $("#metrics").innerHTML = [["Stangen", M.count], ["Grundflaeche (Bounding Box)", `${M.footprint_width.toFixed(1)} x ${M.footprint_height.toFixed(1)} mm`],
      ["Flaeche", M.footprint_area.toFixed(0) + " mm²"], ["Mittlerer Nachbarabstand", M.mean_nn_distance.toFixed(2) + " mm"],
      ["Variation Nachbarabstand", M.nn_cv.toFixed(3)], ["Ordnung Quadrat (psi4)", M.psi4.toFixed(2)], ["Ordnung Hex (psi6)", M.psi6.toFixed(2)],
      ["Einfache Obergrenze Anzahl", r.upper_bound], ["Kandidaten", r.candidates.toLocaleString("de")], ["Zeit", r.elapsed.toFixed(1) + " s"]]
      .concat(Object.keys(M).filter((k) => k.startsWith("plane_")).map((k) => [`Einheiten auf G${k.split("_")[1]}`, M[k]]))
      .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
    $("#terms").innerHTML = Object.entries(sc.terms).map(([k, v]) => `<tr><td>${k} (Gewicht ${(sc.weights[k] * 100).toFixed(0)}%)</td><td>${v.toFixed(3)}</td></tr>`).join("") + `<tr><td><b>Gesamt</b></td><td><b>${sc.total.toFixed(3)}</b></td></tr>`;
  } else if (edited) { $("#metrics").innerHTML = `<tr><td>Stangen</td><td>${lastGeo.units.length}</td></tr>`; $("#terms").innerHTML = ""; }
  $("#pairs").innerHTML = (lastGeo.closest_pairs || []).slice(0, 8).map((p) => {
    const tight = p.gap < lastGeo.required_gap * 1.5;
    return `<tr><td>${p.a} ${KIND[p.kind_a]} / ${p.b} ${KIND[p.kind_b]}</td><td style="color:${p.gap < lastGeo.required_gap - 1e-6 ? "var(--bad)" : tight ? "#e08a00" : "inherit"}">${p.gap.toFixed(2)} mm</td></tr>`;
  }).join("") || "<tr><td>Keine</td><td></td></tr>";
  $("#collisions").innerHTML = lastGeo.collisions.length ? lastGeo.collisions.map((c) => `<li style="color:var(--bad)">${esc(c.message)}</li>`).join("") : '<li style="color:var(--ok)">Keine Kollisionen. Alle Abstaende >= ' + lastGeo.required_gap.toFixed(2) + " mm</li>";
  $("#legend").innerHTML = lastGeo.planes.slice(1).map((p) => `<span><i style="background:${col(p.index)}"></i>Motor auf ${p.name}</span>`).join("") + '<span><i style="background:#222"></i>Stange</span><span><i style="background:none;border:2px solid #e00"></i>Kollision</span><span><i style="background:none;border:2px solid #e08a00"></i>enger Abstand</span>';
  renderEditPanel(); drawView();
}
const KIND = { housing: "Motor", gear: "Zahnrad", rod: "Stange", obstacle: "Hindernis" };

// --- Ergebnisansichten ------------------------------------------------------------------------------
function drawView() {
  if (!lastGeo) return; const g = lastGeo, svg = $("#view"), mode = $("#viewSel").value; svg.innerHTML = "";
  $("#planeLabel").style.display = mode === "plane" ? "" : "none";
  if (mode === "section") return drawSection(svg, g);
  if (mode === "iso") return drawIso(svg, g);
  drawPlan(svg, g, mode === "plane" ? parseInt($("#planeSel").value, 10) : null, false);
}
function drawPlan(svg, g, plane, live) {
  svg.innerHTML = "";
  const b = g.bounds, w = b.xmax - b.xmin, h = b.ymax - b.ymin, m = Math.max(w, h) * 0.04;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-b.ymax - m} ${w + 2 * m} ${h + 2 * m}`);
  const fs = Math.max(w, h) / 50;
  const Y = (y) => -y, pts = (o) => o.map(([x, y]) => `${x},${Y(y)}`).join(" ");
  el("rect", { x: b.xmin, y: -b.ymax, width: w, height: h, fill: "none", stroke: "currentColor", "stroke-width": w / 500 }, svg);
  g.obstacles.forEach((o) => el("polygon", { points: pts(o.outline), fill: "#bbb", stroke: "#555", "stroke-width": w / 700 }, svg));
  const passes = (u, p) => { const pl = g.planes[p]; return u.rod.bottom_retracted <= pl.z_top && u.rod.tip_extended >= pl.z_bottom; };
  g.units.forEach((u) => u.parts.forEach((p) => {
    if (p.kind === "rod" || (plane != null && u.plane !== plane)) return;
    el("polygon", { points: pts(p.outline), fill: col(u.plane), "fill-opacity": p.kind === "gear" ? 0.85 : 0.35, stroke: col(u.plane), "stroke-width": w / 700, "data-unit": u.id }, svg);
  }));
  const r = g.rod_diameter / 2;
  g.units.forEach((u) => {
    if (plane != null && !(u.plane === plane || passes(u, plane))) return;
    if (plane != null) el("circle", { cx: u.x, cy: Y(u.y), r: g.hole_diameter / 2, fill: "none", stroke: "currentColor", "stroke-width": w / 700 }, svg);
    const c = el("circle", { cx: u.x, cy: Y(u.y), r: Math.max(r, w / 200), fill: u.id === selUnit ? "#e00" : "#222", "data-unit": u.id, class: editMode && !live ? "handle" : "" }, svg);
    const t = el("text", { x: u.x + r + fs * 0.3, y: Y(u.y) - r, "font-size": fs, fill: "currentColor", "pointer-events": "none" }, svg); t.textContent = u.id;
  });
  if (!live && $("#optDist").checked && plane == null && g.units.length > 1) g.units.forEach((u) => {
    let best = null, bd = 1e18; g.units.forEach((v) => { if (v !== u) { const d = Math.hypot(v.x - u.x, v.y - u.y); if (d < bd) { bd = d; best = v; } } });
    el("line", { x1: u.x, y1: Y(u.y), x2: best.x, y2: Y(best.y), stroke: "#777", "stroke-width": w / 900, "stroke-dasharray": `${fs / 3} ${fs / 3}`, "pointer-events": "none" }, svg);
    if (u.id < best.id) { const t = el("text", { x: (u.x + best.x) / 2, y: Y((u.y + best.y) / 2), "font-size": fs * 0.8, fill: "#888", "pointer-events": "none" }, svg); t.textContent = bd.toFixed(1); }
  });
  if (!live) (g.closest_pairs || []).forEach((p) => { if (p.gap < g.required_gap * 1.5) el("circle", { cx: p.x, cy: Y(p.y), r: fs, fill: "none", stroke: p.gap < g.required_gap - 1e-6 ? "#e00" : "#e08a00", "stroke-width": w / 600, "pointer-events": "none" }, svg); });
  g.collisions.forEach((c) => el("circle", { cx: c.x, cy: Y(c.y), r: fs * 1.4, fill: "none", stroke: "#e00", "stroke-width": w / 400, "pointer-events": "none" }, svg));
}
function drawSection(svg, g) {
  const b = g.bounds, w = b.xmax - b.xmin;
  const zmin = Math.min(...g.planes.map((p) => p.z_bottom), ...g.units.map((u) => u.rod.bottom_retracted)) - 5, zmax = g.stroke + 5, m = w * 0.04;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-zmax} ${w + 2 * m} ${zmax - zmin}`);
  const fs = (zmax - zmin) / 35;
  g.planes.forEach((p) => {
    el("rect", { x: b.xmin, y: -p.z_top, width: w, height: p.thickness, fill: p.index ? col(p.index) : "#a1887f", "fill-opacity": 0.45 }, svg);
    const t = el("text", { x: b.xmin + 1, y: -p.z_top - 1, "font-size": fs, fill: "currentColor" }, svg); t.textContent = `${p.name}  z=${round(p.z_top, 2)}`;
  });
  el("line", { x1: b.xmin, x2: b.xmax, y1: -g.stroke, y2: -g.stroke, stroke: "#e00", "stroke-dasharray": "2 2", "stroke-width": w / 600 }, svg);
  g.units.forEach((u) => {
    el("rect", { x: u.x - g.rod_diameter / 2, y: -u.rod.tip_extended, width: g.rod_diameter, height: u.rod.length, fill: "#222", "fill-opacity": 0.3 }, svg);
    u.parts.filter((p) => p.kind !== "rod").forEach((p) => {
      const xs = p.outline.map((q) => q[0]); const x0 = Math.min(...xs), x1 = Math.max(...xs);
      el("rect", { x: x0, y: -p.z1, width: x1 - x0, height: p.z1 - p.z0, fill: col(u.plane), "fill-opacity": 0.35, stroke: col(u.plane), "stroke-width": w / 800 }, svg);
    });
  });
}
function drawIso(svg, g) {
  const a = rot.a * Math.PI / 180, tilt = rot.tilt, b = g.bounds, cx = (b.xmin + b.xmax) / 2, cy = (b.ymin + b.ymax) / 2;
  const P = (x, y, z) => { const dx = x - cx, dy = y - cy, rx = dx * Math.cos(a) - dy * Math.sin(a), ry = dx * Math.sin(a) + dy * Math.cos(a); return [rx, -(ry * tilt + z * Math.sqrt(1 - tilt * tilt))]; };
  const R = Math.hypot(b.xmax - b.xmin, b.ymax - b.ymin) / 2 + 10, zmin = Math.min(...g.planes.map((p) => p.z_bottom), ...g.units.map((u) => u.rod.bottom_retracted)), zmax = g.stroke;
  svg.setAttribute("viewBox", `${-R} ${-(zmax + R * tilt)} ${2 * R} ${zmax - zmin + 2 * R * tilt + 10}`);
  const poly = (pts) => pts.map((p) => p.join(",")).join(" ");
  g.planes.forEach((p) => el("polygon", { points: poly([[b.xmin, b.ymin], [b.xmax, b.ymin], [b.xmax, b.ymax], [b.xmin, b.ymax]].map(([x, y]) => P(x, y, p.z_top))), fill: p.index ? col(p.index) : "#a1887f", "fill-opacity": 0.18, stroke: "currentColor", "stroke-width": 0.2 }, svg));
  g.units.forEach((u) => {
    const [bx, by] = P(u.x, u.y, u.rod.bottom_retracted), [tx, ty] = P(u.x, u.y, u.rod.tip_extended);
    el("line", { x1: bx, y1: by, x2: tx, y2: ty, stroke: "#222", "stroke-width": g.rod_diameter * 0.9, "stroke-opacity": 0.8 }, svg);
    u.parts.filter((p) => p.kind !== "rod").forEach((p) => el("polygon", { points: poly(p.outline.map(([x, y]) => P(x, y, p.z1))), fill: col(u.plane), "fill-opacity": 0.55, stroke: col(u.plane), "stroke-width": 0.2 }, svg));
  });
}
function initIsoDrag() {
  const svg = $("#view"); let d = null;
  svg.addEventListener("pointerdown", (e) => { if ($("#viewSel").value !== "iso") return; d = { x: e.clientX, y: e.clientY, a: rot.a, t: rot.tilt }; svg.setPointerCapture(e.pointerId); });
  svg.addEventListener("pointermove", (e) => { if (!d) return; rot.a = d.a + (e.clientX - d.x) * 0.5; rot.tilt = Math.min(0.95, Math.max(0.1, d.t + (e.clientY - d.y) * 0.004)); drawView(); });
  svg.addEventListener("pointerup", () => { d = null; });
}

// --- Manuelles Bearbeiten ---------------------------------------------------------------------------
function initEdit() {
  const svg = $("#view"); let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (!editMode || !lastGeo || $("#viewSel").value === "iso" || $("#viewSel").value === "section") return;
    const id = e.target.dataset && e.target.dataset.unit; if (id === undefined || id === "") return;
    selUnit = +id; drag = true; svg.setPointerCapture(e.pointerId); renderEditPanel(); drawView();
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag || selUnit == null) return;
    const [x, y] = svgPoint(svg, e); const u = lastGeo.units.find((q) => q.id === selUnit); if (!u) return;
    u.x = Math.round(x * 100) / 100; u.y = Math.round(y * 100) / 100; moveUnitLocally(u); drawView();
  });
  svg.addEventListener("pointerup", () => { if (drag) { drag = null; pushEdit(); } });
}
function moveUnitLocally(u) { // Vorschau waehrend des Ziehens. Teile werden nach der Pruefung durch den Server ersetzt
  const dx = u.x - u._x0, dy = u.y - u._y0;
  u.parts.forEach((p) => { p.outline = p.outline.map(([x, y]) => [x + dx, y + dy]); });
  u._x0 = u.x; u._y0 = u.y;
}
function renderEditPanel() {
  const box = $("#editPanel"); box.hidden = !editMode; if (!editMode || !lastGeo) return;
  lastGeo.units.forEach((u) => { if (u._x0 === undefined) { u._x0 = u.x; u._y0 = u.y; } });
  const u = lastGeo.units.find((q) => q.id === selUnit);
  const planes = lastGeo.planes.slice(1).map((p) => `<option value="${p.index}" ${u && u.plane === p.index ? "selected" : ""}>${p.name}</option>`).join("");
  box.innerHTML = `<b>Bearbeiten.</b> Stange in der Draufsicht ziehen. Jede Aenderung wird sofort geprueft. ` + (u ? `Einheit ${u.id}:
    Ebene <select id="edPlane">${planes}</select> Winkel <input id="edAngle" type="number" step="any" value="${u.angle}" style="width:80px">
    x <input id="edX" type="number" step="any" value="${round(u.x, 3)}" style="width:80px"> y <input id="edY" type="number" step="any" value="${round(u.y, 3)}" style="width:80px">
    <button id="edDel">Entfernen</button>` : "Keine Einheit gewaehlt.") + ` <button id="edAdd">Einheit hinzufuegen</button> <button id="edReset">Zuruecksetzen</button>`;
  const upd = (fn) => () => { const q = lastGeo.units.find((z) => z.id === selUnit); if (q) { fn(q); pushEdit(); } };
  if (u) {
    $("#edPlane").addEventListener("change", upd((q) => { q.plane = +$("#edPlane").value; }));
    $("#edAngle").addEventListener("change", upd((q) => { q.angle = parseFloat($("#edAngle").value); }));
    $("#edX").addEventListener("change", upd((q) => { q.x = parseFloat($("#edX").value); }));
    $("#edY").addEventListener("change", upd((q) => { q.y = parseFloat($("#edY").value); }));
    $("#edDel").addEventListener("click", () => { lastGeo.units = lastGeo.units.filter((q) => q.id !== selUnit); selUnit = null; pushEdit(); });
  }
  $("#edAdd").addEventListener("click", () => {
    const b = lastGeo.bounds; lastGeo.units.push({ id: 1e6, x: (b.xmin + b.xmax) / 2, y: (b.ymin + b.ymax) / 2, plane: 1, angle: 0, cd: null, parts: [], rod: {} }); selUnit = 1e6; pushEdit();
  });
  $("#edReset").addEventListener("click", () => { edited = false; loadResult(solIndex); });
}
async function pushEdit() {
  clearTimeout(validateTimer);
  validateTimer = setTimeout(async () => {
    const pls = placementsOf(lastGeo);
    const keep = lastGeo.units.findIndex((u) => u.id === selUnit);
    const { status, data } = await api("/api/validate", { project: cfg, placements: pls });
    if (status !== 200) { $("#editPanel").innerHTML = `<span style="color:var(--bad)">${esc((data.errors || [data.error]).join(" "))}</span>`; return; }
    lastGeo = data.geometry; edited = true; selUnit = keep >= 0 ? lastGeo.units[keep].id : null; renderResult();
  }, 120);
}

// --- Export, Speichern -------------------------------------------------------------------------------
async function doExport() {
  const fmt = $("#expFmt").value; if (!lastGeo) return;
  const body = { project: cfg, placements: placementsOf(lastGeo), format: fmt };
  const r = await fetch("/api/export-layout", { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) { alert("Export fehlgeschlagen. " + (await r.text())); return; }
  download("blindsight." + fmt, await r.text(), "text/plain");
}
function saveResult() { if (!lastGeo) return; download("blindsight-ergebnis.json", JSON.stringify({ project: cfg, placements: placementsOf(lastGeo) }, null, 2), "application/json"); }
async function loadResultFile(file) {
  let obj; try { obj = JSON.parse(await file.text()); } catch (e) { alert("Keine gueltige Datei."); return; }
  if (!obj.project || !obj.placements) { alert("Datei enthaelt kein Ergebnis (project und placements erwartet)."); return; }
  await loadCfg(obj.project);
  const { status, data } = await api("/api/validate", { project: cfg, placements: obj.placements });
  if (status !== 200) { alert((data.errors || [data.error]).join("\n")); return; }
  lastGeo = data.geometry; edited = true; selUnit = null; jobId = null;
  lastResult = { solutions: [], status: "manual", optimizer: "geladen", target: cfg.target_count, upper_bound: 0, messages: [], proven_optimal: false, optimality_note: "", candidates: 0, elapsed: 0 };
  renderResult(); switchTab("results");
}

// --- Allgemein ------------------------------------------------------------------------------------------
function switchTab(name) {
  if (name === "sketch" && window.skReload) setTimeout(skReload, 0);
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
}
async function loadCfg(obj) {
  const base = JSON.parse(JSON.stringify(defaults));
  const merge = (a, b) => { for (const k of Object.keys(b)) { if (b[k] && typeof b[k] === "object" && !Array.isArray(b[k]) && a[k] && typeof a[k] === "object" && !Array.isArray(a[k])) merge(a[k], b[k]); else a[k] = b[k]; } return a; };
  cfg = merge(base, obj); writeInputs(); await refresh(); if (window.skReload) skReload();
}

async function init() {
  schema = (await api("/api/schema")).data; defaults = (await api("/api/default")).data;
  buildForms(); initMotorPreview(); initLibrary(); if (window.initSketch) initSketch(); initIsoDrag(); initEdit();
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#unitSel").addEventListener("change", () => { unit = $("#unitSel").value; writeInputs(); refresh(); if (window.skRender) skRender(); });
  $("#btnStart").addEventListener("click", start);
  $("#btnCancel").addEventListener("click", () => api("/api/cancel/" + jobId, {}));
  ["viewSel", "planeSel", "optDist"].forEach((id) => $("#" + id).addEventListener("change", drawView));
  $("#optEdit").addEventListener("change", () => { editMode = $("#optEdit").checked; renderEditPanel(); drawView(); });
  $("#solSel").addEventListener("change", () => loadResult(+$("#solSel").value));
  $("#btnExport").addEventListener("click", doExport);
  $("#btnSaveResult").addEventListener("click", saveResult);
  $("#fileResult").addEventListener("change", (e) => { if (e.target.files[0]) loadResultFile(e.target.files[0]); });
  $("#btnSave").addEventListener("click", () => download("blindsight-config.json", JSON.stringify(cfg, null, 2), "application/json"));
  $("#btnReset").addEventListener("click", () => loadCfg({}));
  $("#fileLoad").addEventListener("change", async (e) => { const f = e.target.files[0]; if (!f) return; try { await loadCfg(JSON.parse(await f.text())); } catch (er) { alert("Keine gueltige Konfigurationsdatei."); } });
  document.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => { const p = PRESETS[b.dataset.preset]; WEIGHTS.forEach(([k], i) => { cfg.search.weights[k] = p[i]; }); writeWeights(); }));
  $("#obsAdd").addEventListener("click", () => { cfg.obstacles.push({ shape: "circle", x: (cfg.bounds.xmin + cfg.bounds.xmax) / 2, y: (cfg.bounds.ymin + cfg.bounds.ymax) / 2, w: 10, h: 10, r: 5, angle: 0, z0: -1e6, z1: 1e6, plane: null, name: "" }); renderObstacles(); refresh(); });
  $("#zoneAdd").addEventListener("click", () => { const z = (cfg.stack.mount_zones["1"] ||= []); z.push([cfg.bounds.xmin, cfg.bounds.ymin, cfg.bounds.xmax, cfg.bounds.ymax]); renderZones(); refresh(); });
  const ex = (await api("/api/examples")).data;
  ex.forEach((n) => $("#exampleSel").add(new Option(n, n)));
  $("#exampleSel").addEventListener("change", async (e) => { if (e.target.value) await loadCfg((await api("/api/example/" + e.target.value)).data); });
  await loadCfg({});
}
window.addEventListener("load", init);
