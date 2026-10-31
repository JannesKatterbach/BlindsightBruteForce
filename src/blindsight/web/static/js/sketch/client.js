"use strict";
// Motor sketch. Solver calls, taking over results, history, editing and sync with the configuration.

(() => {
  const SYNC_DEBOUNCE_MS = 120;
  // Changes of the sketch run one after another. Otherwise a late answer could overwrite a newer one
  const queue = serialQueue();

  async function callSolve(sketch = SK.sk, extra = {}) {
    const { data } = await api("/api/sketch/solve", { sketch, ...extra });
    return data;
  }

  const isInvalid = (data) => !data || (data.state === "invalid" && errorsOf(data).length > 0);

  /** Take over the result of the solver and drop selections of things that no longer exist. */
  function apply(data) {
    if (data.sketch && Array.isArray(data.sketch.points)) SK.sk = data.sketch;
    SK.res = data;
    const exists = (ref) => {
      if (ref === "o") return true;
      const i = +ref.slice(1);
      return ref[0] === "p" ? i < SK.sk.points.length : ref[0] === "e" ? i < SK.sk.entities.length : i < SK.sk.constraints.length;
    };
    SK.sel = new Set([...SK.sel].filter(exists));
  }

  /** Change a copy of the sketch, have it solved and take it over if it is valid. */
  function commit(mutator) {
    return queue(async () => {
      const before = JSON.stringify(SK.sk);
      const candidate = clone(SK.sk);
      if (mutator(candidate) === false) return false;
      const data = await callSolve(candidate);
      if (isInvalid(data)) { SK.msg = errorsOf(data).join(" "); Sketch.renderAll(); return false; }
      skPushHistory(before);
      apply(data);
      SK.msg = "";
      sync();
      Sketch.renderAll();
      return true;
    });
  }

  /** History. from and to are SK.hist and SK.redo (or the other way round). */
  function step(from, to) {
    return queue(async () => {
      if (!from.length) return;
      to.push(JSON.stringify(SK.sk));
      SK.sk = JSON.parse(from.pop());
      SK.sel.clear();
      apply(await callSolve());
      sync();
      Sketch.renderAll();
    });
  }

  /** Solve again with the current sketch (e.g. after a language switch). */
  function resolve() {
    return queue(async () => {
      apply(await callSolve());
      Sketch.renderAll();
    });
  }

  /** Housing rectangle and gear from the motor fields as the new sketch (can be undone). */
  function fromMotor() {
    return queue(async () => {
      const { data } = await api("/api/sketch/from-motor", { motor: { ...cfg.motor, sketch: null } });
      if (!data.sketch) return;
      skPushHistory(JSON.stringify(SK.sk));
      apply(data);
      sync();
      Sketch.renderAll();
    });
  }

  // --- Editing -----------------------------------------------------------------------------------------------
  /** Remove entities with their points and all constraints that refer to them (like the core). */
  function deleteEntities(sk, indices) {
    const removedPoints = new Set([...indices].flatMap((k) => sk.entities[k].points));
    const keepE = sk.entities.map((_, k) => k).filter((k) => !indices.has(k));
    const keepP = sk.points.map((_, i) => i).filter((i) => !removedPoints.has(i));
    const newE = new Map(keepE.map((old, i) => [old, i])), newP = new Map(keepP.map((old, i) => [old, i]));
    const remap = (ref) => {
      if (ref === "o") return ref;
      const table = ref[0] === "p" ? newP : newE, i = +ref.slice(1);
      return table.has(i) ? ref[0] + table.get(i) : null;
    };
    sk.constraints = sk.constraints.map((c) => ({ ...c, refs: c.refs.map(remap) })).filter((c) => c.refs.every((r) => r !== null));
    sk.entities = keepE.map((k) => ({ ...sk.entities[k], points: sk.entities[k].points.map((p) => newP.get(p)) }));
    sk.points = keepP.map((i) => sk.points[i]);
  }

  /** Delete the selection. Constraints directly, points by their entity. */
  function deleteSelection() {
    if (!SK.sel.size) return Promise.resolve(false);
    const sel = [...SK.sel];
    SK.sel.clear();
    return commit((sk) => {
      const cons = new Set(sel.filter((r) => r[0] === "c").map((r) => +r.slice(1)));
      sk.constraints = sk.constraints.filter((_, k) => !cons.has(k));
      const ents = new Set(sel.filter((r) => r[0] === "e").map((r) => +r.slice(1)));
      sel.filter((r) => r[0] === "p").forEach((r) => { const owner = sk.entities.findIndex((e) => e.points.includes(+r.slice(1))); if (owner >= 0) ents.add(owner); });
      if (!ents.size && !cons.size) return false;
      deleteEntities(sk, ents);
    });
  }

  /** Switch the selected entities between normal and construction geometry (Q). */
  function toggleConstruction() {
    const ents = [...SK.sel].filter((r) => r[0] === "e").map((r) => +r.slice(1)).filter((k) => SK.sk.entities[k].type !== "point");
    if (!ents.length) return Promise.resolve(false);
    const target = !ents.every((k) => SK.sk.entities[k].construction);
    return commit((sk) => { ents.forEach((k) => { sk.entities[k].construction = target; }); });
  }

  // --- Sync with the configuration ------------------------------------------------------------------------
  let syncTimer = null;
  /** Take a valid sketch into cfg.motor. Housing size, gear and centre distance come from the sketch. */
  function sync() {
    if (!SK.res || SK.res.state === "invalid") return;
    cfg.motor.outline = null;
    cfg.motor.sketch = clone(SK.sk);
    const prof = SK.res.profile || {};
    if (prof.bbox) {
      cfg.motor.width = Math.max(0.01, prof.bbox.xmax - prof.bbox.xmin);
      cfg.motor.depth = Math.max(0.01, prof.bbox.ymax - prof.bbox.ymin);
    }
    if (prof.gear) {
      cfg.motor.gear_diameter = prof.gear.diameter;
      cfg.motor.gear_width = prof.gear.width;
      cfg.motor.center_distance = prof.gear.center_distance;
    }
    SK.attached = true;
    updateSketchLock();  // at once, the redraw below is debounced
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => { writeInputs(); drawMotor(); refresh(); }, SYNC_DEBOUNCE_MS);
  }

  /** Load the sketch from cfg (or the motor fields as a preview). Only the newest call counts. */
  let reloadSeq = 0;
  async function reload() {
    const tab = $("#tab-sketch");
    if (!tab || !tab.classList.contains("active")) return;
    const mine = ++reloadSeq;
    // Back on the tab with the sketch unchanged. Keep tool, selection and history
    if (SK.res && SK.attached && hasSketch(cfg.motor) && JSON.stringify(cfg.motor.sketch) === JSON.stringify(SK.sk)) { Sketch.renderAll(); return; }
    let data, attached;
    if (hasSketch(cfg.motor)) {
      data = await callSolve(clone(cfg.motor.sketch));
      attached = true;
    } else {
      data = (await api("/api/sketch/from-motor", { motor: { ...cfg.motor, sketch: null } })).data;
      attached = false;
    }
    if (mine !== reloadSeq || !data || !data.sketch) return;  // reloaded meanwhile
    SK.sk = data.sketch;
    SK.attached = attached;
    apply(data);
    SK.hist = [];
    SK.redo = [];
    SK.sel.clear();
    Sketch.setTool("select");
    if (!SK.fitted) Sketch.fit();
    Sketch.renderAll();
  }

  /** Discard the sketch, back to the rectangle of the motor fields. */
  function drop() {
    cfg.motor.sketch = null;
    SK.attached = false;
    writeInputs();
    refresh();
    reload();
  }

  // --- Dragging (throttled, the last position wins) --------------------------------------------------------
  // The drag is passed along because SK.drag may already be null on release while the last answer is still
  // on its way. dragRun lets the release wait for it.
  let dragQueue = null, dragRun = null;
  function dragSolve(drag, target) {
    dragQueue = { drag, target };
    if (!dragRun) dragRun = dragLoop().finally(() => { dragRun = null; });
    return dragRun;
  }
  async function dragLoop() {
    SK.busy++;
    try {
      while (dragQueue) {
        const { drag, target } = dragQueue;
        dragQueue = null;
        const data = await callSolve(SK.sk, { drag: { ref: drag.ref, grab: drag.grab, target, mode: drag.mode } });
        if (!data || !data.ok) continue;
        if (!drag.pushed) { skPushHistory(drag.before); drag.pushed = true; }
        drag.grab = target;  // the next move continues from here
        apply(data);
        Sketch.render();
        Sketch.renderStatus();
      }
    } finally {
      SK.busy--;
    }
  }
  const dragDone = () => dragRun || Promise.resolve();

  Object.assign(Sketch, {
    callSolve, apply, sync, drop, dragSolve, dragDone, deleteEntities,
    reload: skTracked(reload),
    commit: skTracked(commit),
    undo: skTracked(() => step(SK.hist, SK.redo)),
    redo: skTracked(() => step(SK.redo, SK.hist)),
    resolve: skTracked(resolve),
    fromMotor: skTracked(fromMotor),
    deleteSelection: skTracked(deleteSelection),
    toggleConstruction: skTracked(toggleConstruction),
  });
})();
