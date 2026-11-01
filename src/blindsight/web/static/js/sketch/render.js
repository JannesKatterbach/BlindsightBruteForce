"use strict";
// Motor sketch. Canvas. Grid, rod, housing hull, gear, entities, points, relation symbols, dimensions and
// the preview of the active tool. Drawing happens in mm in the rod frame (y up). px() converts screen pixels.

(() => {
  const MIN_GRID_PX = 22;  // smallest distance of the grid lines on the screen
  const GLYPHS = { coincident: "◆", horizontal: "H", vertical: "V", parallel: "∥", perpendicular: "⊥", equal: "=", midpoint: "M", concentric: "◎", fix: "⚓" };
  const DIMENSIONS = new Set(["distance", "hdistance", "vdistance", "length", "angle", "diameter", "radius"]);

  function canvasSize() {
    const canvas = $("#skCanvas");
    return [Math.max(200, canvas.clientWidth), Math.max(200, canvas.clientHeight)];
  }

  /** View so that all geometry, the gear and the rod are visible. */
  function fit() {
    const b = Sketch.bounds(), d = cfg.rod.diameter;
    const x0 = Math.min(b.x0, -d), x1 = Math.max(b.x1, d), y0 = Math.min(b.y0, -d), y1 = Math.max(b.y1, d);
    const [W, H] = canvasSize();
    SK.view.k = Math.max((x1 - x0) / (W - 160), (y1 - y0) / (H - 160), 0.01);
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
    const text = (x, y, content, o = {}) => svgText(o.parent || root, {
      transform: `translate(${x} ${y}) scale(1 -1)`, "font-size": px(o.size || 12), fill: o.fill || "currentColor",
      "text-anchor": o.anchor || "middle", "dominant-baseline": "middle", "pointer-events": o.events ? "all" : "none", ...(o.attrs || {}),
    }, content);
    const line = (a, b, o = {}) => el("line", {
      x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: o.stroke || "currentColor", "stroke-width": px(o.w || 1),
      ...(o.dash ? { "stroke-dasharray": `${px(o.dash)} ${px(o.dash)}` } : {}), "pointer-events": "none", ...(o.attrs || {}),
    }, o.parent || root);
    const bounds = { x0: v.cx - (W * k) / 2, x1: v.cx + (W * k) / 2, y0: v.cy - (H * k) / 2, y1: v.cy + (H * k) / 2 };
    return { root, k, px, text, line, bounds };
  }

  // --- Colours ----------------------------------------------------------------------------------------------
  /** Entities that take part in a conflicting constraint. */
  function conflictRefs() {
    const out = new Set();
    SK.sk.constraints.forEach((c, k) => { if (constraintStatus(k) === "conflict") c.refs.forEach((r) => out.add(r)); });
    return out;
  }

  function entityColor(k, conflicts) {
    const ref = `e${k}`;
    if (SK.sel.has(ref) || SK.pick.includes(ref)) return SK_COLORS.sel;
    if (SK.hover === ref) return SK_COLORS.hover;
    if (conflicts.has(ref)) return SK_COLORS.conflict;
    const defined = SK.res && SK.res.defined_entities && SK.res.defined_entities[k];
    return defined ? SK_COLORS.defined : SK_COLORS.free;
  }

  function render() {
    const svg = $("#skCanvas");
    if (!svg) return;
    svg.innerHTML = "";
    svg.classList.toggle("select", SK.tool === "select");
    const ctx = context(svg);
    drawGrid(ctx);
    drawHull(ctx);
    drawRotationPreview(ctx);
    drawRod(ctx);
    drawEntities(ctx);
    drawPoints(ctx);
    drawConstraints(ctx);
    drawPreview(ctx);
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

  /** Housing hull (light) and gear (orange) from the last solve. */
  function drawHull({ root, px }) {
    const prof = (SK.res && SK.res.profile) || {};
    if ($("#skShowHull").checked && prof.housing && prof.housing.length >= 3) {
      el("polygon", { id: "skHull", points: pointsAttr(prof.housing), fill: SK_COLORS.hull, "fill-opacity": 0.13, stroke: SK_COLORS.hull, "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}`, "pointer-events": "none" }, root);
    }
    if (prof.gear) {
      const g = prof.gear;
      el("rect", { id: "skGear", x: g.xmin, y: g.ymin, width: g.diameter, height: g.width, fill: SK_COLORS.gear, "fill-opacity": 0.35, "pointer-events": "none" }, root);
    }
  }

  /** Sweep envelope (circle around the rod) and rotated preview of the motor. */
  function drawRotationPreview({ root, px, text }) {
    const prof = (SK.res && SK.res.profile) || {};
    const pts = (prof.housing || []).concat(prof.gear ? [[prof.gear.xmin, prof.gear.ymin], [prof.gear.xmax, prof.gear.ymax], [prof.gear.xmin, prof.gear.ymax], [prof.gear.xmax, prof.gear.ymin]] : []);
    if (!pts.length) return;
    const R = Math.max(...pts.map((p) => Math.hypot(p[0], p[1])));
    if ($("#skSweep").checked) el("circle", { cx: 0, cy: 0, r: R, fill: "none", stroke: "#8a6", "stroke-width": px(1), "stroke-dasharray": `${px(5)} ${px(4)}`, "pointer-events": "none" }, root);
    if (!SK.rot) return;
    const group = el("g", { transform: `rotate(${SK.rot})`, opacity: 0.45, "pointer-events": "none" }, root);
    if (prof.housing) el("polygon", { points: pointsAttr(prof.housing), fill: "#c8a", stroke: SK_COLORS.rotation, "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}` }, group);
    if (prof.gear) el("rect", { x: prof.gear.xmin, y: prof.gear.ymin, width: prof.gear.diameter, height: prof.gear.width, fill: "#f9c27a" }, group);
    const a = (SK.rot * Math.PI) / 180, ar = Math.min(R * 0.5, px(70));
    el("path", { d: `M ${ar} 0 A ${ar} ${ar} 0 ${SK.rot > 180 ? 1 : 0} 1 ${ar * Math.cos(a)} ${ar * Math.sin(a)}`, fill: "none", stroke: SK_COLORS.rotation, "stroke-width": px(1.5) }, root);
    text(ar * 1.2 * Math.cos(a / 2), ar * 1.2 * Math.sin(a / 2), `${SK.rot}°`, { size: 12, fill: SK_COLORS.rotation });
  }

  /** Rod at the origin with its hole and the own clearance of the housing. The origin can be selected. */
  function drawRod({ root, px, text }) {
    const rodR = cfg.rod.diameter / 2, m = cfg.motor;
    el("circle", { cx: 0, cy: 0, r: rodR + cfg.rod.hole_clearance, fill: "none", stroke: "currentColor", "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}`, "pointer-events": "none" }, root);
    el("circle", { cx: 0, cy: 0, r: rodR + m.own_clearance, fill: "none", stroke: SK_COLORS.redundant, "stroke-width": px(1), "stroke-dasharray": `${px(3)} ${px(3)}`, "pointer-events": "none" }, root);
    el("circle", { id: "skRod", cx: 0, cy: 0, r: rodR, fill: SK_COLORS.rod, "fill-opacity": 0.85, "pointer-events": "none" }, root);
    const origin = SK.sel.has("o") || SK.pick.includes("o") ? SK_COLORS.sel : SK.hover === "o" ? SK_COLORS.hover : "#fff";
    el("circle", { cx: 0, cy: 0, r: px(4), fill: origin, stroke: "#222", "stroke-width": px(1.2), "data-sk-ref": "o", "pointer-events": "none" }, root);
    text(rodR + px(10), -rodR - px(10), t("ui.sk.rod", { d: fmtLen(cfg.rod.diameter) }), { size: 11, anchor: "start", fill: "#888" });
  }

  function drawEntities({ root, px }) {
    const conflicts = conflictRefs();
    SK.sk.entities.forEach((e, k) => {
      if (e.type === "point") return;
      const color = entityColor(k, conflicts);
      const gear = e.role === "gear";
      const style = {
        stroke: gear && color === SK_COLORS.defined ? SK_COLORS.gearDark : color, "stroke-width": px(e.construction ? 1.2 : 2), fill: "none",
        "data-sk-ref": `e${k}`, "pointer-events": "none", class: e.construction ? "construction" : "",
        ...(e.construction ? { "stroke-dasharray": `${px(6)} ${px(4)}` } : {}),
      };
      if (e.type === "line") {
        const [a, b] = Sketch.ends(k);
        el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], ...style }, root);
      } else if (e.type === "circle") {
        const { c, r } = Sketch.curve(k);
        el("circle", { cx: c[0], cy: c[1], r, ...style }, root);
      } else if (e.type === "arc") {
        const { c, r } = Sketch.curve(k), { a0, sweep } = Sketch.arcAngles(k);
        const s = [c[0] + r * Math.cos(a0), c[1] + r * Math.sin(a0)], t = [c[0] + r * Math.cos(a0 + sweep), c[1] + r * Math.sin(a0 + sweep)];
        el("path", { d: `M ${s[0]} ${s[1]} A ${r} ${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${t[0]} ${t[1]}`, ...style }, root);
      }
    });
  }

  /** End points, centres and sketch points. Coloured like their entity, selected points orange. */
  function drawPoints({ root, px }) {
    const conflicts = conflictRefs();
    SK.sk.entities.forEach((e, k) => {
      const base = entityColor(k, conflicts);
      e.points.forEach((p, j) => {
        const ref = e.type === "point" ? `e${k}` : `p${p}`;
        const q = SK.sk.points[p];
        const selected = SK.sel.has(ref) || SK.pick.includes(ref);
        const defined = SK.res && SK.res.defined_points && SK.res.defined_points[p];
        const color = selected ? SK_COLORS.sel : SK.hover === ref ? SK_COLORS.hover : base === SK_COLORS.sel ? (defined ? SK_COLORS.defined : SK_COLORS.free) : base;
        const r = px(e.type === "point" ? 4.5 : selected || SK.hover === ref ? 4.5 : 3);
        const centre = e.type !== "line" && e.type !== "point" && j === 0;
        el(centre ? "rect" : "circle", centre
          ? { x: q[0] - r, y: q[1] - r, width: 2 * r, height: 2 * r, fill: "#fff", stroke: color, "stroke-width": px(1.4), "data-sk-ref": ref, "pointer-events": "none" }
          : { cx: q[0], cy: q[1], r, fill: selected || e.type === "point" ? color : "#fff", stroke: color, "stroke-width": px(1.4), "data-sk-ref": ref, "pointer-events": "none" }, root);
      });
    });
  }

  // --- Relations and dimensions -------------------------------------------------------------------------------
  /** Where a relation symbol of an entity or point is drawn (several symbols of one anchor are stacked). */
  function anchorOf(ref, ctx) {
    if (Sketch.isPointRef(ref)) { const p = Sketch.point(ref); return { at: p, dir: [1, 0] }; }
    const k = Sketch.entityIndex(ref), e = SK.sk.entities[k];
    if (e.type === "line") {
      const [a, b] = Sketch.ends(k), d = [b[0] - a[0], b[1] - a[1]], n = Math.hypot(...d) || 1;
      return { at: Sketch.midpoint(a, b), dir: [d[0] / n, d[1] / n], normal: [-d[1] / n, d[0] / n] };
    }
    const { c, r } = Sketch.curve(k);
    return { at: [c[0] + r * Math.SQRT1_2, c[1] + r * Math.SQRT1_2], dir: [1, 0] };
  }

  function drawConstraints(ctx) {
    const stacks = new Map();
    SK.sk.constraints.forEach((c, k) => {
      if (DIMENSIONS.has(c.type)) drawDimension(ctx, c, k);
      else drawRelation(ctx, c, k, stacks);
    });
  }

  function constraintColor(k) {
    const ref = `c${k}`;
    if (SK.sel.has(ref)) return SK_COLORS.sel;
    if (SK.hover === ref) return SK_COLORS.hover;
    const status = constraintStatus(k);
    if (status === "disabled") return "#999";
    return status === "ok" ? SK_COLORS.dimension : statusColor(status);
  }

  /** Symbols that would only clutter the drawing are left out (they stay in the list and show when selected). */
  function hiddenRelation(c, k) {
    if (SK.sel.has(`c${k}`) || SK.hover === `c${k}`) return false;
    if (c.type === "coincident" && c.refs.every((r) => Sketch.isPointRef(r)) && !c.refs.includes("o")) return true;  // corners
    const gearRef = (r) => {
      if (r === "o") return true;
      if (r[0] === "e") return SK.sk.entities[+r.slice(1)].role === "gear";
      const owner = Sketch.ownerOf(+r.slice(1));
      return owner >= 0 && SK.sk.entities[owner].role === "gear";
    };
    return c.refs.every(gearRef);  // the inner relations of the gear
  }

  function drawRelation({ root, px, text }, c, k, stacks) {
    const glyph = GLYPHS[c.type];
    if (!glyph || hiddenRelation(c, k)) return;
    // Relations to the origin or between two points are drawn at the first non origin reference
    const refs = c.refs.filter((r) => r !== "o");
    const anchorRef = refs.find((r) => !Sketch.isPointRef(r)) || refs[0] || "o";
    const anchor = anchorOf(anchorRef);
    const n = stacks.get(anchorRef) || 0;
    stacks.set(anchorRef, n + 1);
    const normal = anchor.normal || [0.7, 0.7];
    const off = px(14), along = px(14) * n;
    const x = anchor.at[0] + normal[0] * off + anchor.dir[0] * along, y = anchor.at[1] + normal[1] * off + anchor.dir[1] * along;
    const color = constraintColor(k);
    const g = el("g", { "data-sk-ref": `c${k}`, class: "skglyph" }, root);
    el("rect", { x: x - px(7), y: y - px(7), width: px(14), height: px(14), rx: px(3), fill: "#fff", stroke: color, "stroke-width": px(1) }, g);
    text(x, y, glyph, { size: 10, fill: color, parent: g, events: true });
  }

  function arrow(parent, px, tip, dir, color) {
    const n = Math.hypot(...dir) || 1, u = [dir[0] / n, dir[1] / n], q = [-u[1], u[0]];
    const p1 = [tip[0] - u[0] * px(8) + q[0] * px(3), tip[1] - u[1] * px(8) + q[1] * px(3)];
    const p2 = [tip[0] - u[0] * px(8) - q[0] * px(3), tip[1] - u[1] * px(8) - q[1] * px(3)];
    el("polygon", { points: pointsAttr([tip, p1, p2]), fill: color, "pointer-events": "none" }, parent);
  }

  /** Dimension line between a and b (extension lines from the measured points), text at label. */
  function linearDimension(ctx, g, a, b, label, color, from, to) {
    const { px, line } = ctx;
    line(from || a, a, { stroke: color, w: 0.8, parent: g });
    line(to || b, b, { stroke: color, w: 0.8, parent: g });
    line(a, b, { stroke: color, w: 1, parent: g });
    arrow(g, px, a, [a[0] - b[0], a[1] - b[1]], color);
    arrow(g, px, b, [b[0] - a[0], b[1] - a[1]], color);
    if (label) line(Sketch.midpoint(a, b), label, { stroke: color, w: 0.6, dash: 2, parent: g });
  }

  /** Default position of the dimension text. */
  function defaultLabel(c) {
    const r = c.refs, px = SK.view.k;
    if (c.type === "length") { const a = anchorOf(r[0]); return [a.at[0] - a.normal[0] * px * 24, a.at[1] - a.normal[1] * px * 24]; }
    if (c.type === "diameter" || c.type === "radius") { const { c: m, r: rad } = Sketch.curve(Sketch.entityIndex(r[0])); return [m[0] + rad * 1.2, m[1] + rad * 0.6]; }
    if (c.type === "angle") { const p = Sketch.lineIntersection(r[0], r[1]); return [p[0] + px * 30, p[1] + px * 30]; }
    const pts = r.map((ref) => (Sketch.isPointRef(ref) ? Sketch.point(ref) : anchorOf(ref).at));
    const m = Sketch.midpoint(pts[0], pts[1]);
    if (c.type === "hdistance") return [m[0], Math.min(pts[0][1], pts[1][1]) - px * 24];
    if (c.type === "vdistance") return [Math.max(pts[0][0], pts[1][0]) + px * 24, m[1]];
    return [m[0] + px * 16, m[1] + px * 16];
  }

  function dimensionText(c) {
    if (c.type === "angle") return `${fmtDeg(c.value)}°`;
    if (c.type === "diameter") return `⌀${fmtLen(c.value)}`;
    if (c.type === "radius") return `R${fmtLen(c.value)}`;
    return fmtLen(c.value);
  }

  /** Draw a dimension (also used for the preview while placing one, then k is null). */
  function drawDimension(ctx, c, k, preview = false) {
    const { root, px, text } = ctx;
    const color = preview ? SK_COLORS.snap : k === null ? SK_COLORS.free : constraintColor(k);
    const label = c.label || defaultLabel(c);
    const g = el("g", k === null ? { opacity: 0.8 } : { "data-sk-ref": `c${k}`, class: "skdim" }, root);
    drawDimensionGeometry(ctx, g, c, label, color);
    const content = preview ? (c.type === "angle" ? `${fmtDeg(c.value)}°` : dimensionText(c)) : dimensionText(c);
    const box = text(label[0], label[1], content, { size: 12, fill: color, parent: g, events: true, attrs: k === null ? {} : { "data-sk-dim": k } });
    box.setAttribute("font-weight", "600");
    // A halo in the background colour keeps the number readable on top of lines
    box.setAttribute("stroke", "var(--card)");
    box.setAttribute("stroke-width", px(4));
    box.setAttribute("paint-order", "stroke");
  }

  function drawDimensionGeometry(ctx, g, c, label, color) {
    const r = c.refs;
    if (c.type === "diameter" || c.type === "radius") { drawRadialDimension(ctx, g, c, label, color); return; }
    if (c.type === "angle") { drawAngleArc(ctx, g, r, label, color); return; }
    if (c.type === "length") { offsetDimension(ctx, g, ...Sketch.ends(Sketch.entityIndex(r[0])), label, color); return; }
    const kinds = r.map(Sketch.kindOf);
    if (kinds[0] === "point" && kinds[1] === "point") {
      const a = Sketch.point(r[0]), b = Sketch.point(r[1]);
      if (c.type === "hdistance") linearDimension(ctx, g, [a[0], label[1]], [b[0], label[1]], null, color, a, b);
      else if (c.type === "vdistance") linearDimension(ctx, g, [label[0], a[1]], [label[0], b[1]], null, color, a, b);
      else offsetDimension(ctx, g, a, b, label, color);
      return;
    }
    // Point to line or line to line. Perpendicular from the point (or the midpoint of the second line)
    const lineRef = kinds[0] === "line" ? r[0] : r[1];
    const otherRef = lineRef === r[0] ? r[1] : r[0];
    const p = Sketch.isPointRef(otherRef) ? Sketch.point(otherRef) : Sketch.midpoint(...Sketch.ends(Sketch.entityIndex(otherRef)));
    const [a, b] = Sketch.ends(Sketch.entityIndex(lineRef)), d = [b[0] - a[0], b[1] - a[1]], l2 = d[0] * d[0] + d[1] * d[1] || 1;
    const tFoot = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / l2;
    const foot = [a[0] + tFoot * d[0], a[1] + tFoot * d[1]];
    linearDimension(ctx, g, p, foot, label, color);
  }

  /** Diameter or radius. Leader from the centre (or the opposite edge) through the circle to the label. */
  function drawRadialDimension({ px, line }, g, c, label, color) {
    const { c: m, r: rad } = Sketch.curve(Sketch.entityIndex(c.refs[0]));
    const d = [label[0] - m[0], label[1] - m[1]], n = Math.hypot(...d) || 1, u = [d[0] / n, d[1] / n];
    const edge = [m[0] + u[0] * rad, m[1] + u[1] * rad];
    const start = c.type === "diameter" ? [m[0] - u[0] * rad, m[1] - u[1] * rad] : m;
    line(start, label, { stroke: color, w: 0.8, parent: g });
    arrow(g, px, edge, u, color);
    if (c.type === "diameter") arrow(g, px, start, [-u[0], -u[1]], color);
  }

  /** Arc between two lines around their corner, through the label. */
  function drawAngleArc({ px }, g, refs, label, color) {
    const corner = Sketch.lineIntersection(refs[0], refs[1]);
    const rad = Math.max(px(12), Math.hypot(label[0] - corner[0], label[1] - corner[1]) * 0.85);
    const dirs = refs.map((ref) => {  // direction from the corner to the far end of each line
      const [a, b] = Sketch.ends(Sketch.entityIndex(ref));
      const far = Math.hypot(a[0] - corner[0], a[1] - corner[1]) > Math.hypot(b[0] - corner[0], b[1] - corner[1]) ? a : b;
      return Math.atan2(far[1] - corner[1], far[0] - corner[0]);
    });
    let sweep = dirs[1] - dirs[0];
    while (sweep > Math.PI) sweep -= 2 * Math.PI;
    while (sweep < -Math.PI) sweep += 2 * Math.PI;
    const s = [corner[0] + rad * Math.cos(dirs[0]), corner[1] + rad * Math.sin(dirs[0])];
    const e = [corner[0] + rad * Math.cos(dirs[0] + sweep), corner[1] + rad * Math.sin(dirs[0] + sweep)];
    el("path", { d: `M ${s[0]} ${s[1]} A ${rad} ${rad} 0 0 ${sweep > 0 ? 1 : 0} ${e[0]} ${e[1]}`, fill: "none", stroke: color, "stroke-width": px(1), "pointer-events": "none" }, g);
  }

  /** Aligned dimension between a and b, shifted parallel towards the label. */
  function offsetDimension(ctx, g, a, b, label, color) {
    const d = [b[0] - a[0], b[1] - a[1]], n = Math.hypot(...d) || 1, nn = [-d[1] / n, d[0] / n];
    const off = (label[0] - a[0]) * nn[0] + (label[1] - a[1]) * nn[1];
    const A = [a[0] + nn[0] * off, a[1] + nn[1] * off], B = [b[0] + nn[0] * off, b[1] + nn[1] * off];
    linearDimension(ctx, g, A, B, null, color, a, b);
  }

  // --- Preview of the active tool -----------------------------------------------------------------------------
  function drawPreview(ctx) {
    const { root, px, text } = ctx;
    const cur = SK.cursor;
    if (!cur) return;
    const snap = SK.snap;
    const style = { stroke: SK_COLORS.free, "stroke-width": px(1.5), fill: "none", "stroke-dasharray": `${px(5)} ${px(3)}`, "pointer-events": "none" };
    const pt = snap ? [snap.x, snap.y] : cur;
    const draft = SK.draft;
    if (draft && draft.clicks.length) {
      const a = [draft.clicks[0].x, draft.clicks[0].y];
      if (draft.tool === "line") {
        el("line", { x1: draft.clicks[draft.clicks.length - 1].x, y1: draft.clicks[draft.clicks.length - 1].y, x2: pt[0], y2: pt[1], ...style }, root);
        const axis = Sketch.axisInference([draft.clicks[draft.clicks.length - 1].x, draft.clicks[draft.clicks.length - 1].y], pt);
        if (axis) text(pt[0] + px(16), pt[1] + px(14), axis === "horizontal" ? "H" : "V", { size: 11, fill: SK_COLORS.snap });
      } else if (draft.tool === "rect" || draft.tool === "gear") {
        const y0 = draft.tool === "gear" ? -Math.abs(pt[1] - a[1]) / 2 : a[1], y1 = draft.tool === "gear" ? Math.abs(pt[1] - a[1]) / 2 : pt[1];
        el("rect", { x: Math.min(a[0], pt[0]), y: Math.min(y0, y1), width: Math.abs(pt[0] - a[0]), height: Math.abs(y1 - y0), ...style, ...(draft.tool === "gear" ? { stroke: SK_COLORS.gearDark } : {}) }, root);
      } else if (draft.tool === "circle" || draft.tool === "arc") {
        const r = Math.hypot(pt[0] - a[0], pt[1] - a[1]);
        if (draft.tool === "circle" || draft.clicks.length === 1) el("circle", { cx: a[0], cy: a[1], r, ...style, ...(draft.tool === "arc" ? { opacity: 0.5 } : {}) }, root);
        else {
          const s = [draft.clicks[1].x, draft.clicks[1].y], rs = Math.hypot(s[0] - a[0], s[1] - a[1]);
          const a0 = Math.atan2(s[1] - a[1], s[0] - a[0]), a1 = Math.atan2(pt[1] - a[1], pt[0] - a[0]);
          let sweep = (a1 - a0) % (2 * Math.PI); if (sweep <= 0) sweep += 2 * Math.PI;
          const e = [a[0] + rs * Math.cos(a1), a[1] + rs * Math.sin(a1)];
          el("path", { d: `M ${s[0]} ${s[1]} A ${rs} ${rs} 0 ${sweep > Math.PI ? 1 : 0} 1 ${e[0]} ${e[1]}`, ...style }, root);
        }
      }
    }
    if (SK.dimPlace) {
      const c = { ...SK.dimPlace, label: cur, value: Sketch.measure(SK.dimPlace.type, SK.dimPlace.refs) };
      drawDimension(ctx, c, null, true);
    }
    if (DRAW_TOOLS.includes(SK.tool) && snap && snap.ref) {
      el("circle", { cx: snap.x, cy: snap.y, r: px(6), fill: "none", stroke: SK_COLORS.snap, "stroke-width": px(2), "pointer-events": "none", class: "sksnap" }, root);
      text(snap.x + px(14), snap.y - px(14), snap.kind === "point" ? GLYPHS.coincident : "⊙", { size: 11, fill: SK_COLORS.snap });
    }
  }

  Object.assign(Sketch, { canvasSize, fit, zoom, render, defaultLabel, DIMENSIONS, GLYPHS });
})();
