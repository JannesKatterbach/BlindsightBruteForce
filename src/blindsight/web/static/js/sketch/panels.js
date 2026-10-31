"use strict";
// Motor sketch. Toolbar (icons, active tool), status line and the foldable list of relations and dimensions.

(() => {
  // Icons of the toolbar (24 x 24, drawn with the text colour)
  const ICONS = {
    select: '<path d="M5 3l12 9-6 1 3 7-2 1-3-7-4 4z"/>',
    line: '<path d="M4 20L20 4"/><circle cx="4" cy="20" r="1.8"/><circle cx="20" cy="4" r="1.8"/>',
    rect: '<rect x="4" y="6" width="16" height="12"/>',
    circle: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="1"/>',
    arc: '<path d="M4 17A9 9 0 0 1 20 17"/><circle cx="12" cy="17" r="1"/>',
    gear: '<rect x="5" y="8" width="14" height="8"/><path d="M7 8v-2M10 8v-2M13 8v-2M16 8v-2M7 16v2M10 16v2M13 16v2M16 16v2"/>',
    construction: '<path d="M4 20L20 4" stroke-dasharray="3 3"/>',
    dimension: '<path d="M4 8v10M20 8v10M4 13h16"/><path d="M7 10l-3 3 3 3M17 10l3 3-3 3"/>',
    coincident: '<circle cx="12" cy="12" r="4"/><path d="M4 12h4M16 12h4"/>',
    horizontal: '<path d="M4 12h16"/><text x="12" y="8" font-size="7" text-anchor="middle" stroke="none" fill="currentColor">H</text>',
    vertical: '<path d="M12 4v16"/><text x="17" y="14" font-size="7" text-anchor="middle" stroke="none" fill="currentColor">V</text>',
    parallel: '<path d="M8 20L14 4M12 20L18 4"/>',
    perpendicular: '<path d="M5 19h14M12 19V5"/>',
    equal: '<path d="M6 9h12M6 15h12"/>',
    midpoint: '<path d="M4 16h16"/><path d="M12 12l3 4-3 4-3-4z"/>',
    concentric: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/>',
    fix: '<rect x="6" y="11" width="12" height="9"/><path d="M8.5 11V8a3.5 3.5 0 0 1 7 0v3"/>',
    undo: '<path d="M9 5L4 10l5 5"/><path d="M4 10h11a5 5 0 0 1 0 10h-3"/>',
    redo: '<path d="M15 5l5 5-5 5"/><path d="M20 10H9a5 5 0 0 0 0 10h3"/>',
    delete: '<path d="M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13"/>',
    fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  };
  const STATUS_DOTS = { ok: "●", conflict: "✖", redundant: "◐", disabled: "○" };
  const STATE_COLORS = { under: SK_COLORS.free, full: "var(--ok)", over: SK_COLORS.redundant, conflict: SK_COLORS.conflict, invalid: SK_COLORS.conflict };

  function initToolbar() {
    for (const button of $$("#skToolbar [data-sk-tool], #skToolbar [data-sk-rel], #skToolbar [data-sk-act]")) {
      const name = button.dataset.skTool || button.dataset.skRel || button.dataset.skAct;
      if (ICONS[name]) button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
    }
  }

  /** Readable name of a reference ("Line 3", "Point 5", "Origin"). */
  function refName(ref) {
    if (ref === "o") return t("ui.sk.name.origin");
    const i = +ref.slice(1);
    if (ref[0] === "p") return t("ui.sk.name.point", { n: i + 1 });
    const e = SK.sk.entities[i];
    const kind = e && e.role === "gear" && e.type !== "line" ? "gear" : e ? e.type : "line";
    return t(`ui.sk.name.${kind}`, { n: i + 1 });
  }

  function constraintText(c) {
    const info = Sketch.typeInfo(c.type);
    return `${info ? info.label : c.type}. ${c.refs.map(refName).join(", ")}`;
  }

  /** Foldable list of all relations and dimensions. Hover highlights, the box switches on and off, × deletes. */
  function renderList() {
    const box = $("#skCons");
    $("#skList").hidden = !SK.showList;
    $("#skListToggle").classList.toggle("active", !!SK.showList);
    if (!SK.showList) return;
    SK.rendering = true;
    box.innerHTML = "";
    if (!SK.sk.constraints.length) box.innerHTML = `<p class="hint">${esc(t("ui.sk.no_constraints"))}</p>`;
    SK.sk.constraints.forEach((c, k) => box.appendChild(listRow(c, k)));
    queueMicrotask(() => { SK.rendering = false; });
  }

  function listRow(c, k) {
    const status = constraintStatus(k);
    const row = document.createElement("div");
    row.className = "skcons " + status + (SK.sel.has(`c${k}`) ? " sel" : "");
    row.dataset.skCons = k;
    const message = (SK.res && SK.res.constraints && SK.res.constraints[k] && SK.res.constraints[k].message) || t("ui.sk.status." + status);
    row.innerHTML = `<span class="dot" title="${esc(message)}">${STATUS_DOTS[status] || STATUS_DOTS.ok}</span><span class="lbl">${esc(c.name || constraintText(c))}</span>`;
    if (c.value !== null && c.value !== undefined) {
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.className = "skval";
      input.value = c.type === "angle" ? fmtDeg(c.value) : fmtLen(c.value);
      input.dataset.skConsVal = k;
      input.addEventListener("change", () => {
        const v = parseFloat(input.value);
        if (Number.isFinite(v)) Sketch.commit((s) => { s.constraints[k].value = v; });
      });
      row.appendChild(input);
    }
    const enabled = document.createElement("input");
    enabled.type = "checkbox";
    enabled.checked = c.enabled;
    enabled.title = t("ui.sk.active");
    enabled.addEventListener("change", () => Sketch.commit((s) => { s.constraints[k].enabled = enabled.checked; }));
    const remove = document.createElement("button");
    remove.textContent = "×";
    remove.title = t("ui.sk.delete_constraint");
    remove.dataset.skConsDel = k;
    remove.addEventListener("click", () => Sketch.commit((s) => { s.constraints.splice(k, 1); }));
    row.append(enabled, remove);
    row.addEventListener("mouseenter", () => { SK.hover = `c${k}`; Sketch.render(); });
    row.addEventListener("mouseleave", () => { SK.hover = null; Sketch.render(); });
    row.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "BUTTON") return;
      SK.sel = new Set([`c${k}`]);
      Sketch.renderAll();
    });
    return row;
  }

  /** Status line under the drawing and the state of the toolbar. */
  function renderStatus() {
    const r = SK.res, box = $("#skStatus");
    const items = [];
    if (r) {
      const stateText = t("ui.sk.state." + r.state, { dof: r.dof });
      items.push(`<b style="color:${STATE_COLORS[r.state] || "inherit"}">${esc(stateText)}</b>`);
      const gear = r.profile && r.profile.gear;
      if (gear) items.push(esc(t("ui.sk.gear_info", { d: fmtLen(gear.diameter), w: fmtLen(gear.width), cd: fmtLen(gear.center_distance) })));
      for (const m of [...(r.errors || []), ...(r.warnings || [])]) items.push(`<span style="color:var(--bad)">${esc(m)}</span>`);
    }
    if (SK.msg) items.push(`<span style="color:var(--bad)">${esc(SK.msg)}</span>`);
    if (!SK.attached) items.push(esc(t("ui.sk.preview")));
    box.innerHTML = items.join(" · ");
    box.className = "statusBox" + (r && (r.state === "conflict" || (r.errors || []).length || (r.warnings || []).length) ? " warn" : "");
    $("#skHint").textContent = t(`ui.sk.hint.${hintKey()}`);
    for (const b of $$("#skToolbar [data-sk-tool]")) b.classList.toggle("active", SK.tool === b.dataset.skTool);
    for (const b of $$("#skToolbar [data-sk-rel]")) b.classList.toggle("armed", SK.tool === b.dataset.skRel);
    $("#skToolbar [data-sk-act=undo]").disabled = !SK.hist.length;
    $("#skToolbar [data-sk-act=redo]").disabled = !SK.redo.length;
    $("#skToolbar [data-sk-act=delete]").disabled = !SK.sel.size;
  }

  function hintKey() {
    if (SK.dimPlace) return "place";
    if (RELATIONS.includes(SK.tool)) return "relation";
    if (SK.tool === "line" && SK.draft) return "line_chain";
    if (SK.tool === "arc" && SK.draft) return SK.draft.clicks.length === 1 ? "arc_start" : "arc_end";
    return SK.tool;
  }

  function renderAll() {
    Sketch.render();
    renderList();
    renderStatus();
  }

  Object.assign(Sketch, { initToolbar, renderList, renderStatus, renderAll, refName, constraintText });
})();
