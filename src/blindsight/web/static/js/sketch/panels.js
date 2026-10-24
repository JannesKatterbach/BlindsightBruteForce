"use strict";
// Motor Skizze. Constraint Liste, Tabellen der Seiten und Punkte, Statuszeile.

(() => {
  const STATUS_DOTS = { ok: "●", conflict: "✖", redundant: "◐", disabled: "○" };
  const STATE_TEXT = {
    under: (r) => `Unterbestimmt, ${r.dof} Freiheitsgrade`, full: () => "Voll bestimmt", over: () => "Überbestimmt (redundante Constraints)",
    conflict: () => "Widerspruch in den Constraints", invalid: () => "Ungültige Skizze",
  };
  const STATE_COLORS = { under: SK_COLORS.ok, full: SK_COLORS.full, over: SK_COLORS.redundant, conflict: SK_COLORS.conflict, invalid: SK_COLORS.conflict };

  // Kurzschreibweise je Typ. Fehlt ein Eintrag, entsteht der Text aus dem Schema (Bezeichnung und Bezuege)
  const side = (i) => `S${i + 1}`, pt = (i) => `P${i + 1}`;
  const refName = (c) => (c.ref === "gear" ? "Zahnrad" : "Stange");
  const CONSTRAINT_TEXT = {
    length: (c) => `Länge ${side(c.a)}`, angle: (c) => `Winkel ${pt(c.a)}`, angle_sides: (c) => `Winkel ${side(c.a)} / ${side(c.b)}`,
    parallel: (c) => `${side(c.a)} ∥ ${side(c.b)}`, perpendicular: (c) => `${side(c.a)} ⊥ ${side(c.b)}`, equal: (c) => `${side(c.a)} = ${side(c.b)}`,
    horizontal: (c) => `${side(c.a)} horizontal`, vertical: (c) => `${side(c.a)} vertikal`, fix: (c) => `${pt(c.a)} fixiert`,
    coord_x: (c) => `x von ${pt(c.a)}`, coord_y: (c) => `y von ${pt(c.a)}`,
    dist_point: (c) => `Abstand ${pt(c.a)} zu ${refName(c)}`, dist_side: (c) => `Abstand ${side(c.a)} zu ${refName(c)}`,
  };

  /** Beschreibung des Typs aus /api/schema (Felder fuer Seiten und Punkte, Werteart). */
  const constraintType = (name) => (schema.sketch_constraints || []).find((t) => t.name === name);

  function constraintText(c) {
    if (CONSTRAINT_TEXT[c.type]) return CONSTRAINT_TEXT[c.type](c);
    const type = constraintType(c.type);
    if (!type) return c.type;
    const refs = type.sides.map((f) => side(c[f])).concat(type.points.map((f) => pt(c[f])));
    return `${type.label} ${refs.join(" / ")}`;
  }

  /** Werteart des einen bearbeitbaren Zahlenwerts ("len" oder "deg"), null ohne solchen Wert. */
  function valueKind(c) {
    const type = constraintType(c.type);
    return type && type.value && !type.value2 ? type.value : null;
  }

  /** Seiten und Punkte, auf die sich ein Constraint bezieht (zum Hervorheben). */
  function references(c) {
    const type = constraintType(c.type);
    if (!type) return { sides: [], points: [] };
    return { sides: type.sides.map((f) => c[f]).filter((x) => x != null), points: type.points.map((f) => c[f]).filter((x) => x != null) };
  }

  function highlight(sides = [], points = []) {
    SK.hover = sides.length || points.length ? { sides, points } : null;
    Sketch.render();
  }

  // Aenderungen an Werten in der Anzeigeeinheit (Laengen) oder in Grad
  const toValue = (kind, v) => (kind === "len" ? fromU(v) : v);
  const showValue = (kind, v) => (kind === "len" ? fmtLen(v) : fmtDeg(v));

  /** Waehrend Tabellen neu gebaut werden, feuert der Browser change fuer entfernte Felder. Das ignorieren. */
  function rebuild(box, html) {
    SK.rendering = true;
    box.innerHTML = html;
    queueMicrotask(() => { SK.rendering = false; });
  }

  function renderConstraints() {
    const box = $("#skCons");
    rebuild(box, "");
    if (!SK.sk.constraints.length) {
      box.innerHTML = '<p class="hint">Noch keine Constraints. Seiten oder Punkte wählen und ein Werkzeug anklicken, oder Werte in den Tabellen eingeben.</p>';
      return;
    }
    SK.sk.constraints.forEach((c, k) => box.appendChild(constraintRow(c, k)));
  }

  function constraintRow(c, k) {
    const status = constraintStatus(k);
    const row = document.createElement("div");
    row.className = "skcons " + status;
    row.dataset.skCons = k;
    const message = (SK.res && SK.res.constraints[k] && SK.res.constraints[k].message) || status;
    row.innerHTML = `<span class="dot" title="${esc(message)}">${STATUS_DOTS[status] || STATUS_DOTS.ok}</span><span class="lbl">${esc(c.name || constraintText(c))}</span>`;
    const kind = valueKind(c);
    if (kind) {
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.className = "skval";
      input.value = showValue(kind, c.value);
      input.dataset.skConsVal = k;
      input.addEventListener("change", () => {
        const v = parseFloat(input.value);
        if (Number.isFinite(v)) Sketch.commit((s) => { s.constraints[k].value = toValue(kind, v); });
      });
      row.appendChild(input);
    }
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = c.enabled;
    enabled.title = "Aktiv";
    enabled.addEventListener("change", () => Sketch.commit((s) => { s.constraints[k].enabled = enabled.checked; }));
    const remove = document.createElement("button");
    remove.textContent = "×";
    remove.title = "Constraint löschen";
    remove.dataset.skConsDel = k;
    remove.addEventListener("click", () => Sketch.commit((s) => { s.constraints.splice(k, 1); }));
    row.append(enabled, remove);
    const refs = references(c);
    row.addEventListener("mouseenter", () => highlight(refs.sides, refs.points));
    row.addEventListener("mouseleave", () => highlight());
    return row;
  }

  /** Constraint vom Typ type, der match erfuellt, aendern oder neu anlegen. */
  function upsert(sketch, type, match, fields) {
    const idx = sketch.constraints.findIndex((c) => c.type === type && match(c));
    if (idx >= 0) Object.assign(sketch.constraints[idx], fields);
    else sketch.constraints.push(makeConstraint(type, fields));
  }

  const hasConstraint = (type, i) => SK.sk.constraints.some((c) => c.type === type && c.a === i);
  const hasEnabled = (type, i) => SK.sk.constraints.some((c) => c.type === type && c.enabled && c.a === i);

  function currentMeasures() {
    if (SK.res && SK.res.measures) return SK.res.measures;
    const indices = [...Array(skCount()).keys()];
    return { sides: indices.map(Sketch.sideLen), angles: indices.map(Sketch.interiorAngle) };
  }

  function renderTables() {
    const measures = currentMeasures();
    rebuild($("#skSides"), sidesTable(measures));
    rebuild($("#skPoints"), pointsTable(measures));
    bindSideTable();
    bindPointTable();
  }

  function sidesTable(measures) {
    let html = `<table class="grid"><tr><th>Seite</th><th>Länge [${unit}]</th><th>parallel zu</th><th>H</th><th>V</th></tr>`;
    for (let i = 0; i < skCount(); i++) {
      const parallel = SK.sk.constraints.find((c) => c.type === "parallel" && c.enabled && (c.a === i || c.b === i));
      const partner = parallel ? (parallel.a === i ? parallel.b : parallel.a) : null;
      const options = ['<option value="">—</option>'].concat([...Array(skCount()).keys()].filter((j) => j !== i)
        .map((j) => `<option value="${j}" ${partner === j ? "selected" : ""}>S${j + 1}</option>`)).join("");
      html += `<tr class="${SK.sel.s.has(i) ? "sel" : ""}" data-row-side="${i}"><td>S${i + 1}</td>
        <td><input type="number" step="any" class="${hasConstraint("length", i) ? "driven" : ""}" data-sk-len="${i}" value="${fmtLen(measures.sides[i])}"></td>
        <td><select data-sk-par="${i}">${options}</select></td>
        <td><input type="checkbox" data-sk-hv="horizontal:${i}" ${hasEnabled("horizontal", i) ? "checked" : ""}></td>
        <td><input type="checkbox" data-sk-hv="vertical:${i}" ${hasEnabled("vertical", i) ? "checked" : ""}></td></tr>`;
    }
    return html + "</table>";
  }

  function pointsTable(measures) {
    let html = `<table class="grid"><tr><th>Punkt</th><th>x [${unit}]</th><th>y [${unit}]</th><th>Winkel °</th><th></th></tr>`;
    for (let i = 0; i < skCount(); i++) {
      const q = Sketch.point(i), fixed = hasConstraint("fix", i);
      const driven = (type) => (hasConstraint(type, i) || (type !== "angle" && fixed) ? "driven" : "");
      html += `<tr class="${SK.sel.p.has(i) ? "sel" : ""}" data-row-point="${i}"><td>P${i + 1}</td>
        <td><input type="number" step="any" class="${driven("coord_x")}" data-sk-x="${i}" value="${fmtLen(q[0])}"></td>
        <td><input type="number" step="any" class="${driven("coord_y")}" data-sk-y="${i}" value="${fmtLen(q[1])}"></td>
        <td><input type="number" step="any" class="${driven("angle")}" data-sk-ang="${i}" value="${fmtDeg(measures.angles[i])}"></td>
        <td><button data-sk-fix="${i}" title="Fixieren">${fixed ? "gelöst" : "fix"}</button><button data-sk-del="${i}" title="Punkt löschen">×</button></td></tr>`;
    }
    return html + "</table>";
  }

  /** Feld mit Zahlenwert. onValue erhaelt Index und Zahl, nur fuer endliche Zahlen. */
  function onNumber(selector, attr, onValue) {
    $$(selector).forEach((input) => input.addEventListener("change", () => {
      const v = parseFloat(input.value);
      if (Number.isFinite(v)) onValue(+input.dataset[attr], v);
    }));
  }

  /** Klick auf eine Zeile (nicht auf ein Feld) waehlt die Seite oder den Punkt aus. */
  function onRowClick(selector, attr, kind) {
    $$(selector).forEach((row) => row.addEventListener("click", (ev) => {
      if (ev.target.tagName === "TR" || ev.target.tagName === "TD") Sketch.select(kind, +row.dataset[attr], ev.shiftKey);
    }));
  }

  function bindSideTable() {
    onNumber("#skSides [data-sk-len]", "skLen", (i, v) => { if (v > 0) Sketch.commit((s) => upsert(s, "length", (c) => c.a === i, { a: i, value: fromU(v) })); });
    $$("#skSides [data-sk-par]").forEach((select) => select.addEventListener("change", () => {
      const i = +select.dataset.skPar, j = select.value === "" ? null : +select.value;
      Sketch.commit((s) => {
        s.constraints = s.constraints.filter((c) => !(c.type === "parallel" && (c.a === i || c.b === i)));
        if (j !== null) s.constraints.push(makeConstraint("parallel", { a: i, b: j }));
      });
    }));
    $$("#skSides [data-sk-hv]").forEach((box) => box.addEventListener("change", () => {
      const [type, index] = box.dataset.skHv.split(":"), i = +index;
      Sketch.commit((s) => {
        s.constraints = s.constraints.filter((c) => !(c.type === type && c.a === i));
        if (box.checked) s.constraints.push(makeConstraint(type, { a: i }));
      });
    }));
    onRowClick("#skSides [data-row-side]", "rowSide", "s");
  }

  function bindPointTable() {
    onNumber("#skPoints [data-sk-x]", "skX", (i, v) => Sketch.commit((s) => upsert(s, "coord_x", (c) => c.a === i, { a: i, value: fromU(v) })));
    onNumber("#skPoints [data-sk-y]", "skY", (i, v) => Sketch.commit((s) => upsert(s, "coord_y", (c) => c.a === i, { a: i, value: fromU(v) })));
    onNumber("#skPoints [data-sk-ang]", "skAng", (i, v) => { if (v > 0 && v < 180) Sketch.commit((s) => upsert(s, "angle", (c) => c.a === i, { a: i, value: v })); });
    $$("#skPoints [data-sk-fix]").forEach((button) => button.addEventListener("click", () => {
      const i = +button.dataset.skFix;
      Sketch.commit((s) => {
        const idx = s.constraints.findIndex((c) => c.type === "fix" && c.a === i);
        if (idx >= 0) s.constraints.splice(idx, 1);
        else s.constraints.push(makeConstraint("fix", { a: i, value: s.points[i][0], value2: s.points[i][1] }));
      });
    }));
    $$("#skPoints [data-sk-del]").forEach((button) => button.addEventListener("click", () => Sketch.deletePoint(+button.dataset.skDel)));
    onRowClick("#skPoints [data-row-point]", "rowPoint", "p");
  }

  function renderStatus() {
    const r = SK.res, box = $("#skStatus");
    if (!r) { box.textContent = ""; return; }
    const stateText = STATE_TEXT[r.state] ? STATE_TEXT[r.state](r) : r.state;
    const items = [`<b style="color:${STATE_COLORS[r.state]}">${esc(stateText)}</b>`, r.convex ? "Kontur konvex" : '<b style="color:var(--bad)">Kontur nicht konvex</b>'];
    for (const m of [...(r.errors || []), ...(r.warnings || [])]) items.push(`<span style="color:var(--bad)">${esc(m)}</span>`);
    const clearance = skCount() >= 3 ? Sketch.housingClearance() : 0;
    if (clearance < cfg.motor.own_clearance - SK_EPS) {
      items.push(`<span style="color:var(--bad)">Gehäuse zu nah an der Stange (${fmtLen(Math.max(0, clearance))} ${unit}, benötigt ${fmtLen(cfg.motor.own_clearance)} ${unit})</span>`);
    }
    if (SK.msg) items.push(`<span style="color:var(--bad)">${esc(SK.msg)}</span>`);
    if (!SK.attached) items.push("Vorschau des aktuellen Motors. Die erste Änderung übernimmt die Skizze in die Konfiguration.");
    box.innerHTML = items.join(" · ");
    box.className = "statusBox" + (r.state === "conflict" || !r.convex || (r.errors || []).length ? " warn" : "");
    $("#skUndo").disabled = !SK.hist.length;
    $("#skRedo").disabled = !SK.redo.length;
    $$("[data-sk-add]").forEach((b) => { b.disabled = !Sketch.canAdd(b.dataset.skAdd); });
    $("#skDraw").classList.toggle("primary", SK.tool === "draw");
    const cdInput = $("#skCdIn");
    if (cdInput && document.activeElement !== cdInput) cdInput.value = fmtLen(cfg.motor.center_distance);
  }

  function renderAll() {
    Sketch.render();
    renderConstraints();
    renderTables();
    renderStatus();
  }

  Object.assign(Sketch, { constraintText, valueKind, upsert, renderStatus, renderAll });
})();
