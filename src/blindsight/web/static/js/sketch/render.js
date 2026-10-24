"use strict";
// Motor sketch. Canvas (grid, gear, housing, rod, dimensions, constraint symbols, points).
// Drawing happens in mm in the rod frame (y up). px() converts sizes in screen pixels.

(() => {
  const MIN_GRID_PX = 22;  // smallest distance of the grid lines on the screen
  // Symbols of relations at a side
  const SIDE_GLYPHS = [["parallel", "∥"], ["perpendicular", "⊥"], ["equal", "="], ["horizontal", "H"], ["vertical", "V"], ["angle_sides", "∠"], ["dist_side", "⇥"]];

  function canvasSize() {
    const canvas = $("#skCanvas");
    return [Math.max(200, canvas.clientWidth), Math.max(200, canvas.clientHeight)];
  }

  /** Set the view so that outline, gear and rod are visible. */
  function fit() {
    const d = cfg.rod.diameter;
    const points = SK.sk.points.concat(Sketch.gearBox(), [[d, d], [-d, -d]]);
    const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const [W, H] = canvasSize();
    SK.view.k = Math.max((x1 - x0) / (W - 140), (y1 - y0) / (H - 140), 0.01);
    SK.view.cx = (x0 + x1) / 2;
    SK.view.cy = (y0 + y1) / 2;
    SK.fitted = true;
  }

  /** Zoom about the screen point (px, py), by default about the centre. */
  function zoom(factor, px, py) {
    const [W, H] = canvasSize(), v = SK.view;
    px = px ?? W / 2;
    py = py ?? H / 2;
    const mx = v.cx + (px - W / 2) * v.k, my = v.cy - (py - H / 2) * v.k;
    v.k = Math.min(5, Math.max(0.005, v.k * factor));
    v.cx = mx - (px - W / 2) * v.k;
    v.cy = my + (py - H / 2) * v.k;
    render();
  }

  /** Drawing context with helpers for text and lines in screen sizes. */
  function context(svg) {
    const [W, H] = canvasSize(), v = SK.view, k = v.k;
    svg.setAttribute("viewBox", `${v.cx - (W * k) / 2} ${-(v.cy + (H * k) / 2)} ${W * k} ${H * k}`);
    const root = el("g", { transform: "scale(1,-1)" }, svg);
    const px = (a) => a * k;
    const text = (x, y, content, o = {}) => {
      let rot = o.rot || 0;
      if (rot > 90) rot -= 180;
      if (rot < -90) rot += 180;  // text never upside down
      return svgText(root, {
        transform: `translate(${x} ${y}) rotate(${rot}) scale(1 -1)`, "font-size": px(o.size || 12), fill: o.fill || "currentColor",
        "text-anchor": o.anchor || "middle", "dominant-baseline": "middle", "pointer-events": o.dim ? "all" : "none", ...(o.attrs || {}),
      }, content);
    };
    const line = (a, b, o = {}) => el("line", {
      x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: o.stroke || "currentColor", "stroke-width": px(o.w || 1),
      ...(o.dash ? { "stroke-dasharray": `${px(o.dash)} ${px(o.dash)}` } : {}), "pointer-events": "none", ...(o.attrs || {}),
    }, root);
    const dimText = (x, y, content, status, attrs, rot = 0) => text(x, y, content, { size: 12, fill: statusColor(status), rot, dim: true, attrs });
    const bounds = { x0: v.cx - (W * k) / 2, x1: v.cx + (W * k) / 2, y0: v.cy - (H * k) / 2, y1: v.cy + (H * k) / 2 };
    const bad = SK.res && (SK.res.state === "conflict" || !SK.res.ok);
    const outlineColor = bad ? SK_COLORS.conflict : SK.res && SK.res.state === "full" ? SK_COLORS.full : SK_COLORS.ok;
    return { root, k, px, text, line, dimText, bounds, outlineColor };
  }

  function render() {
    const svg = $("#skCanvas");
    if (!svg) return;
    svg.innerHTML = "";
    const ctx = context(svg);
    drawGrid(ctx);
    drawRotationPreview(ctx);
    drawGear(ctx);
    drawHousing(ctx);
    drawRod(ctx);
    const showMeasures = $("#skShowMeasures").checked;
    drawSideDimensions(ctx, showMeasures);
    drawAngles(ctx, showMeasures);
    drawReferenceDistances(ctx);
    drawPoints(ctx);
    drawDrawingTool(ctx);
  }

  function drawGrid({ k, px, text, line, bounds: { x0, x1, y0, y1 } }) {
    let step = 1;
    while (step / k < MIN_GRID_PX) step *= step < 5 ? 5 : 2;
    for (let x = Math.ceil(x0 / step) * step; x <= x1; x += step) line([x, y0], [x, y1], { stroke: SK_COLORS.grid, w: 0.5 });
    for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) line([x0, y], [x1, y], { stroke: SK_COLORS.grid, w: 0.5 });
    line([x0, 0], [x1, 0], { stroke: SK_COLORS.axis, w: 0.8, dash: 6 });
    line([0, y0], [0, y1], { stroke: SK_COLORS.axis, w: 0.8, dash: 6 });
    text(x1 - px(8), px(10), "x", { size: 11, fill: "#888", anchor: "end" });
    text(px(10), y1 - px(10), "y", { size: 11, fill: "#888", anchor: "start" });
  }

  const pointsAttr = (points) => points.map((p) => p.join(",")).join(" ");

  /** Sweep envelope (circle around the rod) and rotated preview of the motor. */
  function drawRotationPreview({ root, px, text }) {
    const poly = SK.sk.points, gear = Sketch.gearBox();
    const R = Math.max(...poly.map((p) => Math.hypot(p[0], p[1])), ...gear.map((p) => Math.hypot(p[0], p[1])));
    if ($("#skSweep").checked) el("circle", { cx: 0, cy: 0, r: R, fill: "none", stroke: "#8a6", "stroke-width": px(1), "stroke-dasharray": `${px(5)} ${px(4)}`, "pointer-events": "none" }, root);
    if (!SK.rot) return;
    const group = el("g", { transform: `rotate(${SK.rot})`, opacity: 0.45, "pointer-events": "none" }, root);
    el("polygon", { points: pointsAttr(poly), fill: "#c8a", stroke: SK_COLORS.rotation, "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}` }, group);
    el("polygon", { points: pointsAttr(gear), fill: "#f9c27a", stroke: SK_COLORS.gearDark, "stroke-width": px(1) }, group);
    const a = (SK.rot * Math.PI) / 180, ar = Math.min(R * 0.5, px(70));
    el("path", { d: `M ${ar} 0 A ${ar} ${ar} 0 ${SK.rot > 180 ? 1 : 0} 1 ${ar * Math.cos(a)} ${ar * Math.sin(a)}`, fill: "none", stroke: SK_COLORS.rotation, "stroke-width": px(1.5) }, root);
    text(ar * 1.2 * Math.cos(a / 2), ar * 1.2 * Math.sin(a / 2), `${SK.rot}°`, { size: 12, fill: SK_COLORS.rotation });
  }

  function drawGear({ root, px, text, line }) {
    const m = cfg.motor, cd = m.center_distance;
    el("polygon", { id: "skGear", points: pointsAttr(Sketch.gearBox()), fill: SK_COLORS.gear, "fill-opacity": 0.8, stroke: "#333", "stroke-width": px(1), "pointer-events": "none" }, root);
    line([-cd, -m.gear_width / 2 - px(14)], [-cd, m.gear_width / 2 + px(14)], { stroke: SK_COLORS.gearDark, w: 1, dash: 4 });
    const handle = el("circle", { id: "skGearHandle", cx: -cd, cy: 0, r: px(5), fill: SK_COLORS.gear, stroke: "#fff", "stroke-width": px(1.5), class: "handle", "data-sk-gear": "1" }, root);
    el("title", {}, handle).textContent = t("ui.sk.gear_handle");
    text(-cd, m.gear_width / 2 + px(22), t("ui.sk.gear"), { size: 11, fill: SK_COLORS.gearDark });
  }

  /** Outline and invisibly wide sides for clicking. */
  function drawHousing({ root, px, line, outlineColor }) {
    el("polygon", { id: "skPoly", points: pointsAttr(SK.sk.points), fill: outlineColor, "fill-opacity": 0.16, stroke: outlineColor, "stroke-width": px(2), "pointer-events": "none" }, root);
    for (let i = 0; i < skCount(); i++) {
      const a = Sketch.point(i), b = Sketch.point(i + 1);
      const hovered = SK.hover && SK.hover.sides && SK.hover.sides.includes(i);
      if (SK.sel.s.has(i) || hovered) line(a, b, { stroke: SK_COLORS.sel, w: 4.5 });
      el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "transparent", "stroke-width": px(12), "data-sk-side": i, class: "skside" }, root);
    }
  }

  function drawRod({ root, px, text, line }) {
    const rodR = cfg.rod.diameter / 2, m = cfg.motor;
    const tooClose = Sketch.housingClearance() < m.own_clearance - SK_EPS;
    el("circle", { cx: 0, cy: 0, r: rodR + cfg.rod.hole_clearance, fill: "none", stroke: "currentColor", "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}`, "pointer-events": "none" }, root);
    el("circle", { cx: 0, cy: 0, r: rodR + m.own_clearance, fill: "none", stroke: tooClose ? SK_COLORS.conflict : SK_COLORS.redundant, "stroke-width": px(tooClose ? 2 : 1), "stroke-dasharray": `${px(3)} ${px(3)}`, "pointer-events": "none" }, root);
    el("circle", { id: "skRod", cx: 0, cy: 0, r: rodR, fill: "#222", "pointer-events": "none", "data-rod": "1" }, root);
    line([-rodR * 2.2, 0], [rodR * 2.2, 0], { stroke: "#fff", w: 1 });
    line([0, -rodR * 2.2], [0, rodR * 2.2], { stroke: "#fff", w: 1 });
    text(rodR + px(10), -rodR - px(10), t("ui.sk.rod", { d: fmtLen(cfg.rod.diameter) }), { size: 12, anchor: "start" });
  }

  /** Length dimensions (as a dimension with a constraint, otherwise grey) and relation symbols per side. */
  function drawSideDimensions(ctx, showMeasures) {
    const { root, px, text, line, dimText } = ctx;
    const constraints = SK.sk.constraints;
    for (let i = 0; i < skCount(); i++) {
      const a = Sketch.point(i), b = Sketch.point(i + 1), d = Sketch.sideVec(i), L = Math.hypot(...d) || 1;
      const nx = d[1] / L, ny = -d[0] / L;  // outer normal (outline counter clockwise)
      const angle = (Math.atan2(d[1], d[0]) * 180) / Math.PI;
      const mid = Sketch.sideMid(i), off = px(18);
      const ci = constraints.findIndex((c) => c.type === "length" && c.a === i);
      if (ci >= 0) {
        const status = constraintStatus(ci), color = statusColor(status);
        const A = [a[0] + nx * off, a[1] + ny * off], B = [b[0] + nx * off, b[1] + ny * off];
        line(a, [a[0] + nx * off * 1.3, a[1] + ny * off * 1.3], { stroke: color, w: 0.8 });
        line(b, [b[0] + nx * off * 1.3, b[1] + ny * off * 1.3], { stroke: color, w: 0.8 });
        line(A, B, { stroke: color, w: 1 });
        for (const [Q, dir] of [[A, 1], [B, -1]]) drawArrow(root, px, Q, [(d[0] / L) * dir, (d[1] / L) * dir], [nx, ny], color);
        const shown = SK.res && SK.res.measures ? SK.res.measures.sides[i] : L;
        dimText(mid[0] + nx * (off + px(10)), mid[1] + ny * (off + px(10)), fmtLen(shown), status, { "data-sk-dim": `length:${i}` }, angle);
      } else if (showMeasures) {
        text(mid[0] + nx * px(12), mid[1] + ny * px(12), fmtLen(L), { size: 10.5, fill: "#888", rot: angle, dim: true, attrs: { "data-sk-dim": `length:${i}`, class: "skmeasure" } });
      }
      const related = (type) => constraints.some((c) => c.enabled && c.type === type && (c.a === i || c.b === i));
      const glyphs = SIDE_GLYPHS.filter(([type]) => related(type)).map(([, g]) => g).join("");
      if (glyphs) text(mid[0] - nx * px(12), mid[1] - ny * px(12), glyphs, { size: 14, fill: SK_COLORS.ok, rot: angle });
    }
  }

  function drawArrow(root, px, tip, along, normal, color) {
    const [ux, uy] = along, [nx, ny] = normal;
    const p1 = [tip[0] + ux * px(9) + nx * px(3), tip[1] + uy * px(9) + ny * px(3)];
    const p2 = [tip[0] + ux * px(9) - nx * px(3), tip[1] + uy * px(9) - ny * px(3)];
    el("polygon", { points: pointsAttr([tip, p1, p2]), fill: color, "pointer-events": "none" }, root);
  }

  /** Interior angle as an arc. Coloured and editable with a constraint, otherwise grey. */
  function drawAngles({ root, px, text, dimText }, showMeasures) {
    for (let i = 0; i < skCount(); i++) {
      const ci = SK.sk.constraints.findIndex((c) => c.type === "angle" && c.a === i);
      if (ci < 0 && !showMeasures) continue;
      const q = Sketch.point(i), next = Sketch.point(i + 1), angle = Sketch.interiorAngle(i);
      const status = ci >= 0 ? constraintStatus(ci) : "ok";
      const color = ci < 0 ? "#999" : statusColor(status);
      const rr = px(ci >= 0 ? 26 : 20);
      // Arc from the direction to the next point counter clockwise to the previous point
      const start = Math.atan2(next[1] - q[1], next[0] - q[0]), end = start + (angle * Math.PI) / 180;
      el("path", { d: `M ${q[0] + rr * Math.cos(start)} ${q[1] + rr * Math.sin(start)} A ${rr} ${rr} 0 ${angle > 180 ? 1 : 0} 1 ${q[0] + rr * Math.cos(end)} ${q[1] + rr * Math.sin(end)}`, fill: "none", stroke: color, "stroke-width": px(ci >= 0 ? 1.4 : 0.8), "pointer-events": "none" }, root);
      const mid = start + (angle * Math.PI) / 360;
      const tx = q[0] + (rr + px(14)) * Math.cos(mid), ty = q[1] + (rr + px(14)) * Math.sin(mid);
      if (ci >= 0) dimText(tx, ty, `${fmtDeg(angle)}°`, status, { "data-sk-dim": `angle:${i}` });
      else text(tx, ty, `${fmtDeg(angle)}°`, { size: 10, fill: "#999", dim: true, attrs: { "data-sk-dim": `angle:${i}`, class: "skmeasure" } });
    }
  }

  /** Distance dimensions to the rod or the gear and coordinate dimensions. */
  function drawReferenceDistances({ px, line, dimText }) {
    SK.sk.constraints.forEach((c, ci) => {
      if (!c.enabled) return;
      const status = constraintStatus(ci), color = statusColor(status), attrs = { "data-sk-dim": `cons:${ci}` };
      if (c.type === "dist_point") {
        const q = Sketch.point(c.a), r = Sketch.refPos(c.ref);
        line(r, q, { stroke: color, w: 1, dash: 5 });
        dimText((q[0] + r[0]) / 2, (q[1] + r[1]) / 2 + px(10), fmtLen(Math.hypot(q[0] - r[0], q[1] - r[1])), status, attrs);
      } else if (c.type === "dist_side") {
        const a = Sketch.point(c.a), d = Sketch.sideVec(c.a), L = Math.hypot(...d) || 1, r = Sketch.refPos(c.ref);
        const t = ((r[0] - a[0]) * d[0] + (r[1] - a[1]) * d[1]) / (L * L), foot = [a[0] + t * d[0], a[1] + t * d[1]];
        line(r, foot, { stroke: color, w: 1, dash: 5 });
        dimText((r[0] + foot[0]) / 2, (r[1] + foot[1]) / 2 + px(10), fmtLen(Math.hypot(foot[0] - r[0], foot[1] - r[1])), status, attrs);
      } else if (c.type === "coord_x" || c.type === "coord_y") {
        const q = Sketch.point(c.a);
        dimText(q[0] + px(12), q[1] - px(14), (c.type === "coord_x" ? "x " : "y ") + fmtLen(c.value), status, attrs);
      }
    });
  }

  function drawPoints({ root, px, text, outlineColor }) {
    for (let i = 0; i < skCount(); i++) {
      const q = Sketch.point(i);
      const highlighted = SK.sel.p.has(i) || (SK.hover && SK.hover.points && SK.hover.points.includes(i));
      el("circle", { cx: q[0], cy: q[1], r: px(highlighted ? 7 : 5.5), fill: highlighted ? SK_COLORS.sel : "#fff", stroke: outlineColor, "stroke-width": px(2), class: "handle", "data-sk-point": i }, root);
      if (SK.sk.constraints.some((c) => c.enabled && c.type === "fix" && c.a === i)) drawLock(root, px, q);
      text(q[0] - px(11), q[1] + px(11), `P${i + 1}`, { size: 10.5, fill: "#666" });
    }
  }

  /** Lock symbol for fixed points. */
  function drawLock(root, px, q) {
    el("rect", { x: q[0] + px(7), y: q[1] + px(5), width: px(8), height: px(6), fill: SK_COLORS.ok, "pointer-events": "none" }, root);
    el("path", { d: `M ${q[0] + px(9)} ${q[1] + px(11)} v ${px(3)} a ${px(2)} ${px(2)} 0 0 1 ${px(4)} 0 v ${-px(3)}`, fill: "none", stroke: SK_COLORS.ok, "stroke-width": px(1.3), "pointer-events": "none" }, root);
  }

  function drawDrawingTool({ root, px }) {
    if (SK.tool !== "draw") return;
    const points = SK.drawPts.concat(SK.cursor ? [SK.cursor] : []);
    if (points.length > 1) el("polyline", { points: pointsAttr(points), fill: "none", stroke: "#e00", "stroke-width": px(1.5), "stroke-dasharray": `${px(5)} ${px(3)}`, "pointer-events": "none" }, root);
    SK.drawPts.forEach((p) => el("circle", { cx: p[0], cy: p[1], r: px(4.5), fill: "#e00", "pointer-events": "none" }, root));
  }

  Object.assign(Sketch, { canvasSize, fit, zoom, render });
})();
