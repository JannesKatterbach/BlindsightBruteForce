"use strict";
// Motor Skizze. Aufrufe des Solvers, Uebernahme der Ergebnisse, Verlauf und Abgleich mit der Konfiguration.

(() => {
  const SYNC_DEBOUNCE_MS = 120;
  const gearArg = () => [cfg.motor.gear_diameter, cfg.motor.gear_width];
  const request = (sketch, extra = {}) => ({ sketch, cd: cfg.motor.center_distance, gear: gearArg(), ...extra });
  // Aenderungen an der Skizze laufen nacheinander. Sonst koennte eine spaete Antwort eine neuere ueberschreiben
  const queue = serialQueue();

  async function callSolve(extra = {}) {
    const { data } = await api("/api/sketch/solve", request(SK.sk, extra));
    return data;
  }

  /** Ergebnis des Solvers uebernehmen und die Auswahl auf vorhandene Punkte und Seiten begrenzen. */
  function apply(data) {
    if (data.sketch && data.sketch.points && data.sketch.points.length >= 3) {
      SK.sk = { points: data.sketch.points, constraints: data.sketch.constraints };
    }
    SK.res = data;
    SK.sel.p = new Set([...SK.sel.p].filter((i) => i < skCount()));
    SK.sel.s = new Set([...SK.sel.s].filter((i) => i < skCount()));
  }

  const isInvalid = (data) => data.state === "invalid" && errorsOf(data).length > 0;

  /** Aendert eine Kopie der Skizze, laesst sie loesen und uebernimmt sie, wenn sie gueltig ist. */
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

  /** Strukturaenderung (Punkt einfuegen oder loeschen, konvexe Huelle) ueber den Server. */
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

  /** Gezeichnetes Polygon als neue Skizze uebernehmen. */
  function finishDraw() {
    const points = SK.drawPts;
    SK.tool = null;
    SK.drawPts = [];
    SK.cursor = null;
    if (points.length < 3) { SK.msg = "Mindestens 3 Punkte nötig"; Sketch.renderAll(); return Promise.resolve(); }
    return queue(async () => {
      const before = JSON.stringify(SK.sk);
      const { data } = await api("/api/sketch/solve", request({ points, constraints: [] }));
      if (!data.sketch || data.state === "invalid") { SK.msg = (errorsOf(data).length ? errorsOf(data) : ["Ungültige Kontur"]).join(" "); Sketch.renderAll(); return; }
      skPushHistory(before);
      apply(data);
      SK.msg = "";
      skClearSelection();
      sync();
      Sketch.renderAll();
    });
  }

  /** Verlauf. from und to sind SK.hist und SK.redo (oder umgekehrt). */
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

  /** Neu loesen mit der aktuellen Skizze (z.B. nach geaendertem Achsabstand). */
  function resolve() {
    return queue(async () => {
      apply(await callSolve());
      sync();
      Sketch.renderAll();
    });
  }

  /** Rechteck aus den Motordaten als neue Skizze (rueckgaengig machbar). */
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

  // --- Abgleich mit der Konfiguration ------------------------------------------------------------------
  let syncTimer = null;
  /** Uebernimmt eine gueltige Skizze in cfg.motor (Breite und Tiefe aus der Bounding Box). */
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

  /** Laedt die Skizze aus cfg (oder das Rechteck des Motors als Vorschau). Nur der neueste Aufruf zaehlt. */
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
    if (mine !== reloadSeq || !sketch) return;  // inzwischen neu geladen
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

  /** Skizze verwerfen, zurueck zum Rechteck des Motors. */
  function drop() {
    cfg.motor.sketch = null;
    SK.attached = false;
    writeInputs();
    refresh();
    reload();
  }

  // --- Ziehen eines Punktes (gedrosselt, die letzte Position gewinnt) ------------------------------------
  // Der Ziehvorgang wird mitgegeben, weil SK.drag beim Loslassen schon null sein kann, waehrend die letzte
  // Antwort noch unterwegs ist. dragRun erlaubt dem Loslassen, auf sie zu warten.
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
