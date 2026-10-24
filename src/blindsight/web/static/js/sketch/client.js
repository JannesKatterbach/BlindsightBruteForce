"use strict";
// Motor sketch. Solver calls, taking over results, history and sync with the configuration.

(() => {
  const SYNC_DEBOUNCE_MS = 120;
  const gearArg = () => [cfg.motor.gear_diameter, cfg.motor.gear_width];
  const request = (sketch, extra = {}) => ({ sketch, cd: cfg.motor.center_distance, gear: gearArg(), ...extra });
  // Changes of the sketch run one after another. Otherwise a late answer could overwrite a newer one
  const queue = serialQueue();

  async function callSolve(extra = {}) {
    const { data } = await api("/api/sketch/solve", request(SK.sk, extra));
    return data;
  }

  /** Take over the result of the solver and limit the selection to existing points and sides. */
  function apply(data) {
    if (data.sketch && data.sketch.points && data.sketch.points.length >= 3) {
      SK.sk = { points: data.sketch.points, constraints: data.sketch.constraints };
    }
    SK.res = data;
    SK.sel.p = new Set([...SK.sel.p].filter((i) => i < skCount()));
    SK.sel.s = new Set([...SK.sel.s].filter((i) => i < skCount()));
  }

  const isInvalid = (data) => data.state === "invalid" && errorsOf(data).length > 0;

  /** Change a copy of the sketch, have it solved and take it over if it is valid. */
  function commit(mutator) {
    return queue(async () => {
      const before = JSON.stringify(SK.sk);
      const candidate = clone(SK.sk);
      mutator(candidate);
      const { data } = await api("/api/sketch/solve", request(candidate));
      if (isInvalid(data)) { SK.msg = errorsOf(data).join(" "); Sketch.renderAll(); return false; }
      skPushHistory(before);
      apply(data);
      SK.msg = "";
      sync();
      Sketch.renderAll();
      return true;
    });
  }

  /** Structural change (insert or delete a point, convex hull) via the server. */
  function structural(op, body) {
    return queue(async () => {
      const before = JSON.stringify(SK.sk);
      const { data } = await api("/api/sketch/" + op, request(SK.sk, body));
      if (!data.ok && (data.state === "invalid" || (errorsOf(data).length && !data.sketch))) {
        SK.msg = errorsOf(data).join(" ");
        Sketch.renderAll();
        return;
      }
      skPushHistory(before);
      apply(data);
      SK.msg = "";
      skClearSelection();
      sync();
      Sketch.renderAll();
    });
  }

  /** Take a drawn polygon as the new sketch. */
  function finishDraw() {
    const points = SK.drawPts;
    SK.tool = null;
    SK.drawPts = [];
    SK.cursor = null;
    if (points.length < 3) { SK.msg = t("ui.sk.min_points"); Sketch.renderAll(); return Promise.resolve(); }
    return queue(async () => {
      const before = JSON.stringify(SK.sk);
      const { data } = await api("/api/sketch/solve", request({ points, constraints: [] }));
      if (!data.sketch || data.state === "invalid") { SK.msg = (errorsOf(data).length ? errorsOf(data) : [t("ui.sk.invalid_outline")]).join(" "); Sketch.renderAll(); return; }
      skPushHistory(before);
      apply(data);
      SK.msg = "";
      skClearSelection();
      sync();
      Sketch.renderAll();
    });
  }

  /** History. from and to are SK.hist and SK.redo (or the other way round). */
  function step(from, to) {
    return queue(async () => {
      if (!from.length) return;
      to.push(JSON.stringify(SK.sk));
      SK.sk = JSON.parse(from.pop());
      apply(await callSolve());
      sync();
      Sketch.renderAll();
    });
  }

  /** Solve again with the current sketch (e.g. after a changed centre distance). */
  function resolve() {
    return queue(async () => {
      apply(await callSolve());
      sync();
      Sketch.renderAll();
    });
  }

  /** Rectangle from the motor data as the new sketch (can be undone). */
  function fromMotor() {
    return queue(async () => {
      const motor = { ...cfg.motor, sketch: null };
      const { data } = await api("/api/sketch/from-motor", { motor });
      if (!data.sketch) return;
      skPushHistory(JSON.stringify(SK.sk));
      apply(data);
      sync();
      Sketch.renderAll();
    });
  }

  // --- Sync with the configuration ------------------------------------------------------------------
  let syncTimer = null;
  /** Take a valid sketch into cfg.motor (width and depth from the bounding box). */
  function sync() {
    if (!SK.res || SK.res.state === "invalid" || skCount() < 3) return;
    cfg.motor.outline = null;
    cfg.motor.sketch = clone(SK.sk);
    const b = SK.res.bbox;
    if (b) {
      cfg.motor.width = Math.max(0.01, b.xmax - b.xmin);
      cfg.motor.depth = Math.max(0.01, b.ymax - b.ymin);
    }
    SK.attached = true;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => { writeInputs(); drawMotor(); refresh(); }, SYNC_DEBOUNCE_MS);
  }

  /** Load the sketch from cfg (or the rectangle of the motor as a preview). Only the newest call counts. */
  let reloadSeq = 0;
  async function reload() {
    const tab = $("#tab-sketch");
    if (!tab || !tab.classList.contains("active")) return;
    const mine = ++reloadSeq;
    let sketch, data, attached;
    if (hasSketch(cfg.motor)) {
      sketch = { points: clone(cfg.motor.sketch.points), constraints: clone(cfg.motor.sketch.constraints || []).map((c) => ({ ...makeConstraint(c.type), ...c })) };
      data = (await api("/api/sketch/solve", request(sketch))).data;
      attached = true;
    } else {
      data = (await api("/api/sketch/from-motor", { motor: cfg.motor })).data;
      sketch = data && data.sketch;
      attached = false;
    }
    if (mine !== reloadSeq || !sketch) return;  // reloaded meanwhile
    SK.sk = sketch;
    SK.attached = attached;
    apply(data);
    SK.hist = [];
    SK.redo = [];
    skClearSelection();
    SK.tool = null;
    SK.drawPts = [];
    if (!SK.fitted) Sketch.fit();
    Sketch.renderAll();
  }

  /** Discard the sketch, back to the rectangle of the motor. */
  function drop() {
    cfg.motor.sketch = null;
    SK.attached = false;
    writeInputs();
    refresh();
    reload();
  }

  // --- Dragging a point (throttled, the last position wins) ------------------------------------
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
        const data = await callSolve({ drag: { point: drag.i, target } });
        if (!data.ok) continue;
        if (!drag.pushed) { skPushHistory(drag.before); drag.pushed = true; }
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
    callSolve, apply, sync, drop, dragSolve, dragDone,
    reload: skTracked(reload),
    commit: skTracked(commit),
    structural: skTracked(structural),
    finishDraw: skTracked(finishDraw),
    undo: skTracked(() => step(SK.hist, SK.redo)),
    redo: skTracked(() => step(SK.redo, SK.hist)),
    resolve: skTracked(resolve),
    fromMotor: skTracked(fromMotor),
    deletePoint: (i) => Sketch.structural("delete", { point: i }),
  });
})();
