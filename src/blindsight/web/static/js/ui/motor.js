"use strict";
// Motor Vorschau im Reiter Geometrie (nur Anzeige, bearbeitet wird im Reiter Motor Skizze),
// Motor Bibliothek im Browser und SVG Import.

// Felder, die bei vorhandener Skizze keine Wirkung haben und gesperrt werden
const SKETCH_OVERRIDDEN = ["motor.width", "motor.depth", "motor.shaft_x", "motor.gear_gap"];
const LIBRARY_KEY = "blindsight.motors";

const hasSketch = (motor) => !!(motor.sketch && motor.sketch.points && motor.sketch.points.length >= 3);

/** Gehaeusekontur im Stangenrahmen (Ursprung = Stangenachse, y nach oben). */
function motorPolygonRod(m) {
  if (hasSketch(m)) return m.sketch.points;
  const hasOutline = m.outline && m.outline.length >= 3;
  const top = hasOutline ? Math.max(...m.outline.map((p) => p[1])) : m.depth / 2;
  const rx = m.shaft_x + m.center_distance;
  const ry = top + m.gear_gap + m.gear_width / 2;
  const hw = m.width / 2, hd = m.depth / 2;
  const poly = hasOutline ? m.outline : [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]];
  return poly.map(([x, y]) => [x - rx, y - ry]);
}

function drawMotor() {
  const svg = $("#motorPreview");
  svg.innerHTML = "";
  const m = cfg.motor, r = cfg.rod.diameter / 2;
  updateSketchLock();
  if (![m.width, m.depth, cfg.rod.diameter, m.gear_diameter, m.gear_width].every((v) => v > 0)) return;
  const poly = motorPolygonRod(m), gr = m.gear_diameter / 2, gh = m.gear_width / 2, cd = m.center_distance;
  const xs = poly.map((p) => p[0]).concat([-cd - gr, -cd + gr, r, -r]);
  const ys = poly.map((p) => p[1]).concat([-gh, gh, r, -r]);
  const pad = 8, x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
  svg.setAttribute("viewBox", `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`);
  const sw = (x1 - x0) / 300, dash = `${sw * 3} ${sw * 3}`;
  el("polygon", { points: poly.map((p) => `${p[0]},${-p[1]}`).join(" "), fill: "#999", "fill-opacity": 0.5, stroke: "#555", "stroke-width": sw }, svg);
  el("rect", { x: -cd - gr, y: -gh, width: 2 * gr, height: 2 * gh, fill: COLORS.gear, stroke: "#333", "stroke-width": sw }, svg);
  el("circle", { cx: 0, cy: 0, r: r + cfg.rod.hole_clearance, fill: "none", stroke: "currentColor", "stroke-dasharray": dash, "stroke-width": sw }, svg);
  el("circle", { id: "previewRod", cx: 0, cy: 0, r, fill: COLORS.rod }, svg);
  el("line", { x1: -cd, y1: 0, x2: 0, y2: 0, stroke: COLORS.bad, "stroke-width": sw, "stroke-dasharray": dash }, svg);
}

/** Sperrt die von der Skizze bestimmten Felder (mit Hinweis) und gibt sie ohne Skizze wieder frei. */
function updateSketchLock() {
  const locked = hasSketch(cfg.motor);
  $("#sketchNote").hidden = !locked;
  for (const path of SKETCH_OVERRIDDEN) {
    const input = document.querySelector(`[data-path="${path}"]`);
    if (!input) continue;
    input.disabled = locked;
    input.title = locked ? "Wird von der Motor Skizze bestimmt" : input.dataset.tip;  // frueher ging der Tooltip verloren
  }
}

/** Mauskoordinaten im SVG Koordinatensystem (y nach oben). */
function svgPoint(svg, ev) {
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  return [p.x, -p.y];
}

/** Nach einer Aenderung am Motor alle Ansichten aktualisieren (auch die Skizze). */
function motorChanged() {
  writeInputs();
  drawMotor();
  refresh();
  if (window.skReload) skReload();
}

function initMotorPreview() {
  $("#btnOpenSketch").addEventListener("click", () => switchTab("sketch"));
  $("#btnDropSketch").addEventListener("click", () => { cfg.motor.sketch = null; motorChanged(); });
}

// --- Bibliothek --------------------------------------------------------------------------------------
function libLoad() {
  try { return JSON.parse(localStorage.getItem(LIBRARY_KEY) || "{}"); } catch (e) { return {}; }
}
function libStore(library) {
  try { localStorage.setItem(LIBRARY_KEY, JSON.stringify(library)); return true; } catch (e) { alert("Speichern im Browser nicht möglich."); return false; }
}
function libRender() {
  $("#libSel").innerHTML = Object.keys(libLoad()).map((name) => `<option>${esc(name)}</option>`).join("");
}
const withDefaults = (motor) => ({ ...clone(defaults.motor), ...motor });

function initLibrary() {
  libRender();
  $("#libSave").addEventListener("click", () => {
    const name = $("#libName").value.trim();
    if (!name) return;
    const library = libLoad();
    library[name] = cfg.motor;
    if (libStore(library)) libRender();
  });
  $("#libLoad").addEventListener("click", () => {
    const motor = libLoad()[$("#libSel").value];
    if (motor) { cfg.motor = withDefaults(motor); motorChanged(); }
  });
  $("#libDel").addEventListener("click", () => {
    const library = libLoad();
    delete library[$("#libSel").value];
    libStore(library);
    libRender();
  });
  $("#libExport").addEventListener("click", () => download("blindsight-motor.json", JSON.stringify(cfg.motor, null, 2), "application/json"));
  $("#libImport").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    resetFileInput(e.target);
    if (!file) return;
    try { cfg.motor = withDefaults(JSON.parse(await file.text())); } catch (err) { alert("Keine gültige Motor Datei."); return; }
    motorChanged();
  });
  $("#svgMotor").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    resetFileInput(e.target);
    if (file) await importSvgMotor(await file.text());
  });
}

/** SVG Import. Fragt den Massstab nach, wenn er nicht eindeutig ist. */
async function importSvgMotor(svgText) {
  const message = $("#svgMotorMsg");
  const body = { svg: svgText };
  for (;;) {
    body.motor = cfg.motor;
    const { data } = await api("/api/svg-motor-import", body);
    if (errorsOf(data).length) { message.textContent = errorsOf(data).join(" "); return; }
    if (data.scale_required) {
      const answer = prompt(data.message + "\nmm pro SVG Einheit (zum Beispiel 1 bei Einheit mm, 0.2646 bei px mit 96 dpi):");
      const scale = parseFloat(answer);
      if (!answer || !(scale > 0)) { message.textContent = "Abgebrochen. Kein gültiger Maßstab."; return; }
      body.mm_per_unit = scale;
      continue;
    }
    Object.assign(cfg.motor, { outline: null, sketch: { points: data.sketch.points, constraints: [] }, width: data.width, depth: data.depth });
    motorChanged();
    message.textContent = `Übernommen. ${data.width.toFixed(2)} x ${data.depth.toFixed(2)} mm ${data.notes.join(" ")}`;
    return;
  }
}
