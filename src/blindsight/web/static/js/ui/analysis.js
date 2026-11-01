"use strict";
// Analysis without optimization. Layers, rod lengths, problems, side section and build area preview.

const analyzeLatest = latestOnly((project) => api("/api/analyze", project));

/** Update previews and analysis after every change of cfg. Late answers are discarded. */
async function refresh() {
  drawMotor();
  drawBounds();
  let response;
  try { response = await analyzeLatest(cfg); } catch (e) { return; }
  if (!response) return;  // a newer request exists meanwhile
  const errors = errorsOf(response.data);
  if (response.status !== 200 || errors.length) {
    showFieldErrors(errors);
    $("#levelInfo").innerHTML = "";
    return;
  }
  showFieldErrors([]);
  if (response.data.motor) drawMotor(response.data.motor);
  renderLevelInfo(response.data);
  drawSectionPreview(response.data);
}

function renderLevelInfo(analysis) {
  const stroke = round(cfg.rod.stroke, 2);
  const head = ["layer", "z_top", "rod_total", "below_mount", "thread"].map((k) => `<th>${esc(t("ui.levels.head." + k))}</th>`).join("");
  let html = `<table class="grid"><tr>${head}</tr>`;
  for (const p of analysis.planes) {
    if (p.index === 0) {
      html += `<tr><td>G0</td><td>${round(p.z_top, 2)}</td><td colspan=3>${esc(t("ui.levels.reference", { stroke }))}</td></tr>`;
      continue;
    }
    const rod = p.rod;
    html += `<tr><td>${esc(p.name)}</td><td>${round(p.z_top, 2)}</td><td>${round(rod.length, 1)}</td><td>${round(rod.length_below_mount, 1)}</td>` +
      `<td>${round(rod.engage_below_actual, 1)} / ${round(rod.engage_above_actual, 1)}</td></tr>`;
    if (p.problems.length) html += `<tr><td colspan=5 class="bad">${p.problems.map(esc).join("<br>")}</td></tr>`;
  }
  $("#levelInfo").innerHTML = html + `</table><p class="hint">${esc(t("ui.levels.summary", { stroke, gap: round(analysis.required_gap, 2) }))}</p>`;
}

/** Side section of the layers with one rod and one motor per motor layer. */
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
  const b = cfg.bounds;  // origin (0, 0) at the bottom left
  const w = b.width, h = b.height;
  if (!(w > 0 && h > 0)) return;
  const m = Math.max(w, h) * 0.04, thin = w / 600;
  svg.setAttribute("viewBox", `${-m} ${-h - m} ${w + 2 * m} ${h + 2 * m}`);
  drawBoardFrame(svg, w, h, b.edge_margin, b.edge_margin + (b.border ? b.border_width : 0), w / 400);
  const obstacleStyle = { fill: COLORS.obstacle, stroke: COLORS.obstacleStroke, "stroke-width": thin };
  for (const o of cfg.obstacles) {
    if (o.shape === "circle") el("circle", { cx: o.x, cy: -o.y, r: o.r, ...obstacleStyle }, svg);
    else el("rect", { x: o.x - o.w / 2, y: -o.y - o.h / 2, width: o.w, height: o.h, transform: `rotate(${-o.angle} ${o.x} ${-o.y})`, ...obstacleStyle }, svg);
  }
  for (const [plane, zones] of Object.entries(cfg.stack.mount_zones || {})) {
    for (const z of zones) el("rect", { x: z[0], y: -z[3], width: z[2] - z[0], height: z[3] - z[1], fill: col(+plane), "fill-opacity": 0.12, stroke: col(+plane), "stroke-width": thin }, svg);
  }
}
