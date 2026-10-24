"use strict";
// Manuelles Bearbeiten einer Anordnung in der Draufsicht. Jede Aenderung prueft der Server (/api/validate).

const EDIT_DEBOUNCE_MS = 120;
const NEW_UNIT_ID = 1e6;  // vorlaeufige Id einer neuen Einheit bis zur Pruefung
const DRAG_THRESHOLD_PX = 3;  // erst ab dieser Bewegung gilt ein Klick als Ziehen

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
    // Nur echtes Ziehen veraendert die Anordnung. Ein Klick waehlt nur aus
    if (drag && drag.moved) pushEdit();
    drag = null;
  });
}

/** Vorschau waehrend des Ziehens. Die Bauteile ersetzt der Server nach der Pruefung. */
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
  const unitControls = u ? `Einheit ${u.id}:
    Ebene <select id="edPlane">${planes}</select> Winkel <input id="edAngle" type="number" step="any" value="${esc(u.angle)}" style="width:80px">
    x [mm] <input id="edX" type="number" step="any" value="${esc(round(round(u.x), 3))}" style="width:80px">
    y [mm] <input id="edY" type="number" step="any" value="${esc(round(round(u.y), 3))}" style="width:80px">
    <button id="edDel">Entfernen</button>` : "Keine Einheit gewählt.";
  box.innerHTML = `<b>Bearbeiten.</b> Stange in der Draufsicht ziehen. Jede Änderung wird sofort geprüft. ${unitControls} ` +
    `<button id="edAdd">Einheit hinzufügen</button> <button id="edReset">Zurücksetzen</button>` +
    (editError ? `<div style="color:var(--bad)">${esc(editError)}</div>` : "");
  if (u) bindUnitControls();
  $("#edAdd").addEventListener("click", addUnit);
  $("#edReset").addEventListener("click", resetEdits);
}

function bindUnitControls() {
  // Aenderung an der gewaehlten Einheit. Ungueltige Zahlen werden ignoriert
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

/** Zurueck zum Stand vor dem Bearbeiten (auch fuer aus einer Datei geladene Ergebnisse). */
async function resetEdits() {
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

/** Prueft die bearbeitete Anordnung (gedrosselt, nur die neueste Antwort zaehlt). */
function pushEdit() {
  clearTimeout(editTimer);
  editTimer = setTimeout(async () => {
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
