"use strict";
// Ergebnisse. Laden einer Loesung, Status, Kennzahlen, Vergleich, engste Stellen, Kollisionen.

const RESULT_STATUS_LABELS = {
  completed: "Suche abgeschlossen", time_limit: "Zeitlimit erreicht", candidate_limit: "Kandidatenlimit erreicht",
  cancelled: "Abgebrochen", infeasible: "Keine gültige Lösung", stagnation: "Beendet bei Stagnation", manual: "Manuell bearbeitet",
};
const TIGHT_FACTOR = 1.5;  // Abstaende unter 1.5 x Mindestabstand gelten als eng
const GAP_EPS = 1e-6;
const MAX_PAIRS_SHOWN = 8;

let lastResult = null;  // Ergebnis des Laufs (oder Platzhalter fuer eine geladene Datei)
let lastGeo = null;  // Geometrie der angezeigten Loesung
let solIndex = 0;
let resultSource = null;  // "job" oder "file"
let originalPlacements = null;  // Stand vor dem Bearbeiten (fuer Zuruecksetzen)
let edited = false;

const resultLatest = latestOnly((id, idx) => api(`/api/result/${id}?solution=${idx}`));

/** Laedt Loesung idx des aktuellen Laufs vom Server. */
async function loadResult(idx) {
  if (!jobId) return;
  const response = await resultLatest(jobId, idx);
  if (!response || response.status !== 200) return;
  const data = response.data;
  lastResult = data.result;
  solIndex = data.solution_index || 0;
  lastGeo = data.geometry;
  resultSource = "job";
  originalPlacements = lastGeo ? placementsOf(lastGeo) : null;
  edited = false;
  selUnit = null;
  renderResult();
}

/** Ergebnis aus einer Datei (Projekt und Platzierungen) anzeigen. */
function showLoadedResult(geometry) {
  lastGeo = geometry;
  edited = false;
  selUnit = null;
  jobId = null;
  resultSource = "file";
  originalPlacements = placementsOf(geometry);
  solIndex = 0;
  lastResult = {
    solutions: [], status: "manual", optimizer: "geladen", target: cfg.target_count, upper_bound: 0, messages: [],
    proven_optimal: false, optimality_note: "", candidates: 0, elapsed: 0,
  };
  renderResult();
}

function placementsOf(geometry) {
  return geometry.units.map((u) => ({ x: u.x, y: u.y, plane: u.plane, angle: u.angle, ...(u.cd != null ? { cd: u.cd } : {}) }));
}

function renderResult() {
  $("#noResult").hidden = true;
  $("#resultBox").hidden = false;
  renderStatusBox();
  renderSolutionList();
  if (!lastGeo) { clearGeometryViews(); return; }  // frueher blieben alte Anzeigen stehen
  renderPlaneSelect();
  renderMetrics();
  renderPairs();
  renderCollisions();
  renderLegend();
  renderEditPanel();
  drawView();
}

function renderStatusBox() {
  const r = lastResult;
  const n = lastGeo ? lastGeo.units.length : 0;
  const warn = n < r.target || (lastGeo && lastGeo.collisions.length);
  const optimality = r.proven_optimal ? "Optimalität bewiesen." : "Beste gefundene Lösung, nicht als global optimal bewiesen.";
  const box = $("#statusBox");
  box.className = "statusBox" + (warn ? " warn" : "");
  box.innerHTML = `<b>${esc(RESULT_STATUS_LABELS[r.status] || r.status)}.</b> ${n} von ${r.target} Stangen platziert (${esc(r.optimizer)}). ` +
    (edited ? "<b>Manuell bearbeitet. Die Bewertung der Suche gilt nicht mehr.</b>" : `<b>${optimality}</b><br>${esc(r.optimality_note)}`);
}

function renderSolutionList() {
  const r = lastResult;
  const select = $("#solSel");
  select.innerHTML = r.solutions.map((s, i) => `<option value="${i}">${i + 1}. Score ${s.score.total.toFixed(3)} (${s.count} Stangen)</option>`).join("");
  select.value = solIndex;
  $("#messages").innerHTML = r.messages.map((m) => `<li>${esc(m)}</li>`).join("") || "<li>Keine</li>";
  $("#compare").innerHTML = "<tr><td><b>Nr</b></td><td><b>Anzahl / Fläche / Score</b></td></tr>" + r.solutions.map((s, i) =>
    `<tr><td>${i + 1}${i === solIndex ? " (aktiv)" : ""}</td><td>${s.count} / ${(s.score.metrics.footprint_area || 0).toFixed(0)} mm² / ${s.score.total.toFixed(3)}</td></tr>`).join("");
}

function clearGeometryViews() {
  for (const id of ["#metrics", "#terms", "#pairs", "#collisions", "#legend", "#planeSel", "#view"]) $(id).innerHTML = "";
  $("#editPanel").hidden = true;
}

function renderPlaneSelect() {
  const select = $("#planeSel"), current = select.value;
  select.innerHTML = lastGeo.planes.slice(1).map((p) => `<option value="${p.index}">${esc(p.name)}</option>`).join("");
  if (current && [...select.options].some((o) => o.value === current)) select.value = current;
}

function renderMetrics() {
  const r = lastResult;
  const score = r.solutions[solIndex] && r.solutions[solIndex].score;
  if (edited || !score) {
    $("#metrics").innerHTML = `<tr><td>Stangen</td><td>${lastGeo.units.length}</td></tr>`;
    $("#terms").innerHTML = "";
    return;
  }
  const M = score.metrics;
  const rows = [
    ["Stangen", M.count], ["Grundfläche (Bounding Box)", `${M.footprint_width.toFixed(1)} x ${M.footprint_height.toFixed(1)} mm`],
    ["Fläche", M.footprint_area.toFixed(0) + " mm²"], ["Mittlerer Nachbarabstand", M.mean_nn_distance.toFixed(2) + " mm"],
    ["Variation Nachbarabstand", M.nn_cv.toFixed(3)], ["Ordnung Quadrat (psi4)", M.psi4.toFixed(2)], ["Ordnung Hex (psi6)", M.psi6.toFixed(2)],
    ["Einfache Obergrenze Anzahl", r.upper_bound], ["Kandidaten", r.candidates.toLocaleString("de")], ["Zeit", r.elapsed.toFixed(1) + " s"],
  ];
  for (const key of Object.keys(M).filter((k) => k.startsWith("plane_"))) rows.push([`Einheiten auf G${key.split("_")[1]}`, M[key]]);
  $("#metrics").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${esc(v)}</td></tr>`).join("");
  $("#terms").innerHTML = Object.entries(score.terms).map(([k, v]) =>
    `<tr><td>${esc(k)} (Gewicht ${(score.weights[k] * 100).toFixed(0)}%)</td><td>${v.toFixed(3)}</td></tr>`).join("") +
    `<tr><td><b>Gesamt</b></td><td><b>${score.total.toFixed(3)}</b></td></tr>`;
}

const gapColor = (gap, required) => (gap < required - GAP_EPS ? "var(--bad)" : gap < required * TIGHT_FACTOR ? COLORS.tight : "inherit");

function renderPairs() {
  const required = lastGeo.required_gap;
  $("#pairs").innerHTML = (lastGeo.closest_pairs || []).slice(0, MAX_PAIRS_SHOWN).map((p) =>
    `<tr><td>${p.a} ${KIND_LABELS[p.kind_a]} / ${p.b} ${KIND_LABELS[p.kind_b]}</td><td style="color:${gapColor(p.gap, required)}">${p.gap.toFixed(2)} mm</td></tr>`
  ).join("") || "<tr><td>Keine</td><td></td></tr>";
}

function renderCollisions() {
  const collisions = lastGeo.collisions;
  $("#collisions").innerHTML = collisions.length
    ? collisions.map((c) => `<li style="color:var(--bad)">${esc(c.message)}</li>`).join("")
    : `<li style="color:var(--ok)">Keine Kollisionen. Alle Abstände >= ${lastGeo.required_gap.toFixed(2)} mm</li>`;
}

function renderLegend() {
  const swatch = (style, text) => `<span><i style="${style}"></i>${text}</span>`;
  $("#legend").innerHTML = lastGeo.planes.slice(1).map((p) => swatch(`background:${col(p.index)}`, `Motor auf ${esc(p.name)}`)).join("") +
    swatch(`background:${COLORS.rod}`, "Stange") + swatch(`background:none;border:2px solid ${COLORS.bad}`, "Kollision") +
    swatch(`background:none;border:2px solid ${COLORS.tight}`, "enger Abstand");
}
