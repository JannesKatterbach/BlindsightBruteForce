"use strict";
// Ergebnisansichten. Draufsicht, einzelne Ebene, Seitenschnitt, raeumliche Ansicht (mit Maus drehbar).

const isoRotation = { angle: 35, tilt: 0.55 };  // Drehung in Grad, Neigung 0.1 (flach) bis 0.95 (steil)
const ISO_TILT_MIN = 0.1, ISO_TILT_MAX = 0.95;

// Ansicht -> Zeichenfunktion. Eine neue Ansicht ist ein Eintrag hier und eine Option in #viewSel
const VIEWS = {
  top: (svg, g) => drawPlan(svg, g, null, false),
  plane: (svg, g) => drawPlan(svg, g, parseInt($("#planeSel").value, 10), false),
  section: drawSection,
  iso: drawIso,
};

function drawView() {
  if (!lastGeo) return;
  const svg = $("#view"), mode = $("#viewSel").value;
  svg.innerHTML = "";
  $("#planeLabel").style.display = mode === "plane" ? "" : "none";
  (VIEWS[mode] || VIEWS.top)(svg, lastGeo);
}

/** Durchquert die Stange der Einheit die Ebene (dann braucht die Ebene ein Loch)? */
function rodPasses(g, unitData, planeIndex) {
  const plane = g.planes[planeIndex];
  return unitData.rod.bottom_retracted <= plane.z_top && unitData.rod.tip_extended >= plane.z_bottom;
}

/** Draufsicht. plane null zeigt alle Ebenen, live ist die vereinfachte Vorschau waehrend der Suche. */
function drawPlan(svg, g, plane, live) {
  svg.innerHTML = "";
  const b = g.bounds, w = b.xmax - b.xmin, h = b.ymax - b.ymin, m = Math.max(w, h) * 0.04;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-b.ymax - m} ${w + 2 * m} ${h + 2 * m}`);
  const ctx = { svg, g, w, fs: Math.max(w, h) / 50, pts: (outline) => outline.map(([x, y]) => `${x},${-y}`).join(" ") };
  el("rect", { x: b.xmin, y: -b.ymax, width: w, height: h, fill: "none", stroke: "currentColor", "stroke-width": w / 500 }, svg);
  g.obstacles.forEach((o) => el("polygon", { points: ctx.pts(o.outline), fill: COLORS.obstacle, stroke: COLORS.obstacleStroke, "stroke-width": w / 700 }, svg));
  drawPlanMotors(ctx, plane);
  drawPlanRods(ctx, plane, live);
  if (!live && $("#optDist").checked && plane == null) drawPlanDistances(ctx);
  if (!live) drawPlanTightSpots(ctx);
  if (!live) drawTileGrid(ctx);
  g.collisions.forEach((c) => el("circle", { cx: c.x, cy: -c.y, r: ctx.fs * 1.4, fill: "none", stroke: COLORS.bad, "stroke-width": w / 400, "pointer-events": "none" }, svg));
}

function drawPlanMotors({ svg, g, w, pts }, plane) {
  for (const u of g.units) {
    if (plane != null && u.plane !== plane) continue;
    for (const part of u.parts) {
      if (part.kind === "rod") continue;
      el("polygon", { points: pts(part.outline), fill: col(u.plane), "fill-opacity": part.kind === "gear" ? 0.85 : 0.35, stroke: col(u.plane), "stroke-width": w / 700, "data-unit": u.id }, svg);
    }
  }
}

function drawPlanRods({ svg, g, w, fs }, plane, live) {
  const r = g.rod_diameter / 2;
  for (const u of g.units) {
    if (plane != null && !(u.plane === plane || rodPasses(g, u, plane))) continue;
    if (plane != null) el("circle", { cx: u.x, cy: -u.y, r: g.hole_diameter / 2, fill: "none", stroke: "currentColor", "stroke-width": w / 700 }, svg);
    el("circle", { cx: u.x, cy: -u.y, r: Math.max(r, w / 200), fill: u.id === selUnit ? COLORS.bad : COLORS.rod, "data-unit": u.id, class: editMode && !live ? "handle" : "" }, svg);
    svgText(svg, { x: u.x + r + fs * 0.3, y: -u.y - r, "font-size": fs, fill: "currentColor", "pointer-events": "none" }, u.id);
  }
}

/** Linie von jeder Stange zur naechsten, Abstand einmal je Paar beschriftet. */
function drawPlanDistances({ svg, g, w, fs }) {
  if (g.units.length < 2) return;
  for (const u of g.units) {
    let nearest = null, best = Infinity;
    for (const v of g.units) {
      const d = v === u ? Infinity : Math.hypot(v.x - u.x, v.y - u.y);
      if (d < best) { best = d; nearest = v; }
    }
    el("line", { x1: u.x, y1: -u.y, x2: nearest.x, y2: -nearest.y, stroke: "#777", "stroke-width": w / 900, "stroke-dasharray": `${fs / 3} ${fs / 3}`, "pointer-events": "none" }, svg);
    if (u.id < nearest.id) svgText(svg, { x: (u.x + nearest.x) / 2, y: -(u.y + nearest.y) / 2, "font-size": fs * 0.8, fill: "#888", "pointer-events": "none" }, best.toFixed(1));
  }
}

function drawPlanTightSpots({ svg, g, w, fs }) {
  for (const p of g.closest_pairs || []) {
    if (p.gap >= g.required_gap * TIGHT_FACTOR) continue;
    const stroke = p.gap < g.required_gap - GAP_EPS ? COLORS.bad : COLORS.tight;
    el("circle", { cx: p.x, cy: -p.y, r: fs, fill: "none", stroke, "stroke-width": w / 600, "pointer-events": "none" }, svg);
  }
}

/** Outlines of the placed tiles of a repeating pattern. */
function drawTileGrid({ svg, w }) {
  const tile = currentTile();
  if (!tile) return;
  for (const [x, y] of tile.origins) {
    el("rect", { x, y: -(y + tile.height), width: tile.width, height: tile.height, fill: "none", stroke: "#8a6", "stroke-width": w / 900, "stroke-dasharray": `${w / 300} ${w / 300}`, "pointer-events": "none", class: "tile" }, svg);
  }
}

const lowestZ = (g) => Math.min(...g.planes.map((p) => p.z_bottom), ...g.units.map((u) => u.rod.bottom_retracted));

function drawSection(svg, g) {
  const b = g.bounds, w = b.xmax - b.xmin;
  const zmin = lowestZ(g) - 5, zmax = g.stroke + 5, m = w * 0.04, fs = (zmax - zmin) / 35;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-zmax} ${w + 2 * m} ${zmax - zmin}`);
  for (const p of g.planes) {
    el("rect", { x: b.xmin, y: -p.z_top, width: w, height: p.thickness, fill: p.index ? col(p.index) : COLORS.g0, "fill-opacity": 0.45 }, svg);
    svgText(svg, { x: b.xmin + 1, y: -p.z_top - 1, "font-size": fs, fill: "currentColor" }, `${p.name}  z=${round(p.z_top, 2)}`);
  }
  el("line", { x1: b.xmin, x2: b.xmax, y1: -g.stroke, y2: -g.stroke, stroke: COLORS.bad, "stroke-dasharray": "2 2", "stroke-width": w / 600 }, svg);
  for (const u of g.units) {
    el("rect", { x: u.x - g.rod_diameter / 2, y: -u.rod.tip_extended, width: g.rod_diameter, height: u.rod.length, fill: COLORS.rod, "fill-opacity": 0.3 }, svg);
    for (const part of u.parts.filter((q) => q.kind !== "rod")) {
      const xs = part.outline.map((q) => q[0]), x0 = Math.min(...xs), x1 = Math.max(...xs);
      el("rect", { x: x0, y: -part.z1, width: x1 - x0, height: part.z1 - part.z0, fill: col(u.plane), "fill-opacity": 0.35, stroke: col(u.plane), "stroke-width": w / 800 }, svg);
    }
  }
}

function drawIso(svg, g) {
  const a = isoRotation.angle * Math.PI / 180, tilt = isoRotation.tilt, b = g.bounds;
  const cx = (b.xmin + b.xmax) / 2, cy = (b.ymin + b.ymax) / 2;
  const project = (x, y, z) => {
    const dx = x - cx, dy = y - cy;
    const rx = dx * Math.cos(a) - dy * Math.sin(a), ry = dx * Math.sin(a) + dy * Math.cos(a);
    return [rx, -(ry * tilt + z * Math.sqrt(1 - tilt * tilt))];
  };
  const R = Math.hypot(b.xmax - b.xmin, b.ymax - b.ymin) / 2 + 10, zmin = lowestZ(g), zmax = g.stroke;
  svg.setAttribute("viewBox", `${-R} ${-(zmax + R * tilt)} ${2 * R} ${zmax - zmin + 2 * R * tilt + 10}`);
  const poly = (points) => points.map((p) => p.join(",")).join(" ");
  const corners = [[b.xmin, b.ymin], [b.xmax, b.ymin], [b.xmax, b.ymax], [b.xmin, b.ymax]];
  for (const p of g.planes) {
    el("polygon", { points: poly(corners.map(([x, y]) => project(x, y, p.z_top))), fill: p.index ? col(p.index) : COLORS.g0, "fill-opacity": 0.18, stroke: "currentColor", "stroke-width": 0.2 }, svg);
  }
  for (const u of g.units) {
    const [bx, by] = project(u.x, u.y, u.rod.bottom_retracted), [tx, ty] = project(u.x, u.y, u.rod.tip_extended);
    el("line", { x1: bx, y1: by, x2: tx, y2: ty, stroke: COLORS.rod, "stroke-width": g.rod_diameter * 0.9, "stroke-opacity": 0.8 }, svg);
    for (const part of u.parts.filter((q) => q.kind !== "rod")) {
      el("polygon", { points: poly(part.outline.map(([x, y]) => project(x, y, part.z1))), fill: col(u.plane), "fill-opacity": 0.55, stroke: col(u.plane), "stroke-width": 0.2 }, svg);
    }
  }
}

function initIsoDrag() {
  const svg = $("#view");
  let start = null;
  svg.addEventListener("pointerdown", (e) => {
    if ($("#viewSel").value !== "iso") return;
    start = { x: e.clientX, y: e.clientY, angle: isoRotation.angle, tilt: isoRotation.tilt };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!start) return;
    isoRotation.angle = start.angle + (e.clientX - start.x) * 0.5;
    isoRotation.tilt = Math.min(ISO_TILT_MAX, Math.max(ISO_TILT_MIN, start.tilt + (e.clientY - start.y) * 0.004));
    drawView();
  });
  svg.addEventListener("pointerup", () => { start = null; });
}
