"use strict";
// Motor sketch. Drawing tools like Onshape. Line (chain), rectangle, circle, arc and gear. While drawing the
// clicks snap to points and curves (coincident) and nearly horizontal or vertical lines get the relation.

(() => {
  /** Active tool. Drawing tools start a new draft, relation and dimension tools collect clicks. */
  function setTool(tool) {
    SK.tool = tool;
    SK.draft = null;
    SK.pick = [];
    SK.dimPlace = null;
    $("#skInput").hidden = true;
    Sketch.renderAll();
  }

  /** Add a point to the sketch copy and return its index. */
  function addPoint(sk, x, y) {
    sk.points.push([x, y]);
    return sk.points.length - 1;
  }

  function addEntity(sk, type, points, extra = {}) {
    sk.entities.push({ type, points, radius: null, construction: false, role: "", ...extra });
    return sk.entities.length - 1;
  }

  /** Coincident relation of a new point with the reference it snapped to (point, origin or curve). */
  function snapConstraint(sk, pointIndex, snap) {
    if (snap && snap.ref) sk.constraints.push(makeConstraint("coincident", [`p${pointIndex}`, snap.ref]));
  }

  /** Line from click a to click b with its inferred relations. Returns the entity index. */
  function addLine(sk, a, b, role = "") {
    const pa = addPoint(sk, a.x, a.y), pb = addPoint(sk, b.x, b.y);
    const k = addEntity(sk, "line", [pa, pb], { role });
    snapConstraint(sk, pa, a.snap);
    snapConstraint(sk, pb, b.snap);
    const axis = Sketch.axisInference([a.x, a.y], [b.x, b.y]);
    if (axis) sk.constraints.push(makeConstraint(axis, [`e${k}`]));
    return k;
  }

  /** Rectangle from two corners. Four lines, coincident corners, horizontal and vertical sides. */
  function addRectangle(sk, a, b, role = "") {
    const corners = [[a.x, a.y], [b.x, a.y], [b.x, b.y], [a.x, b.y]];
    const lines = corners.map((c, i) => {
      const d = corners[(i + 1) % 4];
      return addEntity(sk, "line", [addPoint(sk, c[0], c[1]), addPoint(sk, d[0], d[1])], { role });
    });
    lines.forEach((k, i) => {
      const next = lines[(i + 1) % 4];
      sk.constraints.push(makeConstraint("coincident", [`p${sk.entities[k].points[1]}`, `p${sk.entities[next].points[0]}`]));
    });
    ["horizontal", "vertical", "horizontal", "vertical"].forEach((t, i) => sk.constraints.push(makeConstraint(t, [`e${lines[i]}`])));
    snapConstraint(sk, sk.entities[lines[0]].points[0], a.snap);
    snapConstraint(sk, sk.entities[lines[1]].points[1], b.snap);
    return lines;
  }

  /** Gear. Rectangle (role gear), construction diagonal and centre point on the x axis (like the core). */
  function addGear(sk, a, b) {
    const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), h = Math.max(Math.abs(b.y - a.y) / 2, 0.5);
    const lines = addRectangle(sk, { x: x0, y: -h }, { x: x1, y: h }, "gear");
    const diag = addEntity(sk, "line", [addPoint(sk, x0, -h), addPoint(sk, x1, h)], { construction: true, role: "gear" });
    sk.constraints.push(makeConstraint("coincident", [`p${sk.entities[diag].points[0]}`, `p${sk.entities[lines[0]].points[0]}`]));
    sk.constraints.push(makeConstraint("coincident", [`p${sk.entities[diag].points[1]}`, `p${sk.entities[lines[2]].points[0]}`]));
    const centre = addEntity(sk, "point", [addPoint(sk, (x0 + x1) / 2, 0)], { role: "gear" });
    sk.constraints.push(makeConstraint("midpoint", [`e${centre}`, `e${diag}`]));
    sk.constraints.push(makeConstraint("horizontal", [`e${centre}`, "o"]));
  }

  const hasGear = () => SK.sk.entities.some((e) => e.role === "gear");

  /** A click of a drawing tool at the mouse position p (mm). */
  function drawClick(p) {
    const snap = SK.snap || Sketch.infer(p);
    const click = { x: snap.x, y: snap.y, snap: snap.ref ? snap : null };
    const tool = SK.tool;
    if (tool === "gear" && !SK.draft && hasGear()) { SK.msg = t("ui.sk.gear_exists"); Sketch.renderAll(); return; }
    if (!SK.draft) { SK.draft = { tool, clicks: [click] }; Sketch.render(); return; }
    const draft = SK.draft;
    const first = draft.clicks[0], last = draft.clicks[draft.clicks.length - 1];
    if (tool === "line") {
      if (Math.hypot(click.x - last.x, click.y - last.y) < SK_EPS) { finishDraft(); return; }
      const closes = draft.clicks.length > 1 && Math.hypot(click.x - first.x, click.y - first.y) < SK_SNAP_PX * SK.view.k;
      // Commits run one after another, so the chain is read when this line is really added
      Sketch.commit((sk) => {
        const chainEnd = draft.lastLine;
        const start = { ...last, snap: chainEnd !== undefined ? null : last.snap };
        const end = closes ? { ...first, snap: null } : click;
        const k = addLine(sk, start, end);
        if (chainEnd !== undefined) sk.constraints.push(makeConstraint("coincident", [`p${sk.entities[k].points[0]}`, `p${sk.entities[chainEnd].points[1]}`]));
        if (closes) sk.constraints.push(makeConstraint("coincident", [`p${sk.entities[k].points[1]}`, `p${sk.entities[draft.firstLine ?? k].points[0]}`]));
        draft.lastLine = k;
        if (draft.firstLine === undefined) draft.firstLine = k;
      });
      if (closes) { SK.draft = null; return; }
      draft.clicks.push({ ...click, snap: null });
      return;
    }
    if (tool === "arc" && draft.clicks.length === 1) { draft.clicks.push(click); Sketch.render(); return; }
    SK.draft = null;
    Sketch.commit((sk) => {
      if (tool === "rect") addRectangle(sk, first, click);
      else if (tool === "gear") addGear(sk, first, click);
      else if (tool === "circle") {
        const c = addPoint(sk, first.x, first.y);
        addEntity(sk, "circle", [c], { radius: Math.max(Math.hypot(click.x - first.x, click.y - first.y), 0.1) });
        snapConstraint(sk, c, first.snap);
      } else if (tool === "arc") {
        const s = draft.clicks[1], r = Math.max(Math.hypot(s.x - first.x, s.y - first.y), 0.1);
        const a1 = Math.atan2(click.y - first.y, click.x - first.x);
        const c = addPoint(sk, first.x, first.y), ps = addPoint(sk, s.x, s.y), pe = addPoint(sk, first.x + r * Math.cos(a1), first.y + r * Math.sin(a1));
        addEntity(sk, "arc", [c, ps, pe]);
        snapConstraint(sk, c, first.snap);
        snapConstraint(sk, ps, s.snap);
      }
    });
  }

  /** End the line chain (double click, Enter or Esc). */
  function finishDraft() {
    SK.draft = null;
    Sketch.render();
  }

  Object.assign(Sketch, { setTool, drawClick, finishDraft, hasGear });
})();
