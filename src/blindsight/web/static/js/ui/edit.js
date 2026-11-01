"use strict";
// Manual editing of an arrangement in the top view. The server checks every change (/api/validate).

const EDIT_DEBOUNCE_MS = 120;
const NEW_UNIT_ID = 1e6;  // provisional id of a new unit until the check
const DRAG_THRESHOLD_PX = 3;  // from this movement on a click counts as dragging

let editMode = false;
let selUnit = null;
let editTimer = null;
let editError = "";
const validateLatest = latestOnly((body) => api("/api/validate", body));

const selectedUnit = () => (lastGeo ? lastGeo.units.find((u) => u.id === selUnit) : undefined);
const editableView = () => !["iso", "section"].includes($("#viewSel").value);

function initEdit() {
  const svg = $("#view");
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (!editMode || !lastGeo || !editableView()) return;
    const id = e.target.dataset && e.target.dataset.unit;
    if (id === undefined || id === "") return;
    selUnit = +id;
    drag = { x: e.clientX, y: e.clientY, moved: false };
    svg.setPointerCapture(e.pointerId);
    renderEditPanel();
    drawView();
  });
  svg.addEventListener("pointermove", (e) => {
    const u = selectedUnit();
    if (!drag || !u) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < DRAG_THRESHOLD_PX) return;
    drag.moved = true;
    const [x, y] = svgPoint(svg, e);
    u.x = Math.round(x * 100) / 100;
    u.y = Math.round(y * 100) / 100;
    moveUnitLocally(u);
    drawView();
  });
  svg.addEventListener("pointerup", () => {
    // Only real dragging changes the arrangement. A click only selects
    if (drag && drag.moved) pushEdit();
    drag = null;
  });
}

/** Preview while dragging. The server replaces the parts after the check. */
function moveUnitLocally(u) {
  const dx = u.x - u._x0, dy = u.y - u._y0;
  u.parts.forEach((p) => { p.outline = p.outline.map(([x, y]) => [x + dx, y + dy]); });
  u._x0 = u.x;
  u._y0 = u.y;
}

function renderEditPanel() {
  const box = $("#editPanel");
  box.hidden = !editMode || !lastGeo;
  if (box.hidden) return;
  lastGeo.units.forEach((u) => { if (u._x0 === undefined) { u._x0 = u.x; u._y0 = u.y; } });
  const u = selectedUnit();
  const planes = lastGeo.planes.slice(1).map((p) => `<option value="${p.index}" ${u && u.plane === p.index ? "selected" : ""}>${esc(p.name)}</option>`).join("");
  const unitControls = u ? `${esc(t("ui.edit.unit", { id: u.id }))}
    ${esc(t("ui.edit.layer"))} <select id="edPlane">${planes}</select> ${esc(t("ui.edit.angle"))} <input id="edAngle" type="number" step="any" value="${esc(u.angle)}" style="width:80px">
    x [mm] <input id="edX" type="number" step="any" value="${esc(round(round(u.x), 3))}" style="width:80px">
    y [mm] <input id="edY" type="number" step="any" value="${esc(round(round(u.y), 3))}" style="width:80px">
    <button id="edDel">${esc(t("ui.edit.remove"))}</button>` : esc(t("ui.edit.none_selected"));
  box.innerHTML = `<b>${esc(t("ui.edit.title"))}</b> ${esc(t("ui.edit.hint"))} ${unitControls} ` +
    `<button id="edAdd">${esc(t("ui.edit.add"))}</button> <button id="edReset">${esc(t("ui.edit.reset"))}</button>` +
    (editError ? `<div style="color:var(--bad)">${esc(editError)}</div>` : "");
  if (u) bindUnitControls();
  $("#edAdd").addEventListener("click", addUnit);
  $("#edReset").addEventListener("click", resetEdits);
}

function bindUnitControls() {
  // Change of the selected unit. Invalid numbers are ignored
  const update = (apply) => () => { const q = selectedUnit(); if (q && apply(q) !== false) pushEdit(); };
  const number = (id) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : undefined; };
  $("#edPlane").addEventListener("change", update((q) => { q.plane = +$("#edPlane").value; }));
  $("#edAngle").addEventListener("change", update((q) => { const v = number("#edAngle"); if (v === undefined) return false; q.angle = v; }));
  $("#edX").addEventListener("change", update((q) => { const v = number("#edX"); if (v === undefined) return false; q.x = v; }));
  $("#edY").addEventListener("change", update((q) => { const v = number("#edY"); if (v === undefined) return false; q.y = v; }));
  $("#edDel").addEventListener("click", () => {
    lastGeo.units = lastGeo.units.filter((q) => q.id !== selUnit);
    selUnit = null;
    pushEdit();
  });
}

function addUnit() {
  const b = lastGeo.bounds;
  lastGeo.units.push({ id: NEW_UNIT_ID, x: (b.xmin + b.xmax) / 2, y: (b.ymin + b.ymax) / 2, plane: 1, angle: 0, cd: null, parts: [], rod: {} });
  selUnit = NEW_UNIT_ID;
  pushEdit();
}

/** Forget an edit check that has not been sent yet (the shown geometry is replaced). */
function cancelPendingEdit() {
  clearTimeout(editTimer);
  editTimer = null;
}

/** Back to the state before editing (also for results loaded from a file). */
async function resetEdits() {
  // Leaving an edited field fires its change event right before this click. Its check must not undo the reset
  cancelPendingEdit();
  editError = "";
  if (resultSource === "job" && jobId) { await loadResult(solIndex); return; }
  if (!originalPlacements) return;
  const response = await validateLatest({ project: cfg, placements: originalPlacements });
  if (!response || response.status !== 200) return;
  lastGeo = response.data.geometry;
  edited = false;
  selUnit = null;
  renderResult();
}

/** Check the edited arrangement (debounced, only the newest answer counts). */
function pushEdit() {
  clearTimeout(editTimer);
  editTimer = setTimeout(async () => {
    if (!lastGeo) return;
    const keep = lastGeo.units.findIndex((u) => u.id === selUnit);
    const response = await validateLatest({ project: cfg, placements: placementsOf(lastGeo) });
    if (!response) return;
    if (response.status !== 200) {
      editError = errorsOf(response.data).join(" ");
      renderEditPanel();
      return;
    }
    editError = "";
    lastGeo = response.data.geometry;
    edited = true;
    selUnit = keep >= 0 && lastGeo.units[keep] ? lastGeo.units[keep].id : null;
    renderResult();
  }, EDIT_DEBOUNCE_MS);
}
