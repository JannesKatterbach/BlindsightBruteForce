"use strict";
// Motor preview on the Geometry tab (display only, editing happens on the Motor sketch tab),
// motor library in the browser and SVG import.

// Fields that a sketch determines. They are locked and filled from the sketch
const SKETCH_OVERRIDDEN = ["motor.width", "motor.depth", "motor.shaft_x", "motor.gear_gap", "motor.gear_diameter", "motor.gear_width", "motor.center_distance"];
const LIBRARY_KEY = "blindsight.motors";
let motorShape = null;  // housing and gear in the rod frame from the last analysis (needed for sketches)

const hasSketch = (motor) => !!(motor.sketch && Array.isArray(motor.sketch.entities) && motor.sketch.entities.length);

/** Housing outline in the rod frame (origin = rod axis, y up). With a sketch it comes from the analysis. */
function motorPolygonRod(m) {
  if (hasSketch(m)) return motorShape ? motorShape.housing : [];
  const hasOutline = m.outline && m.outline.length >= 3;
  const top = hasOutline ? Math.max(...m.outline.map((p) => p[1])) : m.depth / 2;
  const rx = m.shaft_x + m.center_distance;
  const ry = top + m.gear_gap + m.gear_width / 2;
  const hw = m.width / 2, hd = m.depth / 2;
  const poly = hasOutline ? m.outline : [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]];
  return poly.map(([x, y]) => [x - rx, y - ry]);
}

function drawMotor(shape) {
  if (shape) motorShape = shape;
  const svg = $("#motorPreview");
  svg.innerHTML = "";
  const m = cfg.motor, r = cfg.rod.diameter / 2;
  updateSketchLock();
  if (![m.width, m.depth, cfg.rod.diameter, m.gear_diameter, m.gear_width].every((v) => v > 0)) return;
  const poly = motorPolygonRod(m), gr = m.gear_diameter / 2, gh = m.gear_width / 2, cd = m.center_distance;
  if (poly.length < 3) return;
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

/** Lock the fields determined by the sketch (with a hint) and unlock them without a sketch. */
function updateSketchLock() {
  const locked = hasSketch(cfg.motor);
  $("#sketchNote").hidden = !locked;
  for (const path of SKETCH_OVERRIDDEN) {
    const input = document.querySelector(`[data-path="${path}"]`);
    if (!input) continue;
    input.disabled = locked;
    input.title = locked ? t("ui.motor.locked") : input.dataset.tip;  // the tooltip used to get lost
  }
}

/** Mouse coordinates in the SVG coordinate system (y up). */
function svgPoint(svg, ev) {
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX;
  pt.y = ev.clientY;
  const p = pt.matrixTransform(svg.getScreenCTM().inverse());
  return [p.x, -p.y];
}

/** Update all views after a change of the motor (the sketch too). */
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

// --- Library --------------------------------------------------------------------------------------
function libLoad() {
  try { return JSON.parse(localStorage.getItem(LIBRARY_KEY) || "{}"); } catch (e) { return {}; }
}
function libStore(library) {
  try { localStorage.setItem(LIBRARY_KEY, JSON.stringify(library)); return true; } catch (e) { alert(t("ui.library.store_failed")); return false; }
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
    try { cfg.motor = withDefaults(JSON.parse(await file.text())); } catch (err) { alert(t("ui.library.bad_file")); return; }
    motorChanged();
  });
  $("#svgMotor").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    resetFileInput(e.target);
    if (file) await importSvgMotor(await file.text());
  });
}

/** SVG import. Asks for the scale if it is ambiguous. */
async function importSvgMotor(svgText) {
  const message = $("#svgMotorMsg");
  const body = { svg: svgText };
  for (;;) {
    body.motor = cfg.motor;
    const { data } = await api("/api/svg-motor-import", body);
    if (errorsOf(data).length) { message.textContent = errorsOf(data).join(" "); return; }
    if (data.scale_required) {
      const answer = prompt(data.message + "\n" + t("ui.svg.ask_scale"));
      const scale = parseFloat(answer);
      if (!answer || !(scale > 0)) { message.textContent = t("ui.svg.cancelled"); return; }
      body.mm_per_unit = scale;
      continue;
    }
    Object.assign(cfg.motor, { outline: null, sketch: data.sketch, width: data.width, depth: data.depth });
    motorChanged();
    message.textContent = t("ui.svg.imported", { width: data.width.toFixed(2), depth: data.depth.toFixed(2), notes: data.notes.join(" ") });
    return;
  }
}
