"use strict";
// Motor Skizze. Zeichenflaeche mit Stange im Ursprung, Constraints (Laenge, Winkel, Parallel, ...) und Tabellen.
// Der Constraint Solver laeuft im Python Kern (/api/sketch/*). Dieses Skript ist nur Eingabe und Darstellung.
(() => {
  const S = {
    sk: { points: [], constraints: [] }, res: null, attached: false,
    sel: { p: new Set(), s: new Set() }, tool: null, drawPts: [], cursor: null,
    view: { cx: -4, cy: -8, k: 0.12 }, fitted: false, rot: 0, hist: [], redo: [], hover: null,
    drag: null, dirty: true, msg: "", pending: null, busy: 0, rendering: false,
  };
  window.__sk = S;
  const NS = "http://www.w3.org/2000/svg";
  const $s = (sel) => document.querySelector(sel);
  const CLR = { ok: "#2f6fed", full: "#2e9d4b", conflict: "#d32f2f", redundant: "#e08a00", sel: "#ff9800", grid: "#8884", axis: "#8888" };
  const n = () => S.sk.points.length;
  const fmt = (mm) => String(Math.round((mm / UNIT[unit]) * 1000) / 1000);
  const fmtDeg = (d) => String(Math.round(d * 100) / 100);
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const mk = (type, f = {}) => ({ type, a: null, b: null, value: null, value2: null, ref: "rod", enabled: true, name: "", ...f });
  const SIDES = { length: 1, parallel: 2, perpendicular: 2, equal: 2, horizontal: 1, vertical: 1, angle_sides: 2, dist_side: 1 };

  function svgEl(name, attrs = {}, parent) {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  // --- Geometrie Hilfen (Anzeige) ------------------------------------------------------------
  const P = (i) => S.sk.points[((i % n()) + n()) % n()];
  const sideVec = (i) => { const a = P(i), b = P(i + 1); return [b[0] - a[0], b[1] - a[1]]; };
  const sideLen = (i) => Math.hypot(...sideVec(i));
  function interiorAngle(i) {
    const q = P(i), p = P(i - 1), r = P(i + 1);
    const a = [p[0] - q[0], p[1] - q[1]], b = [r[0] - q[0], r[1] - q[1]];
    const ang = Math.atan2(b[0] * a[1] - b[1] * a[0], a[0] * b[0] + a[1] * b[1]) * 180 / Math.PI;
    return ang >= 0 ? ang : ang + 360;
  }
  function distPointPoly(px, py, poly) {
    let inside = true, best = Infinity;
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      if ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0]) < 0) inside = false;
      const dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy;
      let t = l2 ? ((px - a[0]) * dx + (py - a[1]) * dy) / l2 : 0; t = Math.max(0, Math.min(1, t));
      best = Math.min(best, Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy)));
    }
    return inside ? 0 : best;
  }
  const refPos = (ref) => (ref === "gear" ? [-cfg.motor.center_distance, 0] : [0, 0]);
  const gearBox = () => { const m = cfg.motor, r = m.gear_diameter / 2, h = m.gear_width / 2, cd = m.center_distance; return [[-cd - r, -h], [-cd + r, -h], [-cd + r, h], [-cd - r, h]]; };
  const statusOf = (k) => (S.res && S.res.constraints[k] ? S.res.constraints[k].status : "ok");

  // --- Solver Aufrufe -------------------------------------------------------------------------
  const gearArg = () => [cfg.motor.gear_diameter, cfg.motor.gear_width];
  async function callSolve(extra = {}) {
    const { data } = await api("/api/sketch/solve", { sketch: S.sk, cd: cfg.motor.center_distance, gear: gearArg(), ...extra });
    return data;
  }
  function apply(data) {
    if (data.sketch && data.sketch.points && data.sketch.points.length >= 3) S.sk = { points: data.sketch.points, constraints: data.sketch.constraints };
    S.res = data;
    const m = S.sel; // Auswahl bereinigen
    m.p = new Set([...m.p].filter((i) => i < n())); m.s = new Set([...m.s].filter((i) => i < n()));
  }
  function snapshot() { S.hist.push(JSON.stringify(S.sk)); if (S.hist.length > 100) S.hist.shift(); S.redo = []; }
  async function _commit(mutator, opts = {}) {
    const before = JSON.stringify(S.sk);
    const candidate = clone(S.sk);
    mutator(candidate);
    const data = await (async () => { const { data } = await api("/api/sketch/solve", { sketch: candidate, cd: cfg.motor.center_distance, gear: gearArg() }); return data; })();
    if (data.state === "invalid" && data.errors && data.errors.length && !(data.sketch && data.sketch.points && data.sketch.points.length >= 3 && opts.allowInvalid)) {
      S.msg = data.errors.join(" "); renderAll(); return false;
    }
    S.hist.push(before); if (S.hist.length > 100) S.hist.shift(); S.redo = [];
    apply(data); S.msg = ""; sync(); renderAll();
    return true;
  }
  let syncTimer = null;
  function sync() {
    if (!S.res || S.res.state === "invalid" || n() < 3) return;
    cfg.motor.outline = null;
    cfg.motor.sketch = clone(S.sk);
    const b = S.res.bbox;
    if (b) { cfg.motor.width = Math.max(0.01, b.xmax - b.xmin); cfg.motor.depth = Math.max(0.01, b.ymax - b.ymin); }
    S.attached = true;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => { writeInputs(); drawMotor(); refresh(); }, 120);
  }

  // --- Laden ---------------------------------------------------------------------------------------
  async function reload() {
    const tab = $s("#tab-sketch");
    if (!tab || !tab.classList.contains("active")) { S.dirty = true; return; }
    S.dirty = false;
    if (cfg.motor.sketch && cfg.motor.sketch.points && cfg.motor.sketch.points.length >= 3) {
      S.sk = { points: clone(cfg.motor.sketch.points), constraints: clone(cfg.motor.sketch.constraints || []).map((c) => ({ ...mk(c.type), ...c })) };
      S.attached = true;
      apply(await callSolve());
    } else {
      const { data } = await api("/api/sketch/from-motor", { motor: cfg.motor });
      if (data && data.sketch) { S.sk = data.sketch; S.attached = false; S.res = data; }
    }
    S.hist = []; S.redo = []; S.sel = { p: new Set(), s: new Set() }; S.tool = null; S.drawPts = [];
    if (!S.fitted) fit();
    renderAll();
  }

  // --- Ansicht ---------------------------------------------------------------------------------------
  function canvasSize() { const c = $s("#skCanvas"); return [Math.max(200, c.clientWidth), Math.max(200, c.clientHeight)]; }
  function fit() {
    const pts = S.sk.points.concat(gearBox(), [[cfg.rod.diameter, cfg.rod.diameter], [-cfg.rod.diameter, -cfg.rod.diameter]]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const [W, H] = canvasSize();
    S.view.k = Math.max((x1 - x0) / (W - 140), (y1 - y0) / (H - 140), 0.01);
    S.view.cx = (x0 + x1) / 2; S.view.cy = (y0 + y1) / 2; S.fitted = true;
  }
  function zoom(factor, px, py) {
    const [W, H] = canvasSize(), v = S.view;
    px = px ?? W / 2; py = py ?? H / 2;
    const mx = v.cx + (px - W / 2) * v.k, my = v.cy - (py - H / 2) * v.k;
    v.k = Math.min(5, Math.max(0.005, v.k * factor));
    v.cx = mx - (px - W / 2) * v.k; v.cy = my + (py - H / 2) * v.k;
    render();
  }
  const snapV = (v) => { const g = parseFloat($s("#skSnap").value); return g > 0 ? Math.round(v / g) * g : v; };
  const ptr = (ev) => { const [x, y] = svgPoint($s("#skCanvas"), ev); return [x, y]; };

  // --- Rendering ---------------------------------------------------------------------------------------
  function render() {
    const svg = $s("#skCanvas"); if (!svg) return;
    svg.innerHTML = "";
    const [W, H] = canvasSize(), v = S.view, k = v.k;
    svg.setAttribute("viewBox", `${v.cx - (W * k) / 2} ${-(v.cy + (H * k) / 2)} ${W * k} ${H * k}`);
    const root = svgEl("g", { transform: "scale(1,-1)" }, svg);
    const px = (a) => a * k;
    const text = (x, y, str, o = {}) => {
      let rot = o.rot || 0; if (rot > 90) rot -= 180; if (rot < -90) rot += 180;
      const t = svgEl("text", { transform: `translate(${x} ${y}) rotate(${rot}) scale(1 -1)`, "font-size": px(o.size || 12), fill: o.fill || "currentColor", "text-anchor": o.anchor || "middle", "dominant-baseline": "middle", "pointer-events": o.dim ? "all" : "none", ...(o.attrs || {}) }, root);
      t.textContent = str; return t;
    };
    const line = (a, b, o = {}) => svgEl("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: o.stroke || "currentColor", "stroke-width": px(o.w || 1), ...(o.dash ? { "stroke-dasharray": `${px(o.dash)} ${px(o.dash)}` } : {}), "pointer-events": "none", ...(o.attrs || {}) }, root);
    // Raster und Achsen
    const x0 = v.cx - (W * k) / 2, x1 = v.cx + (W * k) / 2, y0 = v.cy - (H * k) / 2, y1 = v.cy + (H * k) / 2;
    let step = 1; while (step / k < 22) step *= (step < 5 ? 5 : 2); // sichtbares Raster
    for (let x = Math.ceil(x0 / step) * step; x <= x1; x += step) line([x, y0], [x, y1], { stroke: CLR.grid, w: 0.5 });
    for (let y = Math.ceil(y0 / step) * step; y <= y1; y += step) line([x0, y], [x1, y], { stroke: CLR.grid, w: 0.5 });
    line([x0, 0], [x1, 0], { stroke: CLR.axis, w: 0.8, dash: 6 }); line([0, y0], [0, y1], { stroke: CLR.axis, w: 0.8, dash: 6 });
    text(x1 - px(8), px(10), "x", { size: 11, fill: "#888", anchor: "end" }); text(px(10), y1 - px(10), "y", { size: 11, fill: "#888", anchor: "start" });
    const m = cfg.motor, rodR = cfg.rod.diameter / 2;
    const full = S.res && S.res.state === "full", poly = S.sk.points;
    const bad = S.res && (S.res.state === "conflict" || !S.res.ok);
    const pc = bad ? CLR.conflict : full ? CLR.full : CLR.ok;
    // Huellkurve und Drehvorschau
    const R = Math.max(...poly.map((p) => Math.hypot(p[0], p[1])), ...gearBox().map((p) => Math.hypot(p[0], p[1])));
    if ($s("#skSweep").checked) svgEl("circle", { cx: 0, cy: 0, r: R, fill: "none", stroke: "#8a6", "stroke-width": px(1), "stroke-dasharray": `${px(5)} ${px(4)}`, "pointer-events": "none" }, root);
    if (S.rot) {
      const g = svgEl("g", { transform: `rotate(${S.rot})`, opacity: 0.45, "pointer-events": "none" }, root);
      svgEl("polygon", { points: poly.map((p) => p.join(",")).join(" "), fill: "#c8a", stroke: "#a58", "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}` }, g);
      svgEl("polygon", { points: gearBox().map((p) => p.join(",")).join(" "), fill: "#f9c27a", stroke: "#a60", "stroke-width": px(1) }, g);
      const a = (S.rot * Math.PI) / 180, ar = Math.min(R * 0.5, px(70));
      svgEl("path", { d: `M ${ar} 0 A ${ar} ${ar} 0 ${S.rot > 180 ? 1 : 0} 1 ${ar * Math.cos(a)} ${ar * Math.sin(a)}`, fill: "none", stroke: "#a58", "stroke-width": px(1.5), transform: "rotate(0)" }, root);
      text(ar * 1.2 * Math.cos(a / 2), ar * 1.2 * Math.sin(a / 2), `${S.rot}°`, { size: 12, fill: "#a58" });
    }
    // Zahnrad
    const gb = gearBox();
    svgEl("polygon", { id: "skGear", points: gb.map((p) => p.join(",")).join(" "), fill: "#f28e2b", "fill-opacity": 0.8, stroke: "#333", "stroke-width": px(1), "pointer-events": "none" }, root);
    line([-m.center_distance, -m.gear_width / 2 - px(14)], [-m.center_distance, m.gear_width / 2 + px(14)], { stroke: "#a60", w: 1, dash: 4 });
    const gh = svgEl("circle", { id: "skGearHandle", cx: -m.center_distance, cy: 0, r: px(5), fill: "#f28e2b", stroke: "#fff", "stroke-width": px(1.5), class: "handle", "data-sk-gear": "1" }, root);
    svgEl("title", {}, gh).textContent = "Zahnradachse. Ziehen aendert den Achsabstand";
    text(-m.center_distance, m.gear_width / 2 + px(22), "Zahnrad", { size: 11, fill: "#a60" });
    // Gehaeuse
    const dg = distPointPoly(0, 0, poly) - rodR;
    const clearBad = dg < m.own_clearance - 1e-9;
    svgEl("polygon", { id: "skPoly", points: poly.map((p) => p.join(",")).join(" "), fill: pc, "fill-opacity": 0.16, stroke: pc, "stroke-width": px(2), "pointer-events": "none" }, root);
    // Seiten (zum Anklicken, unsichtbar breit)
    for (let i = 0; i < n(); i++) {
      const a = P(i), b = P(i + 1), selected = S.sel.s.has(i), hov = S.hover && S.hover.sides && S.hover.sides.includes(i);
      if (selected || hov) line(a, b, { stroke: CLR.sel, w: 4.5 });
      svgEl("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "transparent", "stroke-width": px(12), "data-sk-side": i, class: "skside" }, root);
    }
    // Stange
    svgEl("circle", { cx: 0, cy: 0, r: rodR + cfg.rod.hole_clearance, fill: "none", stroke: "currentColor", "stroke-width": px(1), "stroke-dasharray": `${px(4)} ${px(3)}`, "pointer-events": "none" }, root);
    svgEl("circle", { cx: 0, cy: 0, r: rodR + m.own_clearance, fill: "none", stroke: clearBad ? CLR.conflict : "#e08a00", "stroke-width": px(clearBad ? 2 : 1), "stroke-dasharray": `${px(3)} ${px(3)}`, "pointer-events": "none" }, root);
    svgEl("circle", { id: "skRod", cx: 0, cy: 0, r: rodR, fill: "#222", "pointer-events": "none", "data-rod": "1" }, root);
    line([-rodR * 2.2, 0], [rodR * 2.2, 0], { stroke: "#fff", w: 1 }); line([0, -rodR * 2.2], [0, rodR * 2.2], { stroke: "#fff", w: 1 });
    text(rodR + px(10), -rodR - px(10), `Stange ⌀${fmt(cfg.rod.diameter)}`, { size: 12, anchor: "start" });
    // Masse und Constraint Symbole
    const showM = $s("#skShowMeasures").checked;
    const dimText = (x, y, str, status, attrs, rot = 0) => text(x, y, str, { size: 12, fill: status === "conflict" ? CLR.conflict : status === "redundant" ? CLR.redundant : CLR.ok, rot, dim: true, attrs });
    const has = (t, f) => S.sk.constraints.findIndex((c, k2) => c.enabled && c.type === t && f(c));
    for (let i = 0; i < n(); i++) {
      const a = P(i), b = P(i + 1), d = sideVec(i), L = Math.hypot(...d) || 1;
      const nx = d[1] / L, ny = -d[0] / L; // Aussennormale (Kontur gegen den Uhrzeigersinn)
      const ang = (Math.atan2(d[1], d[0]) * 180) / Math.PI;
      const ci = S.sk.constraints.findIndex((c) => c.type === "length" && c.a === i);
      const off = px(18), mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      if (ci >= 0) {
        const st = statusOf(ci), col2 = st === "conflict" ? CLR.conflict : st === "redundant" ? CLR.redundant : CLR.ok;
        const A = [a[0] + nx * off, a[1] + ny * off], B = [b[0] + nx * off, b[1] + ny * off];
        line(a, [a[0] + nx * off * 1.3, a[1] + ny * off * 1.3], { stroke: col2, w: 0.8 }); line(b, [b[0] + nx * off * 1.3, b[1] + ny * off * 1.3], { stroke: col2, w: 0.8 });
        line(A, B, { stroke: col2, w: 1 });
        for (const [Q, s2] of [[A, 1], [B, -1]]) { const ux = (d[0] / L) * s2, uy = (d[1] / L) * s2; svgEl("polygon", { points: `${Q[0]},${Q[1]} ${Q[0] + ux * px(9) + nx * px(3)},${Q[1] + uy * px(9) + ny * px(3)} ${Q[0] + ux * px(9) - nx * px(3)},${Q[1] + uy * px(9) - ny * px(3)}`, fill: col2, "pointer-events": "none" }, root); }
        dimText(mid[0] + nx * (off + px(10)), mid[1] + ny * (off + px(10)), fmt(S.res && S.res.measures ? S.res.measures.sides[i] : L), st, { "data-sk-dim": `length:${i}` }, ang);
      } else if (showM) text(mid[0] + nx * px(12), mid[1] + ny * px(12), fmt(L), { size: 10.5, fill: "#888", rot: ang, dim: true, attrs: { "data-sk-dim": `length:${i}`, class: "skmeasure" } });
      // Symbole auf der Seite
      let glyph = "";
      const rel = (t) => S.sk.constraints.some((c) => c.enabled && c.type === t && (c.a === i || c.b === i));
      if (rel("parallel")) glyph += "∥"; if (rel("perpendicular")) glyph += "⊥"; if (rel("equal")) glyph += "="; if (rel("horizontal")) glyph += "H"; if (rel("vertical")) glyph += "V";
      if (rel("angle_sides")) glyph += "∠"; if (rel("dist_side")) glyph += "⇥";
      if (glyph) text(mid[0] - nx * px(12), mid[1] - ny * px(12), glyph, { size: 14, fill: CLR.ok, rot: ang });
    }
    for (let i = 0; i < n(); i++) {
      const q = P(i), p0 = P(i - 1), r0 = P(i + 1);
      const ang = interiorAngle(i), ci = S.sk.constraints.findIndex((c) => c.type === "angle" && c.a === i);
      const a1 = Math.atan2(p0[1] - q[1], p0[0] - q[0]), a2 = Math.atan2(r0[1] - q[1], r0[0] - q[0]);
      const rr = px(ci >= 0 ? 26 : 20);
      if (ci >= 0 || showM) {
        const st = ci >= 0 ? statusOf(ci) : "ok", col2 = ci < 0 ? "#999" : st === "conflict" ? CLR.conflict : st === "redundant" ? CLR.redundant : CLR.ok;
        // Bogen von der Richtung zum naechsten Punkt (a2) gegen den Uhrzeigersinn bis zum vorherigen Punkt (a1)
        const end = a2 + (ang * Math.PI) / 180;
        svgEl("path", { d: `M ${q[0] + rr * Math.cos(a2)} ${q[1] + rr * Math.sin(a2)} A ${rr} ${rr} 0 ${ang > 180 ? 1 : 0} 1 ${q[0] + rr * Math.cos(end)} ${q[1] + rr * Math.sin(end)}`, fill: "none", stroke: col2, "stroke-width": px(ci >= 0 ? 1.4 : 0.8), "pointer-events": "none" }, root);
        const mid2 = a2 + (ang * Math.PI) / 360;
        const tx = q[0] + (rr + px(14)) * Math.cos(mid2), ty = q[1] + (rr + px(14)) * Math.sin(mid2);
        if (ci >= 0) dimText(tx, ty, `${fmtDeg(ang)}°`, st, { "data-sk-dim": `angle:${i}` });
        else text(tx, ty, `${fmtDeg(ang)}°`, { size: 10, fill: "#999", dim: true, attrs: { "data-sk-dim": `angle:${i}`, class: "skmeasure" } });
      }
    }
    // Abstandsmasse zur Stange oder zum Zahnrad
    S.sk.constraints.forEach((c, ci) => {
      if (!c.enabled) return;
      const st = statusOf(ci), col2 = st === "conflict" ? CLR.conflict : st === "redundant" ? CLR.redundant : CLR.ok;
      if (c.type === "dist_point") {
        const q = P(c.a), r = refPos(c.ref);
        line(r, q, { stroke: col2, w: 1, dash: 5 }); dimText((q[0] + r[0]) / 2, (q[1] + r[1]) / 2 + px(10), fmt(Math.hypot(q[0] - r[0], q[1] - r[1])), st, { "data-sk-dim": `cons:${ci}` });
      } else if (c.type === "dist_side") {
        const a = P(c.a), d = sideVec(c.a), L = Math.hypot(...d) || 1, r = refPos(c.ref);
        const t = ((r[0] - a[0]) * d[0] + (r[1] - a[1]) * d[1]) / (L * L), f = [a[0] + t * d[0], a[1] + t * d[1]];
        line(r, f, { stroke: col2, w: 1, dash: 5 }); dimText((r[0] + f[0]) / 2, (r[1] + f[1]) / 2 + px(10), fmt(Math.hypot(f[0] - r[0], f[1] - r[1])), st, { "data-sk-dim": `cons:${ci}` });
      } else if (c.type === "coord_x" || c.type === "coord_y") {
        const q = P(c.a), lab = (c.type === "coord_x" ? "x " : "y ") + fmt(c.value);
        dimText(q[0] + px(12), q[1] - px(14), lab, st, { "data-sk-dim": `cons:${ci}` });
      }
    });
    // Punkte
    for (let i = 0; i < n(); i++) {
      const q = P(i), selected = S.sel.p.has(i), fixed = S.sk.constraints.some((c) => c.enabled && c.type === "fix" && c.a === i);
      const hov = S.hover && S.hover.points && S.hover.points.includes(i);
      svgEl("circle", { cx: q[0], cy: q[1], r: px(selected || hov ? 7 : 5.5), fill: selected || hov ? CLR.sel : "#fff", stroke: pc, "stroke-width": px(2), class: "handle", "data-sk-point": i }, root);
      if (fixed) svgEl("rect", { x: q[0] + px(7), y: q[1] + px(5), width: px(8), height: px(6), fill: CLR.ok, "pointer-events": "none" }, root), svgEl("path", { d: `M ${q[0] + px(9)} ${q[1] + px(11)} v ${px(3)} a ${px(2)} ${px(2)} 0 0 1 ${px(4)} 0 v ${-px(3)}`, fill: "none", stroke: CLR.ok, "stroke-width": px(1.3), "pointer-events": "none" }, root);
      text(q[0] - px(11), q[1] + px(11), `P${i + 1}`, { size: 10.5, fill: "#666" });
    }
    // Zeichnen
    if (S.tool === "draw") {
      const pts = S.drawPts.concat(S.cursor ? [S.cursor] : []);
      if (pts.length > 1) svgEl("polyline", { points: pts.map((p) => p.join(",")).join(" "), fill: "none", stroke: "#e00", "stroke-width": px(1.5), "stroke-dasharray": `${px(5)} ${px(3)}`, "pointer-events": "none" }, root);
      S.drawPts.forEach((p) => svgEl("circle", { cx: p[0], cy: p[1], r: px(4.5), fill: "#e00", "pointer-events": "none" }, root));
    }
  }

  // --- Panels ---------------------------------------------------------------------------------------------
  const consText = (c) => {
    const s = (i) => `S${i + 1}`, p = (i) => `P${i + 1}`, ref = c.ref === "gear" ? "Zahnrad" : "Stange";
    switch (c.type) {
      case "length": return `Länge ${s(c.a)}`; case "angle": return `Winkel ${p(c.a)}`;
      case "angle_sides": return `Winkel ${s(c.a)} / ${s(c.b)}`; case "parallel": return `${s(c.a)} ∥ ${s(c.b)}`;
      case "perpendicular": return `${s(c.a)} ⊥ ${s(c.b)}`; case "equal": return `${s(c.a)} = ${s(c.b)}`;
      case "horizontal": return `${s(c.a)} horizontal`; case "vertical": return `${s(c.a)} vertikal`;
      case "fix": return `${p(c.a)} fixiert`; case "coord_x": return `x von ${p(c.a)}`; case "coord_y": return `y von ${p(c.a)}`;
      case "dist_point": return `Abstand ${p(c.a)} zu ${ref}`; case "dist_side": return `Abstand ${s(c.a)} zu ${ref}`;
    }
    return c.type;
  };
  const valueKind = (c) => ({ length: "len", dist_point: "len", dist_side: "len", coord_x: "len", coord_y: "len", angle: "deg", angle_sides: "deg" }[c.type] || null);
  const hl = (sides = [], points = []) => { S.hover = sides.length || points.length ? { sides, points } : null; render(); };

  function renderCons() {
    const box = $s("#skCons"); S.rendering = true; box.innerHTML = ""; queueMicrotask(() => { S.rendering = false; });
    if (!S.sk.constraints.length) { box.innerHTML = '<p class="hint">Noch keine Constraints. Seiten oder Punkte waehlen und ein Werkzeug anklicken, oder Werte in den Tabellen eingeben.</p>'; return; }
    S.sk.constraints.forEach((c, k) => {
      const st = statusOf(k), row = document.createElement("div"); row.className = "skcons " + st; row.dataset.skCons = k;
      const dot = { ok: "●", conflict: "✖", redundant: "◐", disabled: "○" }[st] || "●";
      const refs = [];
      const sides = [c.a, c.b].filter((x, i2) => SIDES[c.type] >= i2 + 1 && x != null);
      row.innerHTML = `<span class="dot" title="${esc(S.res && S.res.constraints[k] && S.res.constraints[k].message || st)}">${dot}</span><span class="lbl">${esc(c.name || consText(c))}</span>`;
      const kind = valueKind(c);
      if (kind) {
        const inp = document.createElement("input"); inp.type = "number"; inp.step = "any"; inp.className = "skval";
        inp.value = kind === "len" ? fmt(c.value) : fmtDeg(c.value); inp.dataset.skConsVal = k;
        inp.addEventListener("change", () => { const v = parseFloat(inp.value); if (!isFinite(v)) return; commit((s2) => { s2.constraints[k].value = kind === "len" ? fromU(v) : v; }); });
        row.appendChild(inp);
      }
      const en = document.createElement("input"); en.type = "checkbox"; en.checked = c.enabled; en.title = "Aktiv"; en.addEventListener("change", () => commit((s2) => { s2.constraints[k].enabled = en.checked; }));
      const del = document.createElement("button"); del.textContent = "×"; del.title = "Constraint loeschen"; del.dataset.skConsDel = k;
      del.addEventListener("click", () => commit((s2) => { s2.constraints.splice(k, 1); }));
      row.append(en, del);
      const sideList = c.type === "dist_point" || ["fix", "coord_x", "coord_y", "angle"].includes(c.type) ? [] : sides, ptList = ["dist_point", "fix", "coord_x", "coord_y", "angle"].includes(c.type) ? [c.a] : [];
      row.addEventListener("mouseenter", () => hl(sideList, ptList)); row.addEventListener("mouseleave", () => hl());
      box.appendChild(row);
    });
  }

  function lenConstraintIdx(i) { return S.sk.constraints.findIndex((c) => c.type === "length" && c.a === i); }
  function upsert(s2, type, match, fields) {
    const idx = s2.constraints.findIndex((c) => c.type === type && match(c));
    if (idx >= 0) Object.assign(s2.constraints[idx], fields); else s2.constraints.push(mk(type, fields));
  }
  function renderTables() {
    const sb = $s("#skSides"), pb = $s("#skPoints");
    if (document.activeElement && (sb.contains(document.activeElement) || pb.contains(document.activeElement)) && document.activeElement.tagName === "INPUT" && document.activeElement.dataset.keep) return;
    const ms = S.res && S.res.measures ? S.res.measures : { sides: [...Array(n()).keys()].map(sideLen), angles: [...Array(n()).keys()].map(interiorAngle) };
    let h = `<table class="grid"><tr><th>Seite</th><th>Länge [${unit}]</th><th>parallel zu</th><th>H</th><th>V</th></tr>`;
    for (let i = 0; i < n(); i++) {
      const lc = lenConstraintIdx(i) >= 0;
      const par = S.sk.constraints.find((c) => c.type === "parallel" && c.enabled && (c.a === i || c.b === i));
      const cur = par ? (par.a === i ? par.b : par.a) : "";
      const opts = ['<option value="">—</option>'].concat([...Array(n()).keys()].filter((j) => j !== i).map((j) => `<option value="${j}" ${cur === j ? "selected" : ""}>S${j + 1}</option>`)).join("");
      const hasT = (t) => S.sk.constraints.some((c) => c.type === t && c.enabled && c.a === i);
      h += `<tr class="${S.sel.s.has(i) ? "sel" : ""}" data-row-side="${i}"><td>S${i + 1}</td><td><input type="number" step="any" class="${lc ? "driven" : ""}" data-sk-len="${i}" value="${fmt(ms.sides[i])}"></td>
        <td><select data-sk-par="${i}">${opts}</select></td>
        <td><input type="checkbox" data-sk-hv="horizontal:${i}" ${hasT("horizontal") ? "checked" : ""}></td><td><input type="checkbox" data-sk-hv="vertical:${i}" ${hasT("vertical") ? "checked" : ""}></td></tr>`;
    }
    S.rendering = true; // Entfernt der Browser ein fokussiertes Feld, feuert er change. Das darf nichts ausloesen
    sb.innerHTML = h + "</table>";
    let g = `<table class="grid"><tr><th>Punkt</th><th>x [${unit}]</th><th>y [${unit}]</th><th>Winkel °</th><th></th></tr>`;
    for (let i = 0; i < n(); i++) {
      const q = P(i), cx = S.sk.constraints.some((c) => c.type === "coord_x" && c.a === i), cy = S.sk.constraints.some((c) => c.type === "coord_y" && c.a === i);
      const ca = S.sk.constraints.some((c) => c.type === "angle" && c.a === i), fx = S.sk.constraints.some((c) => c.type === "fix" && c.a === i);
      g += `<tr class="${S.sel.p.has(i) ? "sel" : ""}" data-row-point="${i}"><td>P${i + 1}</td>
        <td><input type="number" step="any" class="${cx || fx ? "driven" : ""}" data-sk-x="${i}" value="${fmt(q[0])}"></td>
        <td><input type="number" step="any" class="${cy || fx ? "driven" : ""}" data-sk-y="${i}" value="${fmt(q[1])}"></td>
        <td><input type="number" step="any" class="${ca ? "driven" : ""}" data-sk-ang="${i}" value="${fmtDeg(ms.angles[i])}"></td>
        <td><button data-sk-fix="${i}" title="Fixieren">${fx ? "gelöst" : "fix"}</button><button data-sk-del="${i}" title="Punkt loeschen">×</button></td></tr>`;
    }
    pb.innerHTML = g + "</table>";
    queueMicrotask(() => { S.rendering = false; });
    const num = (el2) => parseFloat(el2.value);
    sb.querySelectorAll("[data-sk-len]").forEach((inp) => inp.addEventListener("change", () => { const v = num(inp), i = +inp.dataset.skLen; if (v > 0) commit((s2) => upsert(s2, "length", (c) => c.a === i, { a: i, value: fromU(v) })); }));
    sb.querySelectorAll("[data-sk-par]").forEach((sel) => sel.addEventListener("change", () => {
      const i = +sel.dataset.skPar, j = sel.value === "" ? null : +sel.value;
      commit((s2) => { s2.constraints = s2.constraints.filter((c) => !(c.type === "parallel" && (c.a === i || c.b === i))); if (j !== null) s2.constraints.push(mk("parallel", { a: i, b: j })); });
    }));
    sb.querySelectorAll("[data-sk-hv]").forEach((cb) => cb.addEventListener("change", () => {
      const [t, i] = cb.dataset.skHv.split(":"), idx = +i;
      commit((s2) => { s2.constraints = s2.constraints.filter((c) => !(c.type === t && c.a === idx)); if (cb.checked) s2.constraints.push(mk(t, { a: idx })); });
    }));
    pb.querySelectorAll("[data-sk-x]").forEach((inp) => inp.addEventListener("change", () => { const i = +inp.dataset.skX, v = num(inp); if (isFinite(v)) commit((s2) => upsert(s2, "coord_x", (c) => c.a === i, { a: i, value: fromU(v) })); }));
    pb.querySelectorAll("[data-sk-y]").forEach((inp) => inp.addEventListener("change", () => { const i = +inp.dataset.skY, v = num(inp); if (isFinite(v)) commit((s2) => upsert(s2, "coord_y", (c) => c.a === i, { a: i, value: fromU(v) })); }));
    pb.querySelectorAll("[data-sk-ang]").forEach((inp) => inp.addEventListener("change", () => { const i = +inp.dataset.skAng, v = num(inp); if (v > 0 && v < 180) commit((s2) => upsert(s2, "angle", (c) => c.a === i, { a: i, value: v })); }));
    pb.querySelectorAll("[data-sk-fix]").forEach((b) => b.addEventListener("click", () => {
      const i = +b.dataset.skFix;
      commit((s2) => { const idx = s2.constraints.findIndex((c) => c.type === "fix" && c.a === i); if (idx >= 0) s2.constraints.splice(idx, 1); else s2.constraints.push(mk("fix", { a: i, value: s2.points[i][0], value2: s2.points[i][1] })); });
    }));
    pb.querySelectorAll("[data-sk-del]").forEach((b) => b.addEventListener("click", () => deletePoint(+b.dataset.skDel)));
    sb.querySelectorAll("[data-row-side]").forEach((tr) => tr.addEventListener("click", (ev) => { if (ev.target.tagName === "TR" || ev.target.tagName === "TD") { select("s", +tr.dataset.rowSide, ev.shiftKey); } }));
    pb.querySelectorAll("[data-row-point]").forEach((tr) => tr.addEventListener("click", (ev) => { if (ev.target.tagName === "TR" || ev.target.tagName === "TD") { select("p", +tr.dataset.rowPoint, ev.shiftKey); } }));
  }

  function renderStatus() {
    const r = S.res, box = $s("#skStatus"); if (!r) { box.textContent = ""; return; }
    const stateTxt = { under: `Unterbestimmt, ${r.dof} Freiheitsgrade`, full: "Voll bestimmt", over: "Überbestimmt (redundante Constraints)", conflict: "Widerspruch in den Constraints", invalid: "Ungültige Skizze" }[r.state] || r.state;
    const color = { under: CLR.ok, full: CLR.full, over: CLR.redundant, conflict: CLR.conflict, invalid: CLR.conflict }[r.state];
    const rodR = cfg.rod.diameter / 2, dg = n() >= 3 ? distPointPoly(0, 0, S.sk.points) - rodR : 0;
    const items = [`<b style="color:${color}">${stateTxt}</b>`, r.convex ? "Kontur konvex" : "<b style=\"color:var(--bad)\">Kontur nicht konvex</b>"];
    for (const m of [...(r.errors || []), ...(r.warnings || [])]) items.push(`<span style="color:var(--bad)">${esc(m)}</span>`);
    if (dg < cfg.motor.own_clearance - 1e-9) items.push(`<span style="color:var(--bad)">Gehäuse zu nah an der Stange (${fmt(Math.max(0, dg))} ${unit}, benötigt ${fmt(cfg.motor.own_clearance)} ${unit})</span>`);
    if (S.msg) items.push(`<span style="color:var(--bad)">${esc(S.msg)}</span>`);
    if (!S.attached) items.push("Vorschau des aktuellen Motors. Die erste Änderung übernimmt die Skizze in die Konfiguration.");
    box.innerHTML = items.join(" · ");
    box.className = "statusBox" + (r.state === "conflict" || !r.convex || (r.errors || []).length ? " warn" : "");
    $s("#skUndo").disabled = !S.hist.length; $s("#skRedo").disabled = !S.redo.length;
    document.querySelectorAll("[data-sk-add]").forEach((b) => { b.disabled = !canAdd(b.dataset.skAdd); });
    $s("#skDraw").classList.toggle("primary", S.tool === "draw");
    const cd = $s("#skCdIn"); if (cd && document.activeElement !== cd) cd.value = fmt(cfg.motor.center_distance);
  }
  function renderAll() { render(); renderCons(); renderTables(); renderStatus(); }

  // --- Auswahl und Constraints ------------------------------------------------------------------------------
  function select(kind, i, additive) {
    const set = kind === "p" ? S.sel.p : S.sel.s;
    if (!additive) { S.sel = { p: new Set(), s: new Set() }; }
    const target = kind === "p" ? S.sel.p : S.sel.s;
    if (additive && set.has(i)) target.delete(i); else target.add(i);
    renderAll();
  }
  function canAdd(t) {
    const ps = S.sel.p.size, ss = S.sel.s.size;
    switch (t) {
      case "length": return ss === 1 || (ps === 2 && !ss && adjacentSide([...S.sel.p]) !== null);
      case "angle": return (ps === 1 && !ss) || (ss === 2 && !ps);
      case "parallel": case "perpendicular": case "equal": return ss === 2 && !ps;
      case "horizontal": case "vertical": return ss >= 1 && !ps;
      case "fix": return ps >= 1 && !ss;
      case "dist_rod": case "dist_gear": return (ps === 1 && !ss) || (ss === 1 && !ps);
    }
    return false;
  }
  function adjacentSide(pts) { const [a, b] = pts.sort((x, y) => x - y); if (b === a + 1) return a; if (a === 0 && b === n() - 1) return b; return null; }
  function askValue(label, initial, at, cb) {
    const inp = $s("#skInput"), c = $s("#skCanvas"), r = c.getBoundingClientRect(), v = S.view, [W, H] = canvasSize();
    const sx = (at[0] - v.cx) / v.k + W / 2, sy = -(at[1] - v.cy) / v.k + H / 2;
    inp.hidden = false; inp.value = initial; inp.title = label; inp.placeholder = label;
    inp.style.left = Math.max(4, Math.min(W - 110, sx - 45)) + "px"; inp.style.top = Math.max(4, Math.min(H - 30, sy - 12)) + "px";
    inp.focus(); inp.select();
    const done = (ok) => { inp.hidden = true; inp.onkeydown = null; inp.onblur = null; if (ok) { const val = parseFloat(String(inp.value).replace(",", ".")); if (isFinite(val)) cb(val); } };
    inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); done(true); } else if (e.key === "Escape") { e.preventDefault(); done(false); } };
    inp.onblur = () => done(false);
  }
  const mid = (i) => { const a = P(i), b = P(i + 1); return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; };
  function addConstraint(t) {
    const pts = [...S.sel.p].sort((a, b) => a - b), sides = [...S.sel.s].sort((a, b) => a - b);
    if (!canAdd(t)) return;
    if (t === "length") {
      const i = sides.length ? sides[0] : adjacentSide(pts);
      askValue(`Länge S${i + 1} [${unit}]`, fmt(sideLen(i)), mid(i), (v) => { if (v > 0) commit((s2) => upsert(s2, "length", (c) => c.a === i, { a: i, value: fromU(v) })); });
    } else if (t === "angle" && pts.length === 1) {
      const i = pts[0];
      askValue(`Winkel P${i + 1} [Grad]`, fmtDeg(interiorAngle(i)), P(i), (v) => { if (v > 0 && v < 180) commit((s2) => upsert(s2, "angle", (c) => c.a === i, { a: i, value: v })); });
    } else if (t === "angle" && sides.length === 2) {
      const [a, b] = sides, da = sideVec(a), db = sideVec(b);
      const cur = Math.abs(Math.atan2(da[0] * db[1] - da[1] * db[0], da[0] * db[0] + da[1] * db[1])) * 180 / Math.PI;
      askValue(`Winkel S${a + 1} / S${b + 1} [Grad]`, fmtDeg(cur), mid(a), (v) => { if (v >= 0 && v <= 180) commit((s2) => upsert(s2, "angle_sides", (c) => c.a === a && c.b === b, { a, b, value: v })); });
    } else if (["parallel", "perpendicular", "equal"].includes(t)) {
      const [a, b] = sides;
      if (S.sk.constraints.some((c) => c.type === t && ((c.a === a && c.b === b) || (c.a === b && c.b === a)))) { S.msg = "Diese Beziehung existiert bereits."; renderAll(); return; }
      commit((s2) => s2.constraints.push(mk(t, { a, b })));
    } else if (t === "horizontal" || t === "vertical") {
      commit((s2) => sides.forEach((i) => { if (!s2.constraints.some((c) => c.type === t && c.a === i)) s2.constraints.push(mk(t, { a: i })); }));
    } else if (t === "fix") {
      commit((s2) => pts.forEach((i) => { if (!s2.constraints.some((c) => c.type === "fix" && c.a === i)) s2.constraints.push(mk("fix", { a: i, value: s2.points[i][0], value2: s2.points[i][1] })); }));
    } else if (t === "dist_rod" || t === "dist_gear") {
      const ref = t === "dist_gear" ? "gear" : "rod", r = refPos(ref), word = ref === "gear" ? "Zahnrad" : "Stange";
      if (pts.length === 1) {
        const i = pts[0], q = P(i);
        askValue(`Abstand P${i + 1} zu ${word} [${unit}]`, fmt(Math.hypot(q[0] - r[0], q[1] - r[1])), q, (v) => { if (v >= 0) commit((s2) => upsert(s2, "dist_point", (c) => c.a === i && c.ref === ref, { a: i, ref, value: fromU(v) })); });
      } else {
        const i = sides[0], a = P(i), d = sideVec(i), L = sideLen(i) || 1;
        const cur = Math.abs((d[0] * (r[1] - a[1]) - d[1] * (r[0] - a[0])) / L);
        askValue(`Abstand S${i + 1} zu ${word} [${unit}]`, fmt(cur), mid(i), (v) => { if (v >= 0) commit((s2) => upsert(s2, "dist_side", (c) => c.a === i && c.ref === ref, { a: i, ref, value: fromU(v) })); });
      }
    }
  }

  const tracked = (fn) => async (...a) => { S.busy++; try { return await fn(...a); } finally { S.busy--; } };
  const commit = tracked(_commit), structural = tracked(_structural), finishDraw = tracked(_finishDraw), undo = tracked(_undo), redo = tracked(_redo);

  // --- Punkte einfuegen und loeschen --------------------------------------------------------------------------
  async function _structural(op, body) {
    const before = JSON.stringify(S.sk);
    const { data } = await api("/api/sketch/" + op, { sketch: S.sk, cd: cfg.motor.center_distance, gear: gearArg(), ...body });
    if (!data.ok && (data.state === "invalid" || (data.errors && data.errors.length && !data.sketch))) { S.msg = (data.errors || []).join(" "); renderAll(); return; }
    S.hist.push(before); S.redo = []; apply(data); S.msg = ""; S.sel = { p: new Set(), s: new Set() }; sync(); renderAll();
  }
  const deletePoint = (i) => structural("delete", { point: i });

  // --- Zeichnen ------------------------------------------------------------------------------------------------------
  async function _finishDraw() {
    const pts = S.drawPts; S.tool = null; S.drawPts = []; S.cursor = null;
    if (pts.length < 3) { S.msg = "Mindestens 3 Punkte noetig"; renderAll(); return; }
    const before = JSON.stringify(S.sk);
    const { data } = await api("/api/sketch/solve", { sketch: { points: pts, constraints: [] }, cd: cfg.motor.center_distance, gear: gearArg() });
    if (!data.sketch || data.state === "invalid") { S.msg = (data.errors || ["Ungueltige Kontur"]).join(" "); renderAll(); return; }
    S.hist.push(before); S.redo = []; apply(data); S.msg = ""; S.sel = { p: new Set(), s: new Set() }; sync(); renderAll();
  }

  // --- Ziehen mit Solver (gedrosselt, letzte Position gewinnt) ----------------------------------------------------------
  // Der Ziehvorgang (drag) wird mitgegeben, weil S.drag beim Loslassen schon null sein kann,
  // waehrend die letzte Antwort noch unterwegs ist. dragRun erlaubt dem Loslassen, darauf zu warten.
  let dragQueue = null, dragRun = null;
  function dragSolve(drag, target) {
    dragQueue = { drag, target };
    if (!dragRun) dragRun = dragLoop().finally(() => { dragRun = null; });
    return dragRun;
  }
  async function dragLoop() {
    S.busy++;
    try {
      while (dragQueue) {
        const { drag, target } = dragQueue; dragQueue = null;
        const data = await callSolve({ drag: { point: drag.i, target } });
        if (data.ok) { if (!drag.pushed) { S.hist.push(drag.before); S.redo = []; drag.pushed = true; } apply(data); render(); renderStatusLight(); }
      }
    } finally { S.busy--; }
  }
  function renderStatusLight() { renderStatus(); }

  // --- Ereignisse ------------------------------------------------------------------------------------------------------
  function initCanvas() {
    const svg = $s("#skCanvas");
    svg.addEventListener("wheel", (ev) => { ev.preventDefault(); const r = svg.getBoundingClientRect(); zoom(ev.deltaY < 0 ? 1 / 1.15 : 1.15, ev.clientX - r.left, ev.clientY - r.top); }, { passive: false });
    svg.addEventListener("pointerdown", (ev) => {
      if (ev.button === 2) return;
      const [mx, my] = ptr(ev);
      // Doppelklick wird selbst erkannt, weil das Neuzeichnen das Ziel des nativen dblclick zerstoert
      const now = performance.now(), ld = S.lastDown;
      const dbl = !!ld && now - ld.t < 400 && Math.hypot(ev.clientX - ld.x, ev.clientY - ld.y) < 6;
      S.lastDown = { t: now, x: ev.clientX, y: ev.clientY };
      if (S.tool === "draw") { if (dbl) { S.lastDown = null; finishDraw(); } else { S.drawPts.push([snapV(mx), snapV(my)]); render(); } return; }
      if (dbl && !(ev.target.closest && ev.target.closest("[data-sk-point]"))) { const hit = nearestSide(mx, my); if (hit) { S.lastDown = null; structural("insert", { side: hit.i, t: Math.max(0.05, Math.min(0.95, hit.t)) }); return; } }
      const pt = ev.target.closest && ev.target.closest("[data-sk-point]");
      const sd = ev.target.closest && ev.target.closest("[data-sk-side]");
      const gr = ev.target.closest && ev.target.closest("[data-sk-gear]");
      const dm = ev.target.closest && ev.target.closest("[data-sk-dim]");
      if (dm) { openDim(dm.dataset.skDim); ev.preventDefault(); return; }
      svg.setPointerCapture(ev.pointerId);
      if (gr) { S.drag = { type: "gear", moved: false }; return; }
      if (pt) {
        const i = +pt.dataset.skPoint;
        if (!ev.shiftKey && !S.sel.p.has(i)) S.sel = { p: new Set(), s: new Set() };
        if (ev.shiftKey && S.sel.p.has(i)) S.sel.p.delete(i); else S.sel.p.add(i);
        S.drag = { type: "point", i, moved: false, before: JSON.stringify(S.sk), pushed: false, sx: ev.clientX, sy: ev.clientY };
        renderAll(); return;
      }
      if (sd) {
        const i = +sd.dataset.skSide;
        if (!ev.shiftKey) S.sel = { p: new Set(), s: new Set() };
        if (ev.shiftKey && S.sel.s.has(i)) S.sel.s.delete(i); else S.sel.s.add(i);
        S.lastSideClick = { i, t: performance.now() };
        S.drag = { type: "none" }; renderAll(); return;
      }
      if (!ev.shiftKey) S.sel = { p: new Set(), s: new Set() };
      S.drag = { type: "pan", sx: ev.clientX, sy: ev.clientY, cx: S.view.cx, cy: S.view.cy, moved: false };
      renderAll();
    });
    svg.addEventListener("pointermove", (ev) => {
      const [mx, my] = ptr(ev);
      if (S.tool === "draw") { S.cursor = [snapV(mx), snapV(my)]; render(); return; }
      const d = S.drag; if (!d) return;
      if (d.type === "pan") { const dx = ev.clientX - d.sx, dy = ev.clientY - d.sy; if (Math.hypot(dx, dy) > 3) d.moved = true; S.view.cx = d.cx - dx * S.view.k; S.view.cy = d.cy + dy * S.view.k; render(); }
      else if (d.type === "point") { if (!d.moved && Math.hypot(ev.clientX - d.sx, ev.clientY - d.sy) < 4) return; d.moved = true; dragSolve(d, [snapV(mx), snapV(my)]); }
      else if (d.type === "gear") { d.moved = true; const cd = Math.max(0, Math.round(-snapV(mx) * 1000) / 1000); if (cd !== cfg.motor.center_distance) { cfg.motor.center_distance = cd; writeInputs(); render(); S.pending = cd; } }
    });
    const end = async (ev) => {
      const d = S.drag; S.drag = null; if (!d) return;
      S.busy++;
      try {
      if (d.type === "gear" && d.moved) { apply(await callSolve()); sync(); renderAll(); }
      else if (d.type === "point" && d.moved) { if (dragRun) await dragRun; sync(); renderAll(); }
      else if (d.type === "pan") renderAll();
      } finally { S.busy--; }
    };
    svg.addEventListener("pointerup", end); svg.addEventListener("pointercancel", end);
    svg.addEventListener("contextmenu", (ev) => { const pt = ev.target.closest && ev.target.closest("[data-sk-point]"); if (pt) { ev.preventDefault(); deletePoint(+pt.dataset.skPoint); } });
    document.addEventListener("keydown", (ev) => {
      const tab = $s("#tab-sketch"); if (!tab.classList.contains("active")) return;
      const tag = (document.activeElement && document.activeElement.tagName) || "";
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); undo(); }
      else if ((ev.ctrlKey || ev.metaKey) && (ev.key.toLowerCase() === "y" || (ev.shiftKey && ev.key.toLowerCase() === "z"))) { ev.preventDefault(); redo(); }
      else if (ev.key === "Escape") { S.tool = null; S.drawPts = []; S.sel = { p: new Set(), s: new Set() }; renderAll(); }
      else if (ev.key === "Enter" && S.tool === "draw") finishDraw();
      else if (ev.key === "Delete" || ev.key === "Backspace") {
        if (S.sel.p.size) { deletePoint(Math.max(...S.sel.p)); }
      }
    });
  }
  function nearestSide(mx, my) {
    let best = null;
    for (let i = 0; i < n(); i++) {
      const a = P(i), d = sideVec(i), L2 = d[0] * d[0] + d[1] * d[1] || 1;
      const t = Math.max(0, Math.min(1, ((mx - a[0]) * d[0] + (my - a[1]) * d[1]) / L2));
      const dist = Math.hypot(mx - (a[0] + t * d[0]), my - (a[1] + t * d[1]));
      if (dist < 9 * S.view.k && (!best || dist < best.dist)) best = { i, t, dist };
    }
    return best;
  }
  function openDim(key) {
    const [kind, idx] = key.split(":"), i = +idx;
    if (kind === "length") { S.sel = { p: new Set(), s: new Set([i]) }; renderAll(); addConstraint("length"); }
    else if (kind === "angle") { S.sel = { p: new Set([i]), s: new Set() }; renderAll(); addConstraint("angle"); }
    else if (kind === "cons") {
      const c = S.sk.constraints[i], kd = valueKind(c); if (!kd) return;
      askValue(consText(c), kd === "len" ? fmt(c.value) : fmtDeg(c.value), c.type === "dist_point" ? P(c.a) : mid(c.a ?? 0), (v) => commit((s2) => { s2.constraints[i].value = kd === "len" ? fromU(v) : v; }));
    }
  }
  async function _undo() { if (!S.hist.length) return; S.redo.push(JSON.stringify(S.sk)); S.sk = JSON.parse(S.hist.pop()); apply(await callSolve()); sync(); renderAll(); }
  async function _redo() { if (!S.redo.length) return; S.hist.push(JSON.stringify(S.sk)); S.sk = JSON.parse(S.redo.pop()); apply(await callSolve()); sync(); renderAll(); }

  function initSketch() {
    initCanvas();
    for (const id of ["#skSides", "#skPoints", "#skCons"]) $s(id).addEventListener("change", (e) => { if (S.rendering) e.stopImmediatePropagation(); }, true);
    document.querySelectorAll("[data-sk-add]").forEach((b) => b.addEventListener("click", () => addConstraint(b.dataset.skAdd)));
    $s("#skDraw").addEventListener("click", () => { S.tool = S.tool === "draw" ? null : "draw"; S.drawPts = []; renderAll(); });
    $s("#skFromMotor").addEventListener("click", async () => {
      const keepSk = cfg.motor.sketch; cfg.motor.sketch = null;
      const { data } = await api("/api/sketch/from-motor", { motor: cfg.motor }); cfg.motor.sketch = keepSk;
      if (!data.sketch) return; S.hist.push(JSON.stringify(S.sk)); S.redo = []; apply(data); sync(); renderAll();
    });
    $s("#skHull").addEventListener("click", () => structural("hull", {}));
    $s("#skUndo").addEventListener("click", undo); $s("#skRedo").addEventListener("click", redo);
    $s("#skFit").addEventListener("click", () => { fit(); render(); });
    $s("#skZoomIn").addEventListener("click", () => zoom(1 / 1.25)); $s("#skZoomOut").addEventListener("click", () => zoom(1.25));
    $s("#skRot").addEventListener("input", () => { S.rot = +$s("#skRot").value; $s("#skRotVal").textContent = S.rot; render(); });
    for (const id of ["#skSweep", "#skShowMeasures", "#skSnap"]) $s(id).addEventListener("change", render);
    $s("#skDrop").addEventListener("click", () => { cfg.motor.sketch = null; S.attached = false; if (typeof writeInputs === "function") writeInputs(); refresh(); reload(); });
    // Achsabstand
    const box = $s("#skCd"); box.innerHTML = '<label>Achsabstand Zahnrad zu Stange</label><input id="skCdIn" type="number" step="any" min="0">';
    $s("#skCdIn").addEventListener("change", async () => { const v = parseFloat($s("#skCdIn").value); if (!(v >= 0)) return; cfg.motor.center_distance = fromU(v); writeInputs(); apply(await callSolve()); sync(); renderAll(); });
    window.addEventListener("resize", () => { if ($s("#tab-sketch").classList.contains("active")) render(); });
    new ResizeObserver(() => { if ($s("#tab-sketch").classList.contains("active")) render(); }).observe($s("#skCanvasWrap"));
  }
  window.initSketch = initSketch;
  window.skReload = reload;
  window.skRender = renderAll;
  window.skSelect = (points, sides) => { S.sel = { p: new Set(points), s: new Set(sides) }; renderAll(); };
  window.skAdd = addConstraint;
})();
