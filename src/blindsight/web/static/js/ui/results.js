"use strict";
// Results. Loading a solution, status, metrics, comparison, closest spots, collisions.
// Texts of the core (notes, optimality, collision messages) come translated from the server.

const TIGHT_FACTOR = 1.5;  // distances below 1.5 x the minimum distance count as tight
const GAP_EPS = 1e-6;
const MAX_PAIRS_SHOWN = 8;

let lastResult = null;  // result of the run (or a placeholder for a loaded file)
let lastGeo = null;  // geometry of the shown solution
let solIndex = 0;
let resultSource = null;  // "job" or "file"
let originalPlacements = null;  // state before editing (for reset)
let edited = false;

const resultLatest = latestOnly((id, idx) => api(`/api/result/${id}?solution=${idx}`));

/** Load solution idx of the current run from the server. */
async function loadResult(idx) {
  if (!jobId) return;
  const response = await resultLatest(jobId, idx);
  if (!response || response.status !== 200) return;
  const data = response.data;
  cancelPendingEdit();
  lastResult = data.result;
  solIndex = data.solution_index || 0;
  lastGeo = data.geometry;
  resultSource = "job";
  originalPlacements = lastGeo ? placementsOf(lastGeo) : null;
  edited = false;
  selUnit = null;
  renderResult();
}

/** Show a result from a file (project and placements). */
function showLoadedResult(geometry) {
  cancelPendingEdit();
  lastGeo = geometry;
  edited = false;
  selUnit = null;
  jobId = null;
  resultSource = "file";
  originalPlacements = placementsOf(geometry);
  solIndex = 0;
  lastResult = {
    solutions: [], status: "manual", optimizer: t("ui.result.loaded"), target: cfg.target_count, upper_bound: 0, messages: [],
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
  if (!lastGeo) { clearGeometryViews(); return; }  // old views used to stay visible
  renderPlaneSelect();
  renderMetrics();
  renderPairs();
  renderCollisions();
  renderLegend();
  renderEditPanel();
  drawView();
  if ($("#tileView").classList.contains("active")) renderTiling();
}

function renderStatusBox() {
  const r = lastResult;
  const n = lastGeo ? lastGeo.units.length : 0;
  const warn = n < r.target || (lastGeo && lastGeo.collisions.length);
  const optimality = t(r.proven_optimal ? "ui.result.proven" : "ui.result.not_proven");
  const box = $("#statusBox");
  box.className = "statusBox" + (warn ? " warn" : "");
  box.innerHTML = `<b>${esc(t("ui.status." + r.status))}.</b> ${esc(t("ui.result.placed", { n, target: r.target, optimizer: optionLabel("search.optimizer", r.optimizer) }))} ` +
    (edited ? `<b>${esc(t("ui.result.edited"))}</b>` : `<b>${esc(optimality)}</b><br>${esc(r.optimality_note)}`);
  const tile = currentTile();
  if (tile) {
    box.innerHTML += "<br>" + esc(t("ui.result.tile", {
      pattern: optionLabel("search.pattern", tile.pattern), pitch: round(tile.pitch, 2), rods: tile.rods, rows: tile.rows, cols: tile.cols,
      width: round(tile.width, 2), height: round(tile.height, 2),
    }));
  }
}

/** Repeating tile of the shown solution (periodic_tile only, not after manual edits). */
function currentTile() {
  const solution = lastResult && lastResult.solutions[solIndex];
  return !edited && solution && solution.tile ? solution.tile : null;
}

function renderSolutionList() {
  const r = lastResult;
  const select = $("#solSel");
  select.innerHTML = r.solutions.map((s, i) => `<option value="${i}">${esc(t("ui.result.solution_option", { i: i + 1, score: s.score.total.toFixed(3), count: s.count }))}</option>`).join("");
  select.value = solIndex;
  $("#messages").innerHTML = r.messages.map((m) => `<li>${esc(m)}</li>`).join("") || `<li>${esc(t("ui.result.none"))}</li>`;
  $("#compare").innerHTML = `<tr><td><b>${esc(t("ui.result.compare_no"))}</b></td><td><b>${esc(t("ui.result.compare_values"))}</b></td></tr>` + r.solutions.map((s, i) =>
    `<tr><td>${i + 1}${i === solIndex ? " " + esc(t("ui.result.active")) : ""}</td><td>${s.count} / ${(s.score.metrics.footprint_area || 0).toFixed(0)} mm² / ${s.score.total.toFixed(3)}</td></tr>`).join("");
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
    $("#metrics").innerHTML = `<tr><td>${esc(t("ui.metric.rods"))}</td><td>${lastGeo.units.length}</td></tr>`;
    $("#terms").innerHTML = "";
    return;
  }
  const M = score.metrics;
  const rows = [
    [t("ui.metric.rods"), M.count], [t("ui.metric.footprint"), `${M.footprint_width.toFixed(1)} x ${M.footprint_height.toFixed(1)} mm`],
    [t("ui.metric.area"), M.footprint_area.toFixed(0) + " mm²"], [t("ui.metric.mean_nn"), M.mean_nn_distance.toFixed(2) + " mm"],
    [t("ui.metric.nn_cv"), M.nn_cv.toFixed(3)], [t("ui.metric.psi4"), M.psi4.toFixed(2)], [t("ui.metric.psi6"), M.psi6.toFixed(2)],
    [t("ui.metric.upper_bound"), r.upper_bound], [t("ui.metric.candidates"), fmtCount(r.candidates)], [t("ui.metric.time"), r.elapsed.toFixed(1) + " s"],
  ];
  for (const key of Object.keys(M).filter((k) => k.startsWith("plane_"))) rows.push([t("ui.metric.units_on", { plane: key.split("_")[1] }), M[key]]);
  if ("border" in score.terms) {  // modes holes and pattern
    rows.push([t("ui.metric.layers_used"), t("ui.metric.layers_of", { k: M.layers_used, n: cfg.stack.n_motor_planes })]);
    if (cfg.bounds.border) rows.push([t("ui.metric.border_depth"), `${M.border_depth.toFixed(1)} / ${round(cfg.bounds.border_width, 2)} mm`]);
  }
  $("#metrics").innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
  // The count has no weight in the modes holes and pattern, every hole counts more than the goals
  const termLabel = (k) => (k in score.weights ? t("ui.metric.weight", { term: t("ui.term." + k), percent: (score.weights[k] * 100).toFixed(0) }) : t("ui.metric.first", { term: t("ui.term." + k) }));
  $("#terms").innerHTML = Object.entries(score.terms).map(([k, v]) => `<tr><td>${esc(termLabel(k))}</td><td>${v.toFixed(3)}</td></tr>`).join("") +
    `<tr><td><b>${esc(t("ui.metric.total"))}</b></td><td><b>${score.total.toFixed(3)}</b></td></tr>`;
}

const gapColor = (gap, required) => (gap < required - GAP_EPS ? "var(--bad)" : gap < required * TIGHT_FACTOR ? COLORS.tight : "inherit");

function renderPairs() {
  const required = lastGeo.required_gap;
  $("#pairs").innerHTML = (lastGeo.closest_pairs || []).slice(0, MAX_PAIRS_SHOWN).map((p) =>
    `<tr><td>${p.a} ${esc(kindLabel(p.kind_a))} / ${p.b} ${esc(kindLabel(p.kind_b))}</td><td style="color:${gapColor(p.gap, required)}">${p.gap.toFixed(2)} mm</td></tr>`
  ).join("") || `<tr><td>${esc(t("ui.result.none"))}</td><td></td></tr>`;
}

function renderCollisions() {
  const collisions = lastGeo.collisions;
  $("#collisions").innerHTML = collisions.length
    ? collisions.map((c) => `<li style="color:var(--bad)">${esc(c.message)}</li>`).join("")
    : `<li style="color:var(--ok)">${esc(t("ui.result.no_collisions", { gap: lastGeo.required_gap.toFixed(2) }))}</li>`;
}

function renderLegend() {
  const swatch = (style, text) => `<span><i style="${style}"></i>${text}</span>`;
  $("#legend").innerHTML = lastGeo.planes.slice(1).map((p) => swatch(`background:${col(p.index)}`, esc(t("ui.legend.motor_on", { plane: p.name })))).join("") +
    swatch(`background:${COLORS.rod}`, esc(t("ui.legend.rod"))) + swatch(`background:none;border:2px solid ${COLORS.bad}`, esc(t("ui.legend.collision"))) +
    swatch(`background:${COLORS.tight};border-radius:50%;width:8px;height:8px`, esc(t("ui.legend.tight")));
}
