"use strict";
// Motor sketch. Mouse and keyboard on the canvas, shortcuts like Onshape.

(() => {
  const DOUBLE_CLICK_MS = 400;
  const DOUBLE_CLICK_PX = 6;
  const DRAG_START_PX = 4;  // from this movement on a click becomes a drag
  const WHEEL_ZOOM = 1.15;
  // Shortcuts. Tools and relations (Onshape uses the same letters for most of them)
  const KEYS = { l: "line", r: "rect", c: "circle", a: "arc", g: "gear", d: "dimension", s: "select", i: "coincident", h: "horizontal", v: "vertical", e: "equal" };

  const pointerMm = (ev) => svgPoint($("#skCanvas"), ev);
  const closest = (ev, selector) => (ev.target.closest ? ev.target.closest(selector) : null);

  /** Own double click detection. Redrawing destroys the target of the native dblclick. */
  function isDoubleClick(ev) {
    const now = performance.now(), last = SK.lastDown;
    const double = !!last && now - last.t < DOUBLE_CLICK_MS && Math.hypot(ev.clientX - last.x, ev.clientY - last.y) < DOUBLE_CLICK_PX;
    SK.lastDown = double ? null : { t: now, x: ev.clientX, y: ev.clientY };
    return double;
  }

  function onPointerDown(ev) {
    if (ev.button === 2) return;
    const svg = $("#skCanvas");
    const p = pointerMm(ev);
    const double = isDoubleClick(ev);
    const dimText = closest(ev, "[data-sk-dim]");
    if (dimText && (SK.tool === "select" || SK.tool === "dimension")) {
      const k = +dimText.dataset.skDim;
      if (double) { Sketch.editDimension(k); ev.preventDefault(); return; }
      svg.setPointerCapture(ev.pointerId);
      SK.drag = { type: "label", k, sx: ev.clientX, sy: ev.clientY, moved: false };
      return;
    }
    if (DRAW_TOOLS.includes(SK.tool)) {
      if (double && SK.tool === "line") { Sketch.finishDraft(); return; }
      Sketch.drawClick(p);
      return;
    }
    const glyph = closest(ev, ".skglyph");
    if (glyph) {
      toggleSelection(glyph.dataset.skRef, true);
      return;
    }
    const ref = Sketch.hit(p);
    if (SK.tool === "dimension") {
      if (ref) Sketch.pickForDimension(ref);
      else if (Sketch.placeDimension(p)) ev.preventDefault();
      return;
    }
    if (RELATIONS.includes(SK.tool)) {
      if (ref) Sketch.pickForRelation(ref);
      return;
    }
    svg.setPointerCapture(ev.pointerId);
    if (ref && ref !== "o") {
      const e = ref[0] === "e" ? SK.sk.entities[+ref.slice(1)] : null;
      SK.drag = { type: "geometry", ref, grab: p, before: JSON.stringify(SK.sk), pushed: false, moved: false, sx: ev.clientX, sy: ev.clientY,
                  mode: e && e.type === "circle" ? "radius" : "move", additive: ev.shiftKey || ev.ctrlKey || ev.metaKey };
      return;
    }
    SK.drag = { type: "pan", ref, sx: ev.clientX, sy: ev.clientY, cx: SK.view.cx, cy: SK.view.cy, moved: false };
  }

  function onPointerMove(ev) {
    const p = pointerMm(ev);
    SK.cursor = p;
    const d = SK.drag;
    if (!d) {
      if (DRAW_TOOLS.includes(SK.tool)) SK.snap = Sketch.infer(p);
      else {
        const glyph = closest(ev, ".skglyph");
        SK.hover = glyph ? glyph.dataset.skRef : Sketch.hit(p);
      }
      Sketch.render();
      return;
    }
    const dx = ev.clientX - d.sx, dy = ev.clientY - d.sy;
    if (!d.moved && Math.hypot(dx, dy) < DRAG_START_PX) return;
    d.moved = true;
    if (d.type === "pan") {
      SK.view.cx = d.cx - dx * SK.view.k;
      SK.view.cy = d.cy + dy * SK.view.k;
      Sketch.render();
    } else if (d.type === "label") {
      SK.sk.constraints[d.k].label = p;
      Sketch.render();
    } else {
      Sketch.dragSolve(d, p);
    }
  }

  const onPointerUp = skTracked(async () => {
    const d = SK.drag;
    SK.drag = null;
    if (!d) return;
    if (d.type === "label") {
      if (d.moved) { const label = SK.sk.constraints[d.k].label; await Sketch.commit((s) => { s.constraints[d.k].label = label; }); }
      else toggleSelection(`c${d.k}`, true);
      return;
    }
    if (d.type === "geometry" && d.moved) { await Sketch.dragDone(); Sketch.sync(); Sketch.renderAll(); return; }
    if (d.type === "geometry") { toggleSelection(d.ref, true); return; }
    if (!d.moved) { SK.sel.clear(); Sketch.renderAll(); }  // click into free space clears the selection
  });

  /** Click on an element in the select tool adds it to the selection or removes it again (like Onshape). */
  function toggleSelection(ref, additive) {
    if (!additive) SK.sel.clear();
    if (SK.sel.has(ref)) SK.sel.delete(ref);
    else SK.sel.add(ref);
    Sketch.renderAll();
  }

  /** Esc steps back. Draft, then dimension or relation tool, then the selection. */
  function escape() {
    $("#skInput").hidden = true;
    if (SK.draft || SK.dimPlace || SK.pick.length) { SK.draft = null; SK.dimPlace = null; SK.pick = []; Sketch.renderAll(); return; }
    if (SK.tool !== "select") { Sketch.setTool("select"); return; }
    SK.sel.clear();
    Sketch.renderAll();
  }

  function onKeyDown(ev) {
    if (!$("#tab-sketch").classList.contains("active")) return;
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    const key = ev.key.toLowerCase(), ctrl = ev.ctrlKey || ev.metaKey;
    if (ctrl && key === "z" && !ev.shiftKey) { ev.preventDefault(); Sketch.undo(); }
    else if (ctrl && (key === "y" || (ev.shiftKey && key === "z"))) { ev.preventDefault(); Sketch.redo(); }
    else if (ctrl) return;
    else if (ev.key === "Escape") escape();
    else if (ev.key === "Enter" && SK.draft) Sketch.finishDraft();
    else if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); Sketch.deleteSelection(); }
    else if (key === "q") Sketch.toggleConstruction();
    else if (key === "f") { Sketch.fit(); Sketch.render(); }
    else if (KEYS[key]) {
      ev.preventDefault();
      if (RELATIONS.includes(KEYS[key])) Sketch.relation(KEYS[key]);
      else Sketch.setTool(KEYS[key]);
    }
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
    svg.addEventListener("pointerleave", () => { SK.cursor = null; SK.snap = null; SK.hover = null; if (!SK.drag) Sketch.render(); });
    svg.addEventListener("contextmenu", (ev) => ev.preventDefault());
    document.addEventListener("keydown", onKeyDown);
  }

  Object.assign(Sketch, { initCanvas, toggleSelection, escape });
})();
