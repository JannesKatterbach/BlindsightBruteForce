"use strict";
// Motor Skizze. Verdrahtung der Bedienelemente und Schnittstelle zur restlichen Oberflaeche.

(() => {
  function initSketch() {
    Sketch.initCanvas();
    // Waehrend Tabellen neu gebaut werden, feuert der Browser change fuer entfernte Felder
    for (const id of ["#skSides", "#skPoints", "#skCons"]) {
      $(id).addEventListener("change", (e) => { if (SK.rendering) e.stopImmediatePropagation(); }, true);
    }
    $$("[data-sk-add]").forEach((b) => b.addEventListener("click", () => Sketch.addConstraint(b.dataset.skAdd)));
    $("#skDraw").addEventListener("click", () => { SK.tool = SK.tool === "draw" ? null : "draw"; SK.drawPts = []; Sketch.renderAll(); });
    $("#skFromMotor").addEventListener("click", () => Sketch.fromMotor());
    $("#skHull").addEventListener("click", () => Sketch.structural("hull", {}));
    $("#skUndo").addEventListener("click", () => Sketch.undo());
    $("#skRedo").addEventListener("click", () => Sketch.redo());
    $("#skFit").addEventListener("click", () => { Sketch.fit(); Sketch.render(); });
    $("#skZoomIn").addEventListener("click", () => Sketch.zoom(1 / 1.25));
    $("#skZoomOut").addEventListener("click", () => Sketch.zoom(1.25));
    $("#skRot").addEventListener("input", () => { SK.rot = +$("#skRot").value; $("#skRotVal").textContent = SK.rot; Sketch.render(); });
    for (const id of ["#skSweep", "#skShowMeasures", "#skSnap"]) $(id).addEventListener("change", () => Sketch.render());
    $("#skDrop").addEventListener("click", () => Sketch.drop());
    initCenterDistance();
    const renderIfVisible = () => { if ($("#tab-sketch").classList.contains("active")) Sketch.render(); };
    window.addEventListener("resize", renderIfVisible);
    new ResizeObserver(renderIfVisible).observe($("#skCanvasWrap"));
  }

  function initCenterDistance() {
    $("#skCd").innerHTML = '<label>Achsabstand Zahnrad zu Stange</label><input id="skCdIn" type="number" step="any" min="0">';
    $("#skCdIn").addEventListener("change", () => {
      const v = parseFloat($("#skCdIn").value);
      if (!(v >= 0)) return;
      cfg.motor.center_distance = v;
      writeInputs();
      Sketch.resolve();
    });
  }

  // Schnittstelle fuer main.js, motor.js und Tests
  window.initSketch = initSketch;
  window.skReload = () => Sketch.reload();
  window.skRender = () => Sketch.renderAll();
  window.skSelect = (points, sides) => { SK.sel = { p: new Set(points), s: new Set(sides) }; Sketch.renderAll(); };
  window.skAdd = (tool) => Sketch.addConstraint(tool);
})();
