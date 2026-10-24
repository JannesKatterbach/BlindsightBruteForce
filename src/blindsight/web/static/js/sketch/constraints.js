"use strict";
// Motor Skizze. Auswahl, Werkzeuge fuer Constraints und Werteingabe direkt an der Zeichnung.

(() => {
  const counts = () => ({ ps: SK.sel.p.size, ss: SK.sel.s.size });
  const sortedPoints = () => [...SK.sel.p].sort((a, b) => a - b);
  const sortedSides = () => [...SK.sel.s].sort((a, b) => a - b);

  // Werkzeug -> {can: passt die Auswahl?, run: Constraint anlegen}. Ein neues Werkzeug ist ein Eintrag hier
  // und ein Knopf mit data-sk-add in index.html. Typen und Werte kennt der Kern (CONSTRAINT_TYPES).
  const TOOLS = {
    length: { can: ({ ps, ss }) => ss === 1 || (ps === 2 && !ss && Sketch.adjacentSide(sortedPoints()) !== null), run: addLength },
    angle: { can: ({ ps, ss }) => (ps === 1 && !ss) || (ss === 2 && !ps), run: addAngle },
    parallel: { can: ({ ps, ss }) => ss === 2 && !ps, run: () => addPair("parallel") },
    perpendicular: { can: ({ ps, ss }) => ss === 2 && !ps, run: () => addPair("perpendicular") },
    equal: { can: ({ ps, ss }) => ss === 2 && !ps, run: () => addPair("equal") },
    horizontal: { can: ({ ps, ss }) => ss >= 1 && !ps, run: () => addPerSide("horizontal") },
    vertical: { can: ({ ps, ss }) => ss >= 1 && !ps, run: () => addPerSide("vertical") },
    fix: { can: ({ ps, ss }) => ps >= 1 && !ss, run: addFix },
    dist_rod: { can: ({ ps, ss }) => (ps === 1 && !ss) || (ss === 1 && !ps), run: () => addDistance("rod") },
    dist_gear: { can: ({ ps, ss }) => (ps === 1 && !ss) || (ss === 1 && !ps), run: () => addDistance("gear") },
  };

  function select(kind, i, additive) {
    const before = kind === "p" ? SK.sel.p : SK.sel.s;
    const wasSelected = before.has(i);
    if (!additive) skClearSelection();
    const target = kind === "p" ? SK.sel.p : SK.sel.s;
    if (additive && wasSelected) target.delete(i);
    else target.add(i);
    Sketch.renderAll();
  }

  const canAdd = (tool) => !!TOOLS[tool] && TOOLS[tool].can(counts());

  function addConstraint(tool) {
    if (canAdd(tool)) TOOLS[tool].run();
  }

  /** Eingabefeld an der Stelle at (mm) der Zeichnung. Enter uebernimmt, Esc oder Verlassen bricht ab. */
  function askValue(label, initial, at, onValue) {
    const input = $("#skInput"), v = SK.view, [W, H] = Sketch.canvasSize();
    const sx = (at[0] - v.cx) / v.k + W / 2, sy = -(at[1] - v.cy) / v.k + H / 2;
    input.hidden = false;
    input.value = initial;
    input.title = label;
    input.placeholder = label;
    input.style.left = Math.max(4, Math.min(W - 110, sx - 45)) + "px";
    input.style.top = Math.max(4, Math.min(H - 30, sy - 12)) + "px";
    input.focus();
    input.select();
    const done = (accept) => {
      input.hidden = true;
      input.onkeydown = null;
      input.onblur = null;
      if (!accept) return;
      const value = parseFloat(String(input.value).replace(",", "."));
      if (Number.isFinite(value)) onValue(value);
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); done(true); } else if (e.key === "Escape") { e.preventDefault(); done(false); }
    };
    input.onblur = () => done(false);
  }

  function addLength() {
    const sides = sortedSides();
    const i = sides.length ? sides[0] : Sketch.adjacentSide(sortedPoints());
    askValue(`Länge S${i + 1} [mm]`, fmtLen(Sketch.sideLen(i)), Sketch.sideMid(i), (v) => {
      if (v > 0) Sketch.commit((s) => Sketch.upsert(s, "length", (c) => c.a === i, { a: i, value: v }));
    });
  }

  function addAngle() {
    const points = sortedPoints();
    if (points.length === 1) {
      const i = points[0];
      askValue(`Winkel P${i + 1} [Grad]`, fmtDeg(Sketch.interiorAngle(i)), Sketch.point(i), (v) => {
        if (v > 0 && v < 180) Sketch.commit((s) => Sketch.upsert(s, "angle", (c) => c.a === i, { a: i, value: v }));
      });
      return;
    }
    const [a, b] = sortedSides();
    askValue(`Winkel S${a + 1} / S${b + 1} [Grad]`, fmtDeg(Sketch.angleBetweenSides(a, b)), Sketch.sideMid(a), (v) => {
      if (v >= 0 && v <= 180) Sketch.commit((s) => Sketch.upsert(s, "angle_sides", (c) => c.a === a && c.b === b, { a, b, value: v }));
    });
  }

  function addPair(type) {
    const [a, b] = sortedSides();
    const exists = SK.sk.constraints.some((c) => c.type === type && ((c.a === a && c.b === b) || (c.a === b && c.b === a)));
    if (exists) { SK.msg = "Diese Beziehung existiert bereits."; Sketch.renderAll(); return; }
    Sketch.commit((s) => s.constraints.push(makeConstraint(type, { a, b })));
  }

  function addPerSide(type) {
    const sides = sortedSides();
    Sketch.commit((s) => sides.forEach((i) => {
      if (!s.constraints.some((c) => c.type === type && c.a === i)) s.constraints.push(makeConstraint(type, { a: i }));
    }));
  }

  function addFix() {
    const points = sortedPoints();
    Sketch.commit((s) => points.forEach((i) => {
      if (!s.constraints.some((c) => c.type === "fix" && c.a === i)) s.constraints.push(makeConstraint("fix", { a: i, value: s.points[i][0], value2: s.points[i][1] }));
    }));
  }

  function addDistance(ref) {
    const word = ref === "gear" ? "Zahnrad" : "Stange";
    const points = sortedPoints();
    if (points.length === 1) {
      const i = points[0], q = Sketch.point(i), r = Sketch.refPos(ref);
      askValue(`Abstand P${i + 1} zu ${word} [mm]`, fmtLen(Math.hypot(q[0] - r[0], q[1] - r[1])), q, (v) => {
        if (v >= 0) Sketch.commit((s) => Sketch.upsert(s, "dist_point", (c) => c.a === i && c.ref === ref, { a: i, ref, value: v }));
      });
      return;
    }
    const i = sortedSides()[0];
    askValue(`Abstand S${i + 1} zu ${word} [mm]`, fmtLen(Sketch.distanceSideRef(i, ref)), Sketch.sideMid(i), (v) => {
      if (v >= 0) Sketch.commit((s) => Sketch.upsert(s, "dist_side", (c) => c.a === i && c.ref === ref, { a: i, ref, value: v }));
    });
  }

  /** Klick auf ein Mass. Laenge und Winkel legen einen Constraint an, vorhandene Werte werden bearbeitet. */
  function openDimension(key) {
    const [kind, index] = key.split(":"), i = +index;
    if (kind === "length") { SK.sel = { p: new Set(), s: new Set([i]) }; Sketch.renderAll(); addConstraint("length"); return; }
    if (kind === "angle") { SK.sel = { p: new Set([i]), s: new Set() }; Sketch.renderAll(); addConstraint("angle"); return; }
    const c = SK.sk.constraints[i], valueKind = Sketch.valueKind(c);
    if (kind !== "cons" || !valueKind) return;
    const at = c.type === "dist_point" ? Sketch.point(c.a) : Sketch.sideMid(c.a ?? 0);
    askValue(Sketch.constraintText(c), valueKind === "len" ? fmtLen(c.value) : fmtDeg(c.value), at, (v) => {
      Sketch.commit((s) => { s.constraints[i].value = valueKind === "len" ? v : v; });
    });
  }

  Object.assign(Sketch, { select, canAdd, addConstraint, openDimension });
})();
