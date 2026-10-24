"use strict";
// Motor Skizze. Maus und Tastatur auf der Zeichenflaeche.

(() => {
  const DOUBLE_CLICK_MS = 400;
  const DOUBLE_CLICK_PX = 6;
  const DRAG_START_PX = 4;  // ab dieser Bewegung wird ein Punkt gezogen
  const PAN_START_PX = 3;
  const INSERT_T_MIN = 0.05, INSERT_T_MAX = 0.95;  // eingefuegte Punkte nicht direkt auf einer Ecke
  const WHEEL_ZOOM = 1.15;

  const snap = (v) => { const grid = parseFloat($("#skSnap").value); return grid > 0 ? Math.round(v / grid) * grid : v; };
  const pointerMm = (ev) => svgPoint($("#skCanvas"), ev);
  const closest = (ev, selector) => (ev.target.closest ? ev.target.closest(selector) : null);

  /** Eigene Doppelklick Erkennung. Das Neuzeichnen zerstoert das Ziel des nativen dblclick. */
  function isDoubleClick(ev) {
    const now = performance.now(), last = SK.lastDown;
    const double = !!last && now - last.t < DOUBLE_CLICK_MS && Math.hypot(ev.clientX - last.x, ev.clientY - last.y) < DOUBLE_CLICK_PX;
    SK.lastDown = double ? null : { t: now, x: ev.clientX, y: ev.clientY };
    return double;
  }

  function onPointerDown(ev) {
    if (ev.button === 2) return;
    const svg = $("#skCanvas");
    const [mx, my] = pointerMm(ev);
    const double = isDoubleClick(ev);
    if (SK.tool === "draw") {
      if (double) Sketch.finishDraw();
      else { SK.drawPts.push([snap(mx), snap(my)]); Sketch.render(); }
      return;
    }
    const pointNode = closest(ev, "[data-sk-point]");
    if (double && !pointNode) {
      const hit = Sketch.nearestSide(mx, my);
      if (hit) { Sketch.structural("insert", { side: hit.i, t: Math.max(INSERT_T_MIN, Math.min(INSERT_T_MAX, hit.t)) }); return; }
    }
    const dimension = closest(ev, "[data-sk-dim]");
    if (dimension) { Sketch.openDimension(dimension.dataset.skDim); ev.preventDefault(); return; }
    svg.setPointerCapture(ev.pointerId);
    if (closest(ev, "[data-sk-gear]")) { SK.drag = { type: "gear", moved: false }; return; }
    if (pointNode) {
      const i = +pointNode.dataset.skPoint;
      if (!ev.shiftKey && !SK.sel.p.has(i)) skClearSelection();
      if (ev.shiftKey && SK.sel.p.has(i)) SK.sel.p.delete(i);
      else SK.sel.p.add(i);
      SK.drag = { type: "point", i, moved: false, before: JSON.stringify(SK.sk), pushed: false, sx: ev.clientX, sy: ev.clientY };
      Sketch.renderAll();
      return;
    }
    const sideNode = closest(ev, "[data-sk-side]");
    if (sideNode) {
      const i = +sideNode.dataset.skSide;
      if (!ev.shiftKey) skClearSelection();
      if (ev.shiftKey && SK.sel.s.has(i)) SK.sel.s.delete(i);
      else SK.sel.s.add(i);
      SK.drag = { type: "none" };
      Sketch.renderAll();
      return;
    }
    if (!ev.shiftKey) skClearSelection();
    SK.drag = { type: "pan", sx: ev.clientX, sy: ev.clientY, cx: SK.view.cx, cy: SK.view.cy, moved: false };
    Sketch.renderAll();
  }

  function onPointerMove(ev) {
    const [mx, my] = pointerMm(ev);
    if (SK.tool === "draw") { SK.cursor = [snap(mx), snap(my)]; Sketch.render(); return; }
    const d = SK.drag;
    if (!d) return;
    if (d.type === "pan") {
      const dx = ev.clientX - d.sx, dy = ev.clientY - d.sy;
      if (Math.hypot(dx, dy) > PAN_START_PX) d.moved = true;
      SK.view.cx = d.cx - dx * SK.view.k;
      SK.view.cy = d.cy + dy * SK.view.k;
      Sketch.render();
    } else if (d.type === "point") {
      if (!d.moved && Math.hypot(ev.clientX - d.sx, ev.clientY - d.sy) < DRAG_START_PX) return;
      d.moved = true;
      Sketch.dragSolve(d, [snap(mx), snap(my)]);
    } else if (d.type === "gear") {
      d.moved = true;
      const cd = Math.max(0, Math.round(-snap(mx) * 1000) / 1000);
      if (cd !== cfg.motor.center_distance) { cfg.motor.center_distance = cd; writeInputs(); Sketch.render(); }
    }
  }

  const onPointerUp = skTracked(async () => {
    const d = SK.drag;
    SK.drag = null;
    if (!d) return;
    if (d.type === "gear" && d.moved) await Sketch.resolve();
    else if (d.type === "point" && d.moved) { await Sketch.dragDone(); Sketch.sync(); Sketch.renderAll(); }
    else if (d.type === "pan") Sketch.renderAll();
  });

  function onKeyDown(ev) {
    if (!$("#tab-sketch").classList.contains("active")) return;
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    const key = ev.key.toLowerCase(), ctrl = ev.ctrlKey || ev.metaKey;
    if (ctrl && key === "z" && !ev.shiftKey) { ev.preventDefault(); Sketch.undo(); }
    else if (ctrl && (key === "y" || (ev.shiftKey && key === "z"))) { ev.preventDefault(); Sketch.redo(); }
    else if (ev.key === "Escape") { SK.tool = null; SK.drawPts = []; skClearSelection(); Sketch.renderAll(); }
    else if (ev.key === "Enter" && SK.tool === "draw") Sketch.finishDraw();
    else if ((ev.key === "Delete" || ev.key === "Backspace") && SK.sel.p.size) Sketch.deletePoint(Math.max(...SK.sel.p));
  }

  function initCanvas() {
    const svg = $("#skCanvas");
    svg.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const r = svg.getBoundingClientRect();
      Sketch.zoom(ev.deltaY < 0 ? 1 / WHEEL_ZOOM : WHEEL_ZOOM, ev.clientX - r.left, ev.clientY - r.top);
    }, { passive: false });
    svg.addEventListener("pointerdown", onPointerDown);
    svg.addEventListener("pointermove", onPointerMove);
    svg.addEventListener("pointerup", onPointerUp);
    svg.addEventListener("pointercancel", onPointerUp);
    svg.addEventListener("contextmenu", (ev) => {
      const pointNode = closest(ev, "[data-sk-point]");
      if (pointNode) { ev.preventDefault(); Sketch.deletePoint(+pointNode.dataset.skPoint); }
    });
    document.addEventListener("keydown", onKeyDown);
  }

  Object.assign(Sketch, { initCanvas });
})();
