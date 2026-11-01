"use strict";
// Motor sketch. Wiring of the toolbar and interface to the rest of the UI.

(() => {
  const ACTIONS = {
    construction: () => Sketch.toggleConstruction(),
    undo: () => Sketch.undo(),
    redo: () => Sketch.redo(),
    delete: () => Sketch.deleteSelection(),
    fit: () => { Sketch.fit(); Sketch.render(); },
    list: () => { SK.showList = !SK.showList; Sketch.renderAll(); },
  };

  function initSketch() {
    Sketch.initToolbar();
    Sketch.initCanvas();
    // While the list is rebuilt, the browser fires change for removed fields
    $("#skCons").addEventListener("change", (e) => { if (SK.rendering) e.stopImmediatePropagation(); }, true);
    $$("#skToolbar [data-sk-tool]").forEach((b) => b.addEventListener("click", () => Sketch.setTool(b.dataset.skTool)));
    $$("#skToolbar [data-sk-rel]").forEach((b) => b.addEventListener("click", () => Sketch.relation(b.dataset.skRel)));
    $$("#skToolbar [data-sk-act]").forEach((b) => b.addEventListener("click", () => ACTIONS[b.dataset.skAct]()));
    $("#skRot").addEventListener("input", () => { SK.rot = +$("#skRot").value; $("#skRotVal").textContent = SK.rot; Sketch.render(); });
    for (const id of ["#skSweep", "#skShowHull", "#skSnap"]) $(id).addEventListener("change", () => Sketch.render());
    $("#skDrop").addEventListener("click", () => { if (confirm(t("ui.confirm.drop_sketch"))) Sketch.drop(); });
    const renderIfVisible = () => { if ($("#tab-sketch").classList.contains("active")) Sketch.render(); };
    window.addEventListener("resize", renderIfVisible);
    new ResizeObserver(renderIfVisible).observe($("#skCanvasWrap"));
  }

  // Interface for main.js, motor.js and tests
  window.initSketch = initSketch;
  window.skReload = () => Sketch.reload();
  window.skRender = () => Sketch.renderAll();
  window.skSelect = (refs) => { SK.sel = new Set(refs); Sketch.renderAll(); };
  window.skRelation = (type) => Sketch.relation(type);
  // After a language switch. Solve again so that the messages of the solver come in the new language
  window.skRelocalize = async () => { if (SK.sk.entities.length) await Sketch.resolve(); else Sketch.renderAll(); };
})();
