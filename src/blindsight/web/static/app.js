"use strict";
// Reine Darstellung. Alle Berechnungen laufen im Python Kern.
const $ = (s) => document.querySelector(s);
const PALETTE = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"];
const col = (p) => PALETTE[(p - 1) % PALETTE.length];
const NS = "http://www.w3.org/2000/svg";
let cfg = null, jobId = null, poll = null, lastGeo = null, lastResult = null;

// Eingabeeinheiten (Anzeige). Intern immer mm.
const UNIT = { mm: 1, cm: 10, in: 25.4 };
let unit = "mm";

const FIELDS = {
  general: [
    ["name", "Name", "text"],
    ["target_count", "Gewuenschte Anzahl Stangen", "int"],
    ["clearance", "Sicherheitsabstand Bauteile", "len", "Mindestabstand zwischen allen fremden Bauteilen"],
    ["tolerance", "Toleranz (wird addiert)", "len", "Rundung und Fertigung. Wirksamer Abstand = Sicherheitsabstand + Toleranz"],
  ],
  rod: [
    ["rod.diameter", "Durchmesser", "len"],
    ["rod.stroke", "Maximaler Hub ueber G0", "len"],
    ["rod.engage_below", "Gewinde unter Zahnradachse (ausgefahren)", "len"],
    ["rod.engage_above", "Gewinde ueber Zahnradachse (eingefahren)", "len"],
    ["rod.length_tolerance", "Laengenzuschlag", "len"],
    ["rod.retract_depth", "Spitze eingefahren unter G0", "len"],
    ["rod.hole_clearance", "Radiales Lochspiel", "len"],
  ],
  motor: [
    ["motor.width", "Breite (x)", "len"],
    ["motor.depth", "Tiefe (y, Wellenrichtung)", "len"],
    ["motor.height", "Hoehe (z)", "len"],
    ["motor.shaft_x", "Abtriebsachse, x Versatz zur Mitte", "len"],
    ["motor.axis_height", "Achshoehe ueber Montageflaeche", "len"],
    ["motor.gear_diameter", "Zahnrad Durchmesser", "len"],
    ["motor.gear_width", "Zahnrad Breite", "len"],
    ["motor.gear_gap", "Abstand Gehaeuse zu Zahnrad", "len"],
    ["motor.center_distance", "Achsabstand Zahnrad zu Stange", "len", "Eingriff nur als Abstand modelliert"],
    ["motor.own_clearance", "Mindestabstand Gehaeuse zur eigenen Stange", "len"],
    ["motor.mount", "Montage", "sel:top=Motor steht auf der Ebene,bottom=Motor haengt unter der Ebene"],
  ],
  stack: [
    ["stack.n_motor_planes", "Anzahl Motorebenen", "int"],
    ["stack.mode", "Abstandsmodus", "sel:uniform=Einheitlicher Abstand,gaps=Einzelne Abstaende G(i) zu G(i+1),distances=Abstand jeder Ebene zu G0"],
    ["stack.uniform_spacing", "Einheitlicher Ebenenabstand", "len"],
    ["stack.gaps", "Einzelabstaende (Liste mit Komma)", "list"],
    ["stack.distances", "Abstaende zu G0 (Liste mit Komma)", "list"],
    ["stack.thickness", "Dicke Motorebenen", "len"],
    ["stack.g0_thickness", "Dicke G0", "len"],
    ["stack.allowed_planes", "Erlaubte Motorebenen (Liste, leer = alle)", "listint"],
  ],
  bounds: [
    ["bounds.xmin", "x min", "len"], ["bounds.xmax", "x max", "len"],
    ["bounds.ymin", "y min", "len"], ["bounds.ymax", "y max", "len"],
    ["bounds.edge_margin", "Randabstand", "len"],
    ["bounds.parts_in_bounds", "Im Bauraum muessen liegen", "sel:all=alle Bauteile,rods=nur Stangen"],
  ],
  weights: [
    ["search.weights.count", "Anzahl Stangen", "num"],
    ["search.weights.area", "Kleine Grundflaeche", "num"],
    ["search.weights.uniformity", "Gleichmaessige Verteilung", "num"],
    ["search.weights.regularity", "Regelmaessiges Muster", "num"],
  ],
  search: [
    ["search.patterns", "Muster (square, hex_x, hex_y)", "liststr"],
    ["search.angle_step", "Winkelschritt (Grad)", "num"],
    ["search.angle_min", "Winkel von (Grad)", "num"],
    ["search.angle_max", "Winkel bis (Grad, exklusiv)", "num"],
    ["search.allowed_angles", "Nur diese Winkel (Liste, leer = Raster)", "list"],
    ["search.time_limit_s", "Zeitlimit (s)", "num"],
    ["search.max_candidates", "Max. Kandidaten", "int"],
    ["search.seed", "Seed (Reproduzierbarkeit)", "int"],
    ["search.top_k", "Anzahl Loesungen", "int"],
  ],
};

const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
const set = (o, p, v) => { const ks = p.split("."); const l = ks.pop(); ks.reduce((a, k) => a[k], o)[l] = v; };
const round = (v, n = 4) => (v == null || isNaN(v) ? v : Math.round(v * 10 ** n) / 10 ** n);

function buildForm(id, fields) {
  const box = $("#" + id); box.innerHTML = "";
  for (const [path, label, type, hint] of fields) {
    const l = document.createElement("label"); l.textContent = label; box.appendChild(l);
    let inp;
    if (type.startsWith("sel:")) {
      inp = document.createElement("select");
      for (const o of type.slice(4).split(",")) { const [v, t] = o.split("="); inp.add(new Option(t, v)); }
    } else { inp = document.createElement("input"); inp.type = type === "text" ? "text" : (["list", "listint", "liststr"].includes(type) ? "text" : "number"); inp.step = "any"; }
    inp.dataset.path = path; inp.dataset.type = type; inp.id = "in-" + path.replace(/\./g, "-");
    inp.addEventListener("change", () => { readInput(inp); refresh(); });
    box.appendChild(inp);
    if (hint) { const h = document.createElement("div"); h.className = "hintrow"; h.textContent = hint; box.appendChild(h); }
  }
}

function readInput(inp) {
  const t = inp.dataset.type, p = inp.dataset.path; let v = inp.value;
  if (t === "len") v = parseFloat(v) * UNIT[unit];
  else if (t === "num") v = parseFloat(v);
  else if (t === "int") v = parseInt(v, 10);
  else if (t === "list") v = v.trim() === "" ? (p === "search.allowed_angles" ? null : []) : v.split(/[,; ]+/).filter(Boolean).map(parseFloat);
  else if (t === "listint") v = v.trim() === "" ? null : v.split(/[,; ]+/).filter(Boolean).map((x) => parseInt(x, 10));
  else if (t === "liststr") v = v.split(/[,; ]+/).filter(Boolean);
  set(cfg, p, v);
}

function writeInputs() {
  for (const inp of document.querySelectorAll("[data-path]")) {
    const t = inp.dataset.type, v = get(cfg, inp.dataset.path);
    if (t === "len") inp.value = round(v / UNIT[unit]);
    else if (["list", "listint", "liststr"].includes(t)) inp.value = v == null ? "" : v.join(", ");
    else inp.value = v == null ? "" : v;
  }
  $("#obstacles").value = JSON.stringify(cfg.obstacles || [], null, 1);
  const z = cfg.stack.mount_zones || {};
  $("#mountZones").value = Object.keys(z).length ? JSON.stringify(z) : "";
}

function readExtras() {
  const errs = [];
  try { cfg.obstacles = JSON.parse($("#obstacles").value || "[]"); } catch (e) { errs.push("Hindernisse. Kein gueltiges JSON"); }
  try { cfg.stack.mount_zones = $("#mountZones").value.trim() ? JSON.parse($("#mountZones").value) : {}; } catch (e) { errs.push("Montagebereiche. Kein gueltiges JSON"); }
  return errs;
}

// --- Vorschau Motor ----------------------------------------------------------
function el(name, attrs = {}, parent) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e); return e;
}
function drawMotor() {
  const m = cfg.motor, r = cfg.rod.diameter / 2, svg = $("#motorPreview"); svg.innerHTML = "";
  const gy = m.depth / 2 + m.gear_gap + m.gear_width / 2, rx = m.shaft_x + m.center_distance;
  const xs = [-m.width / 2, m.width / 2, m.shaft_x - m.gear_diameter / 2, rx + r, rx - r];
  const ys = [-m.depth / 2, m.depth / 2 + m.gear_gap + m.gear_width];
  const pad = 6, x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = ys[0] - pad, y1 = ys[1] + pad;
  svg.setAttribute("viewBox", `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`);
  const Y = (y) => -y;
  el("rect", { x: -m.width / 2, y: Y(m.depth / 2), width: m.width, height: m.depth, fill: "#999", "fill-opacity": .5, stroke: "#555", "stroke-width": .3 }, svg);
  el("rect", { x: m.shaft_x - m.gear_diameter / 2, y: Y(m.depth / 2 + m.gear_gap + m.gear_width), width: m.gear_diameter, height: m.gear_width, fill: "#f28e2b", stroke: "#333", "stroke-width": .3 }, svg);
  el("circle", { cx: rx, cy: Y(gy), r, fill: "#222" }, svg);
  el("circle", { cx: m.shaft_x, cy: Y(gy), r: .6, fill: "#e00" }, svg);
  el("line", { x1: m.shaft_x, y1: Y(gy), x2: rx, y2: Y(gy), stroke: "#e00", "stroke-width": .3, "stroke-dasharray": "1 1" }, svg);
}

// --- Seitenschnitt der Ebenen (Vorschau) -------------------------------------
async function refresh() {
  const errs = readExtras();
  drawMotor();
  $("#errors").innerHTML = errs.map((e) => `<li>${e}</li>`).join("");
  try {
    const r = await fetch("/api/analyze", { method: "POST", body: JSON.stringify(cfg) });
    const j = await r.json();
    if (j.errors) { $("#levelInfo").innerHTML = `<div class="errors"><ul>${j.errors.map((e) => `<li>${e}</li>`).join("")}</ul></div>`; return; }
    renderLevelInfo(j);
  } catch (e) { /* Server nicht erreichbar */ }
}
function renderLevelInfo(a) {
  let h = `<table><tr><th>Ebene</th><th>z oben</th><th>Stange gesamt</th><th>unter Montage</th><th>Gewinde unten/oben</th></tr>`;
  for (const p of a.planes) {
    if (p.index === 0) { h += `<tr><td>G0</td><td>${round(p.z_top, 2)}</td><td colspan=3 style="text-align:left">Referenzebene, Hub ${cfg.rod.stroke} mm darueber</td></tr>`; continue; }
    const r = p.rod;
    h += `<tr><td>${p.name}</td><td>${round(p.z_top, 2)}</td><td>${round(r.length, 1)}</td><td>${round(r.length_below_mount, 1)}</td><td>${round(r.engage_below_actual, 1)} / ${round(r.engage_above_actual, 1)}</td></tr>`;
    if (p.problems.length) h += `<tr><td colspan=5 class="bad">${p.problems.join("<br>")}</td></tr>`;
  }
  $("#levelInfo").innerHTML = h + `</table><p class="hint">Alle Stangen erreichen ${cfg.rod.stroke} mm ueber G0. Maße in mm. Wirksamer Mindestabstand ${round(a.required_gap, 2)} mm.</p>`;
  const svg = $("#sectionPreview"); svg.innerHTML = "";
  const zs = a.planes.map((p) => p.z_bottom).concat(cfg.rod.stroke); const zmin = Math.min(...zs) - 10, zmax = cfg.rod.stroke + 10;
  svg.setAttribute("viewBox", `0 ${-zmax} 300 ${zmax - zmin}`);
  a.planes.forEach((p) => {
    el("rect", { x: 10, y: -p.z_top, width: 280, height: p.thickness, fill: p.index ? col(p.index) : "#a1887f", "fill-opacity": .6 }, svg);
    const t = el("text", { x: 14, y: -p.z_top - 1, "font-size": 6, fill: "currentColor" }, svg); t.textContent = p.name;
    if (p.index) {
      const x = 40 + p.index * 40;
      el("rect", { x: x - cfg.rod.diameter / 2, y: -p.rod.tip_extended, width: cfg.rod.diameter, height: p.rod.length, fill: "#222" }, svg);
      el("rect", { x: x + 5, y: p.rod.z_mount < p.z_top ? -p.z_top + 1.6 : -p.z_top - cfg.motor.height, width: 22, height: cfg.motor.height, fill: col(p.index), "fill-opacity": .5 }, svg);
    }
  });
}

// --- Berechnung ----------------------------------------------------------------
async function start() {
  const errs = readExtras(); if (errs.length) { $("#errors").innerHTML = errs.map((e) => `<li>${e}</li>`).join(""); return; }
  $("#errors").innerHTML = "";
  const r = await fetch("/api/start", { method: "POST", body: JSON.stringify(cfg) }); const j = await r.json();
  if (j.errors) { $("#errors").innerHTML = "<ul>" + j.errors.map((e) => `<li>${e}</li>`).join("") + "</ul>"; return; }
  jobId = j.job_id; $("#btnStart").disabled = true; $("#btnCancel").disabled = false;
  clearInterval(poll); poll = setInterval(tick, 400); tick();
}
const STATE_DE = { queued: "wartet", running: "laeuft", finished: "fertig", failed: "Fehler", cancelled: "abgebrochen" };
async function tick() {
  const s = await (await fetch("/api/status/" + jobId)).json(); const p = s.progress;
  $("#bar").style.width = (p ? Math.round(p.fraction * 100) : 0) + "%";
  const rows = [["Status", STATE_DE[s.state] || s.state], ["Phase", p ? p.phase : "-"], ["Untersuchte Kandidaten", s.candidates.toLocaleString("de")],
    ["Verstrichene Zeit", p ? p.elapsed.toFixed(1) + " s" : "-"], ["Beste Anzahl bisher", p ? p.best_count : "-"],
    ["Beste Bewertung bisher", p ? p.best_score.toFixed(3) : "-"], ["Info", p ? p.message : ""]];
  $("#progTable").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
  if (["finished", "failed", "cancelled"].includes(s.state)) {
    clearInterval(poll); $("#btnStart").disabled = false; $("#btnCancel").disabled = true;
    $("#bar").style.width = "100%";
    if (s.state === "failed") { $("#errors").textContent = s.error; return; }
    await loadResult(0); switchTab("results");
  }
}
async function loadResult(idx) {
  const j = await (await fetch(`/api/result/${jobId}?solution=${idx}`)).json();
  lastResult = j.result; lastGeo = j.geometry;
  $("#noResult").hidden = true; $("#resultBox").hidden = false;
  const r = j.result, ST = { completed: "Suche abgeschlossen", time_limit: "Zeitlimit erreicht", candidate_limit: "Kandidatenlimit erreicht", cancelled: "Abgebrochen", infeasible: "Keine gueltige Loesung" };
  const best = r.solutions[0], n = best ? best.count : 0;
  $("#statusBox").className = "statusBox" + (n < r.target ? " warn" : "");
  $("#statusBox").innerHTML = `<b>${ST[r.status] || r.status}.</b> ${n} von ${r.target} Stangen platziert. ` +
    `<b>${r.proven_optimal ? "Optimalitaet bewiesen." : "Beste gefundene Loesung, nicht als global optimal bewiesen."}</b><br>${r.optimality_note}`;
  const sel = $("#solSel"); sel.innerHTML = r.solutions.map((s, i) => `<option value="${i}">${i + 1}. Score ${s.score.total.toFixed(3)} (${s.count} Stangen)</option>`).join(""); sel.value = j.solution_index || 0;
  $("#messages").innerHTML = r.messages.map((m) => `<li>${m}</li>`).join("") || "<li>Keine</li>";
  const ps = $("#planeSel"); const cur = ps.value; ps.innerHTML = lastGeo ? lastGeo.planes.slice(1).map((p) => `<option value="${p.index}">${p.name}</option>`).join("") : ""; if (cur) ps.value = cur;
  if (lastGeo) {
    const sc = r.solutions[j.solution_index || 0].score;
    const M = sc.metrics;
    $("#metrics").innerHTML = [["Stangen", M.count], ["Grundflaeche (Bounding Box)", `${M.footprint_width.toFixed(1)} x ${M.footprint_height.toFixed(1)} mm`],
      ["Flaeche", M.footprint_area.toFixed(0) + " mm²"], ["Mittlerer Nachbarabstand", M.mean_nn_distance.toFixed(2) + " mm"],
      ["Variation Nachbarabstand", M.nn_cv.toFixed(3)], ["Ordnung Quadrat (psi4)", M.psi4.toFixed(2)], ["Ordnung Hex (psi6)", M.psi6.toFixed(2)],
      ["Einfache Obergrenze Anzahl", r.upper_bound], ["Kandidaten", r.candidates.toLocaleString("de")], ["Zeit", r.elapsed.toFixed(1) + " s"]]
      .concat(Object.keys(M).filter((k) => k.startsWith("plane_")).map((k) => [`Einheiten auf G${k.split("_")[1]}`, M[k]]))
      .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
    $("#terms").innerHTML = Object.entries(sc.terms).map(([k, v]) => `<tr><td>${k} (Gewicht ${(sc.weights[k] * 100).toFixed(0)}%)</td><td>${v.toFixed(3)}</td></tr>`).join("") + `<tr><td><b>Gesamt</b></td><td><b>${sc.total.toFixed(3)}</b></td></tr>`;
    $("#collisions").innerHTML = lastGeo.collisions.length ? lastGeo.collisions.map((c) => `<li style="color:var(--bad)">${c.message}</li>`).join("") : '<li style="color:var(--ok)">Keine Kollisionen. Alle Abstaende >= ' + lastGeo.required_gap.toFixed(2) + " mm</li>";
    $("#dlSvg").href = `/api/export/${jobId}.svg?solution=${j.solution_index || 0}`; $("#dlSvg").download = "blindsight.svg";
    $("#dlJson").href = `/api/export/${jobId}.json?solution=${j.solution_index || 0}`; $("#dlJson").download = "blindsight.json";
    $("#legend").innerHTML = lastGeo.planes.slice(1).map((p) => `<span><i style="background:${col(p.index)}"></i>Motor auf ${p.name}</span>`).join("") + '<span><i style="background:#222"></i>Stange</span><span><i style="background:none;border:2px solid #e00"></i>Kollision</span>';
    drawView();
  }
}

// --- Ergebnisansichten ---------------------------------------------------------
function drawView() {
  if (!lastGeo) return; const g = lastGeo, svg = $("#view"), mode = $("#viewSel").value; svg.innerHTML = "";
  $("#planeLabel").style.display = mode === "plane" ? "" : "none"; $("#rotLabel").style.display = mode === "iso" ? "" : "none";
  if (mode === "section") return drawSection(svg, g);
  if (mode === "iso") return drawIso(svg, g);
  drawPlan(svg, g, mode === "plane" ? parseInt($("#planeSel").value, 10) : null);
}
function drawPlan(svg, g, plane) {
  const b = g.bounds, w = b.xmax - b.xmin, h = b.ymax - b.ymin, m = 4;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-b.ymax - m} ${w + 2 * m} ${h + 2 * m}`);
  const Y = (y) => -y, pts = (o) => o.map(([x, y]) => `${x},${Y(y)}`).join(" ");
  el("rect", { x: b.xmin, y: -b.ymax, width: w, height: h, fill: "none", stroke: "currentColor", "stroke-width": .3 }, svg);
  g.obstacles.forEach((o) => el("polygon", { points: pts(o.outline), fill: "#bbb", stroke: "#555", "stroke-width": .2 }, svg));
  const passes = (u, p) => { const pl = g.planes[p]; return u.rod.bottom_retracted <= pl.z_top && u.rod.tip_extended >= pl.z_bottom; };
  g.units.forEach((u) => u.parts.forEach((p) => {
    if (p.kind === "rod" || (plane != null && u.plane !== plane)) return;
    el("polygon", { points: pts(p.outline), fill: col(u.plane), "fill-opacity": p.kind === "gear" ? .85 : .35, stroke: col(u.plane), "stroke-width": .25 }, svg);
  }));
  const r = g.rod_diameter / 2;
  g.units.forEach((u) => {
    if (plane != null && !(u.plane === plane || passes(u, plane))) return;
    if (plane != null) el("circle", { cx: u.x, cy: Y(u.y), r: g.hole_diameter / 2, fill: "none", stroke: "currentColor", "stroke-width": .2 }, svg);
    el("circle", { cx: u.x, cy: Y(u.y), r, fill: "#222" }, svg);
    const t = el("text", { x: u.x + r + .6, y: Y(u.y) - r, "font-size": 2.4, fill: "currentColor" }, svg); t.textContent = u.id;
  });
  if ($("#optDist").checked && plane == null && g.units.length > 1) g.units.forEach((u) => {
    let best = null, bd = 1e9; g.units.forEach((v) => { if (v !== u) { const d = Math.hypot(v.x - u.x, v.y - u.y); if (d < bd) { bd = d; best = v; } } });
    el("line", { x1: u.x, y1: Y(u.y), x2: best.x, y2: Y(best.y), stroke: "#777", "stroke-width": .12, "stroke-dasharray": ".8 .8" }, svg);
    if (u.id < best.id) { const t = el("text", { x: (u.x + best.x) / 2, y: Y((u.y + best.y) / 2), "font-size": 2, fill: "#888" }, svg); t.textContent = bd.toFixed(1); }
  });
  g.collisions.forEach((c) => el("circle", { cx: c.x, cy: Y(c.y), r: 3, fill: "none", stroke: "#e00", "stroke-width": .5 }, svg));
}
function drawSection(svg, g) {
  const b = g.bounds, w = b.xmax - b.xmin, zmin = Math.min(...g.planes.map((p) => p.z_bottom)) - 5, zmax = g.stroke + 5, m = 4;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-zmax} ${w + 2 * m} ${zmax - zmin}`);
  g.planes.forEach((p) => {
    el("rect", { x: b.xmin, y: -p.z_top, width: w, height: p.thickness, fill: p.index ? col(p.index) : "#a1887f", "fill-opacity": .45 }, svg);
    const t = el("text", { x: b.xmin + 1, y: -p.z_top - 1, "font-size": 3, fill: "currentColor" }, svg); t.textContent = `${p.name}  z=${p.z_top}`;
  });
  el("line", { x1: b.xmin, x2: b.xmax, y1: -g.stroke, y2: -g.stroke, stroke: "#e00", "stroke-dasharray": "2 2", "stroke-width": .3 }, svg);
  g.units.forEach((u) => {
    el("rect", { x: u.x - g.rod_diameter / 2, y: -u.rod.tip_extended, width: g.rod_diameter, height: u.rod.length, fill: "#222", "fill-opacity": .75 }, svg);
    u.parts.filter((p) => p.kind !== "rod").forEach((p) => { const xs = p.outline.map((q) => q[0]); const x0 = Math.min(...xs), x1 = Math.max(...xs);
      el("rect", { x: x0, y: -p.z1, width: x1 - x0, height: p.z1 - p.z0, fill: col(u.plane), "fill-opacity": .35, stroke: col(u.plane), "stroke-width": .2 }, svg); });
  });
}
function drawIso(svg, g) {
  const a = (+$("#rot").value) * Math.PI / 180, tilt = .55, b = g.bounds, cx = (b.xmin + b.xmax) / 2, cy = (b.ymin + b.ymax) / 2;
  const P = (x, y, z) => { const dx = x - cx, dy = y - cy, rx = dx * Math.cos(a) - dy * Math.sin(a), ry = dx * Math.sin(a) + dy * Math.cos(a); return [rx, -(ry * tilt + z * Math.cos(Math.asin(tilt)))]; };
  const R = Math.hypot(b.xmax - b.xmin, b.ymax - b.ymin) / 2 + 10, zmin = Math.min(...g.planes.map((p) => p.z_bottom)), zmax = g.stroke;
  svg.setAttribute("viewBox", `${-R} ${-(zmax + R * tilt)} ${2 * R} ${zmax - zmin + 2 * R * tilt + 10}`);
  const poly = (pts) => pts.map((p) => p.join(",")).join(" ");
  const items = [];
  g.planes.forEach((p) => { items.push({ d: 1000 - p.index, draw: () => {
    el("polygon", { points: poly([[b.xmin, b.ymin], [b.xmax, b.ymin], [b.xmax, b.ymax], [b.xmin, b.ymax]].map(([x, y]) => P(x, y, p.z_top))), fill: p.index ? col(p.index) : "#a1887f", "fill-opacity": .18, stroke: "currentColor", "stroke-width": .2 }, svg); } }); });
  g.units.forEach((u) => {
    const [bx, by] = P(u.x, u.y, u.rod.bottom_retracted), [tx, ty] = P(u.x, u.y, u.rod.tip_extended);
    el("line", { x1: bx, y1: by, x2: tx, y2: ty, stroke: "#222", "stroke-width": g.rod_diameter * .9, "stroke-opacity": .8 }, svg);
    u.parts.filter((p) => p.kind !== "rod").forEach((p) => el("polygon", { points: poly(p.outline.map(([x, y]) => P(x, y, p.z1))), fill: col(u.plane), "fill-opacity": .55, stroke: col(u.plane), "stroke-width": .2 }, svg));
  });
  items.forEach((i) => i.draw());
}

// --- Allgemeines ---------------------------------------------------------------
function switchTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
}
async function loadCfg(obj) { cfg = obj; writeInputs(); await refresh(); }

async function init() {
  buildForm("f-general", FIELDS.general); buildForm("f-rod", FIELDS.rod); buildForm("f-motor", FIELDS.motor);
  buildForm("f-stack", FIELDS.stack); buildForm("f-bounds", FIELDS.bounds); buildForm("f-weights", FIELDS.weights); buildForm("f-search", FIELDS.search);
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  ["obstacles", "mountZones"].forEach((id) => $("#" + id).addEventListener("change", refresh));
  $("#btnStart").addEventListener("click", start);
  $("#btnCancel").addEventListener("click", () => fetch("/api/cancel/" + jobId, { method: "POST", body: "{}" }));
  ["viewSel", "planeSel", "optDist"].forEach((id) => $("#" + id).addEventListener("change", drawView));
  $("#rot").addEventListener("input", drawView);
  $("#solSel").addEventListener("change", () => loadResult(+$("#solSel").value));
  $("#btnSave").addEventListener("click", () => { readExtras(); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" })); a.download = "blindsight-config.json"; a.click(); });
  $("#fileLoad").addEventListener("change", async (e) => { const f = e.target.files[0]; if (f) await loadCfg(JSON.parse(await f.text())); });
  $("#svgMotor").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return; const svg = await f.text(); let body = { svg };
    for (;;) {
      const j = await (await fetch("/api/svg-motor-import", { method: "POST", body: JSON.stringify(body) })).json();
      if (j.errors) { $("#svgMotorMsg").textContent = j.errors.join(" "); return; }
      if (j.scale_required) {
        const v = prompt(j.message + "\nmm pro SVG Einheit (zum Beispiel 1 bei Einheit mm, 0.2646 bei px mit 96 dpi):"); if (!v) { $("#svgMotorMsg").textContent = "Abgebrochen. Kein Massstab."; return; }
        body.mm_per_unit = parseFloat(v); continue;
      }
      cfg.motor.width = j.width; cfg.motor.depth = j.depth; writeInputs(); refresh(); $("#svgMotorMsg").textContent = `Uebernommen. ${j.width.toFixed(2)} x ${j.depth.toFixed(2)} mm`; return;
    }
  });
  const ex = await (await fetch("/api/examples")).json();
  ex.forEach((n) => $("#exampleSel").add(new Option(n, n)));
  $("#exampleSel").addEventListener("change", async (e) => { if (e.target.value) await loadCfg(await (await fetch("/api/example/" + e.target.value)).json()); });
  await loadCfg(await (await fetch("/api/default")).json());
}
init();
