"use strict";
// Analyse ohne Optimierung. Ebenen, Stangenlaengen, Probleme, Seitenschnitt und Bauraum Vorschau.

const analyzeLatest = latestOnly((project) => api("/api/analyze", project));

/** Aktualisiert Vorschauen und Analyse nach jeder Aenderung an cfg. Spaete Antworten werden verworfen. */
async function refresh() {
  drawMotor();
  drawBounds();
  let response;
  try { response = await analyzeLatest(cfg); } catch (e) { return; }
  if (!response) return;  // inzwischen gibt es eine neuere Anfrage
  const errors = errorsOf(response.data);
  if (response.status !== 200 || errors.length) {
    showFieldErrors(errors);
    $("#levelInfo").innerHTML = "";
    return;
  }
  showFieldErrors([]);
  renderLevelInfo(response.data);
  drawSectionPreview(response.data);
}

function renderLevelInfo(analysis) {
  const stroke = round(cfg.rod.stroke, 2);
  let html = `<table class="grid"><tr><th>Ebene</th><th>z oben [mm]</th><th>Stange gesamt</th><th>unter Montage</th><th>Gewinde unten / oben</th></tr>`;
  for (const p of analysis.planes) {
    if (p.index === 0) {
      html += `<tr><td>G0</td><td>${round(p.z_top, 2)}</td><td colspan=3>Referenzebene, Hub ${stroke} mm darüber</td></tr>`;
      continue;
    }
    const rod = p.rod;
    html += `<tr><td>${esc(p.name)}</td><td>${round(p.z_top, 2)}</td><td>${round(rod.length, 1)}</td><td>${round(rod.length_below_mount, 1)}</td>` +
      `<td>${round(rod.engage_below_actual, 1)} / ${round(rod.engage_above_actual, 1)}</td></tr>`;
    if (p.problems.length) html += `<tr><td colspan=5 class="bad">${p.problems.map(esc).join("<br>")}</td></tr>`;
  }
  $("#levelInfo").innerHTML = html + `</table><p class="hint">Alle Stangen erreichen ${stroke} mm über G0. Längen in mm. ` +
    `Wirksamer Mindestabstand ${round(analysis.required_gap, 2)} mm.</p>`;
}

/** Seitenschnitt der Ebenen mit je einer Stange und einem Motor pro Motorebene. */
function drawSectionPreview(analysis) {
  const svg = $("#sectionPreview");
  svg.innerHTML = "";
  const planes = analysis.planes;
  const zmin = Math.min(...planes.map((p) => p.z_bottom), ...planes.slice(1).map((p) => p.rod.bottom_retracted)) - 10;
  const zmax = cfg.rod.stroke + 10;
  svg.setAttribute("viewBox", `0 ${-zmax} 300 ${zmax - zmin}`);
  const d = cfg.rod.diameter, motorHeight = cfg.motor.height, mountTop = cfg.motor.mount === "top";
  for (const p of planes) {
    el("rect", { x: 10, y: -p.z_top, width: 280, height: p.thickness, fill: p.index ? col(p.index) : COLORS.g0, "fill-opacity": 0.6 }, svg);
    svgText(svg, { x: 14, y: -p.z_top - 1, "font-size": 6, fill: "currentColor" }, p.name);
    if (!p.index) continue;
    const x = 40 + p.index * Math.min(40, 220 / planes.length);
    el("rect", { x: x - d / 2, y: -p.rod.tip_extended, width: d, height: p.rod.length, fill: COLORS.rod, "fill-opacity": 0.35 }, svg);
    el("rect", { x: x - d / 2, y: -p.rod.tip_extended, width: d, height: p.rod.tip_extended - p.rod.bottom_extended, fill: COLORS.rod }, svg);
    el("rect", { x: x + 5, y: mountTop ? -(p.z_top + motorHeight) : -p.z_bottom, width: 22, height: motorHeight, fill: col(p.index), "fill-opacity": 0.5 }, svg);
  }
}

function drawBounds() {
  const svg = $("#boundsPreview");
  svg.innerHTML = "";
  const b = cfg.bounds;
  if (!(b.xmax > b.xmin && b.ymax > b.ymin)) return;
  const w = b.xmax - b.xmin, h = b.ymax - b.ymin, m = Math.max(w, h) * 0.04, thin = w / 600;
  svg.setAttribute("viewBox", `${b.xmin - m} ${-b.ymax - m} ${w + 2 * m} ${h + 2 * m}`);
  el("rect", { x: b.xmin, y: -b.ymax, width: w, height: h, fill: "none", stroke: "currentColor", "stroke-width": w / 400 }, svg);
  const e = b.edge_margin;
  if (e > 0) el("rect", { x: b.xmin + e, y: -b.ymax + e, width: w - 2 * e, height: h - 2 * e, fill: "none", stroke: "#888", "stroke-dasharray": "2 2", "stroke-width": thin }, svg);
  const obstacleStyle = { fill: COLORS.obstacle, stroke: COLORS.obstacleStroke, "stroke-width": thin };
  for (const o of cfg.obstacles) {
    if (o.shape === "circle") el("circle", { cx: o.x, cy: -o.y, r: o.r, ...obstacleStyle }, svg);
    else el("rect", { x: o.x - o.w / 2, y: -o.y - o.h / 2, width: o.w, height: o.h, transform: `rotate(${-o.angle} ${o.x} ${-o.y})`, ...obstacleStyle }, svg);
  }
  for (const [plane, zones] of Object.entries(cfg.stack.mount_zones || {})) {
    for (const z of zones) el("rect", { x: z[0], y: -z[3], width: z[2] - z[0], height: z[3] - z[1], fill: col(+plane), "fill-opacity": 0.12, stroke: col(+plane), "stroke-width": thin }, svg);
  }
}
