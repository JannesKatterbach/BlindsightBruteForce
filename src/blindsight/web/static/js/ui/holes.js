"use strict";
// Hole pattern generator. Fixed G0 holes or an own repeating tile, written as a JSON file in the format
// blindsight.holes (see src/blindsight/holes.py). The core checks the holes (/api/holes/check).

const HOLE_FORMAT = "blindsight.holes";
const HOLE_CHECK_DEBOUNCE_MS = 200;
const HOLE_FILL_PATTERNS = ["square", "centered_square", "hex", "staggered"];
const HOLE_FILL_MAX = 5000;
const HOLE_DRAG_PX = 3;
const HOLE_TILE_COPIES = 1;  // copies of the tile shown around it in each direction

const holeState = { mode: "fixed", holes: [], tileHoles: [], problems: [] };
let holeCheckTimer = null;
const holeCheckLatest = latestOnly((body) => api("/api/holes/check", body));

const holeList = () => (holeState.mode === "tile" ? holeState.tileHoles : holeState.holes);
const holeTile = () => ({ width: parseFloat($("#holeTileW").value), height: parseFloat($("#holeTileH").value), scalable: $("#holeTileScalable").checked });

function initHoles() {
  $$("input[name=holeMode]").forEach((r) => r.addEventListener("change", () => { holeState.mode = r.value; holesChanged(); }));
  ["#holeTileW", "#holeTileH", "#holeTileScalable"].forEach((id) => $(id).addEventListener("change", holesChanged));
  $("#holeAdd").addEventListener("click", () => {
    const area = holeArea();
    holeList().push([round(area.width / 2, 3), round(area.height / 2, 3)]);
    holesChanged();
  });
  $("#holeClear").addEventListener("click", () => {
    if (!holeList().length || !confirm(t("ui.confirm.clear_holes"))) return;
    holeList().length = 0;
    holesChanged();
  });
  $("#holePasteAdd").addEventListener("click", () => pasteHoles(false));
  $("#holePasteReplace").addEventListener("click", () => pasteHoles(true));
  $("#holeFillBtn").addEventListener("click", fillHoles);
  $("#holeDownload").addEventListener("click", () => download("blindsight-holes.json", JSON.stringify(holeDocument(), null, 2), "application/json"));
  $("#holeLoad").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    resetFileInput(e.target);
    if (file) await loadHoleFile(file);
  });
  $("#holeUse").addEventListener("click", useHoles);
  initHolePreview();
  buildHoleFillPatterns();
  holesChanged();
}

function buildHoleFillPatterns() {
  const select = $("#holeFillPattern"), current = select.value;
  select.innerHTML = "";
  for (const value of HOLE_FILL_PATTERNS) select.add(new Option(optionLabel("search.pattern", value), value));
  if (current) select.value = current;
}

/** Area the holes live in. The build area for fixed holes, the tile for an own tile. */
function holeArea() {
  if (holeState.mode === "tile") { const tile = holeTile(); return { width: tile.width > 0 ? tile.width : 1, height: tile.height > 0 ? tile.height : 1 }; }
  return { width: cfg.bounds.width, height: cfg.bounds.height };
}

/** Called after every change. Redraw table and preview, check the holes. */
function holesChanged() {
  $("#holeTileBox").hidden = holeState.mode !== "tile";
  renderHoleTable();
  drawHolePreview();
  scheduleHoleCheck();
}

// --- Table -----------------------------------------------------------------------------------------------
function renderHoleTable() {
  const holes = holeList();
  const bad = new Set(holeState.problems.map((p) => p.index));
  const box = $("#holeTable");
  if (!holes.length) { box.innerHTML = emptyTable("ui.holes.empty"); return; }
  let html = `<table class="grid"><tr><th>#</th><th>x [mm]</th><th>y [mm]</th><th></th></tr>`;
  holes.forEach(([x, y], i) => {
    html += `<tr class="${bad.has(i) ? "bad" : ""}"><td>${i + 1}</td>` +
      `<td><input type="number" step="any" data-hole="${i}" data-c="0" value="${esc(round(x, 4))}"></td>` +
      `<td><input type="number" step="any" data-hole="${i}" data-c="1" value="${esc(round(y, 4))}"></td>` +
      `<td>${deleteButton("data-hole-del", i)}</td></tr>`;
  });
  box.innerHTML = html + "</table>";
  $$("[data-hole]", box).forEach((input) => input.addEventListener("change", () => {
    const v = parseFloat(input.value);
    if (!Number.isFinite(v)) return;
    holeList()[+input.dataset.hole][+input.dataset.c] = v;
    drawHolePreview();
    scheduleHoleCheck();
  }));
  $$("[data-hole-del]", box).forEach((button) => button.addEventListener("click", () => { holeList().splice(+button.dataset.holeDel, 1); holesChanged(); }));
}

/** Lines "x;y", "x,y", "x y" or tab separated (Excel). Decimal commas are accepted with ; or tab as separator. */
function parseHoleText(text) {
  const out = [];
  for (const line of String(text).split(/\r?\n/)) {
    const clean = line.trim();
    if (!clean) continue;
    const parts = /[;\t]/.test(clean) ? clean.split(/[;\t]+/).map((s) => s.replace(",", ".")) : clean.split(/[,\s]+/);
    const [x, y] = parts.map((s) => parseFloat(s));
    if (Number.isFinite(x) && Number.isFinite(y)) out.push([x, y]);
  }
  return out;
}

function pasteHoles(replace) {
  const parsed = parseHoleText($("#holePaste").value);
  const list = holeList();
  if (replace) list.length = 0;
  list.push(...parsed);
  holesChanged();
}

/** Fill the area (minus a margin) with a regular pattern. */
function fillHoles() {
  const pattern = $("#holeFillPattern").value, a = parseFloat($("#holeFillPitch").value), margin = parseFloat($("#holeFillMargin").value) || 0;
  if (!(a > 0)) return;
  const area = holeArea(), x0 = margin, y0 = margin, x1 = area.width - margin, y1 = area.height - margin;
  const rowGap = { square: a, centered_square: a / Math.SQRT2, hex: a * Math.sqrt(3) / 2, staggered: a * Math.sqrt(3) / 2 }[pattern];
  const colGap = pattern === "centered_square" ? a * Math.SQRT2 : a;
  const shifted = pattern !== "square";
  const points = [];
  for (let row = 0, y = y0; y <= y1 + 1e-9 && points.length < HOLE_FILL_MAX; row++, y = y0 + row * rowGap) {
    const shift = shifted && row % 2 ? colGap / 2 : 0;
    for (let x = x0 + shift; x <= x1 + 1e-9 && points.length < HOLE_FILL_MAX; x += colGap) points.push([round(x, 4), round(y, 4)]);
  }
  const list = holeList();
  list.length = 0;
  list.push(...points);
  holesChanged();
}

// --- Check -------------------------------------------------------------------------------------------------
function scheduleHoleCheck() {
  clearTimeout(holeCheckTimer);
  holeCheckTimer = setTimeout(checkHoles, HOLE_CHECK_DEBOUNCE_MS);
}

async function checkHoles() {
  if (holeState.mode === "tile") {
    const tile = holeTile();
    holeState.problems = holeState.tileHoles.map(([x, y], i) => ({ index: i, x, y }))
      .filter(({ x, y }) => !(x >= 0 && y >= 0 && x < tile.width && y < tile.height))
      .map(({ index }) => ({ index, message: t("ui.holes.outside_tile", { n: index + 1 }) }));
  } else if (holeState.holes.length) {
    const response = await holeCheckLatest({ project: cfg, holes: holeState.holes });
    if (!response) return;
    holeState.problems = response.status === 200 ? response.data.problems : errorsOf(response.data).map((message) => ({ index: -1, message }));
  } else {
    holeState.problems = [];
  }
  renderHoleStatus();
  renderHoleTable();
  drawHolePreview();
}

function renderHoleStatus() {
  const count = holeList().length, problems = holeState.problems;
  const box = $("#holeStatus");
  box.className = "statusBox" + (problems.length ? " warn" : "");
  box.textContent = t(holeState.mode === "tile" ? "ui.holes.status_tile" : "ui.holes.status_fixed", { n: count }) +
    (problems.length ? " " + t("ui.holes.status_problems", { n: problems.length }) : "");
  $("#holeProblems").innerHTML = problems.map((p) => `<li style="color:var(--bad)">${esc(p.message)}</li>`).join("");
}

// --- Preview -----------------------------------------------------------------------------------------------
function drawHolePreview() {
  const svg = $("#holePreview");
  svg.innerHTML = "";
  if (!cfg) return;
  const area = holeArea(), tileMode = holeState.mode === "tile";
  const span = tileMode ? 2 * HOLE_TILE_COPIES + 1 : 1, base = tileMode ? -HOLE_TILE_COPIES : 0;
  const w = area.width * span, h = area.height * span, m = Math.max(w, h) * 0.04;
  const ox = base * area.width, oy = base * area.height;
  svg.setAttribute("viewBox", `${ox - m} ${-(oy + h) - m} ${w + 2 * m} ${h + 2 * m}`);
  const thin = Math.max(w, h) / 500, r = Math.max(cfg.rod.diameter / 2, Math.max(w, h) / 300);
  el("rect", { x: 0, y: -area.height, width: area.width, height: area.height, fill: "none", stroke: "currentColor", "stroke-width": thin * 1.5 }, svg);
  const bad = new Set(holeState.problems.map((p) => p.index));
  const holes = holeList();
  if (tileMode) {
    for (let i = base; i < base + span; i++) {
      for (let j = base; j < base + span; j++) {
        if (!i && !j) continue;
        el("rect", { x: i * area.width, y: -(j + 1) * area.height, width: area.width, height: area.height, fill: "none", stroke: "#8a6", "stroke-width": thin, "stroke-dasharray": `${thin * 4} ${thin * 4}` }, svg);
        holes.forEach(([x, y]) => el("circle", { cx: x + i * area.width, cy: -(y + j * area.height), r, fill: COLORS.rod, "fill-opacity": 0.3, "pointer-events": "none" }, svg));
      }
    }
  }
  holes.forEach(([x, y], i) => {
    el("circle", { cx: x, cy: -y, r, fill: bad.has(i) ? COLORS.bad : COLORS.rod, "data-hole-point": i, class: "handle" }, svg);
    svgText(svg, { x: x + r * 1.3, y: -y - r * 1.3, "font-size": r * 2.2, fill: "currentColor", "pointer-events": "none" }, i + 1);
  });
}

function initHolePreview() {
  const svg = $("#holePreview");
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (e.button === 2) return;
    const node = e.target.closest ? e.target.closest("[data-hole-point]") : null;
    svg.setPointerCapture(e.pointerId);
    drag = node ? { i: +node.dataset.holePoint, x: e.clientX, y: e.clientY, moved: false } : { i: null, x: e.clientX, y: e.clientY, moved: false };
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag || drag.i === null) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < HOLE_DRAG_PX) return;
    drag.moved = true;
    const [x, y] = svgPoint(svg, e);
    holeList()[drag.i] = [round(x, 2), round(y, 2)];
    drawHolePreview();
  });
  svg.addEventListener("pointerup", (e) => {
    if (!drag) return;
    if (drag.i === null) {  // click on the free area places a hole
      const [x, y] = svgPoint(svg, e);
      holeList().push([round(x, 2), round(y, 2)]);
    }
    drag = null;
    holesChanged();
  });
  svg.addEventListener("contextmenu", (e) => {
    const node = e.target.closest ? e.target.closest("[data-hole-point]") : null;
    if (!node) return;
    e.preventDefault();
    holeList().splice(+node.dataset.holePoint, 1);
    holesChanged();
  });
}

// --- File and use ---------------------------------------------------------------------------------------------
/** File content in the format blindsight.holes (same structure as written by the core). */
function holeDocument() {
  const doc = {
    format: HOLE_FORMAT, version: 1, units: { length: "mm" }, origin: "bottom left corner of the build area, x to the right, y up",
    build_area: { width: cfg.bounds.width, height: cfg.bounds.height },
    holes: holeState.mode === "fixed" ? holeState.holes.map(([x, y], id) => ({ id, x, y })) : [],
  };
  if (holeState.mode === "tile") {
    const tile = holeTile();
    doc.tile = { ...tile, holes: holeState.tileHoles.map(([x, y]) => ({ x, y })) };
  }
  return doc;
}

async function loadHoleFile(file) {
  let data;
  try { data = JSON.parse(await file.text()); } catch (e) { alert(t("ui.export.bad_file")); return; }
  const { status, data: doc } = await api("/api/holes/parse", data);
  if (status !== 200) { alert(errorsOf(doc).join("\n")); return; }
  holeState.holes = doc.holes.map((h) => [h.x, h.y]);
  if (doc.tile) {
    holeState.tileHoles = doc.tile.holes.map((h) => [h.x, h.y]);
    $("#holeTileW").value = doc.tile.width;
    $("#holeTileH").value = doc.tile.height;
    $("#holeTileScalable").checked = !!doc.tile.scalable;
  }
  holeState.mode = doc.holes.length ? "fixed" : "tile";
  $$("input[name=holeMode]").forEach((r) => { r.checked = r.value === holeState.mode; });
  holesChanged();
}

/** Put the holes into the configuration and switch to the Optimization tab. */
function useHoles() {
  if (holeState.mode === "tile") {
    const tile = holeTile();
    cfg.search.custom_tile = { ...tile, holes: holeState.tileHoles.map((p) => [...p]) };
    cfg.search.pattern = "custom";
    cfg.search.optimizer = "periodic_tile";
  } else {
    cfg.holes = holeState.holes.map((p) => [...p]);
    cfg.search.optimizer = "fixed_holes";
  }
  writeInputs();
  refresh();
  switchTab("optim");
}

/** Hint on the Optimization tab about the hole pattern in use. */
function renderHolesInfo() {
  const box = $("#holesInfo");
  if (!box || !cfg) return;
  const s = cfg.search;
  if (s.optimizer === "fixed_holes") box.textContent = t("ui.holes.info_fixed", { n: (cfg.holes || []).length });
  else if (s.optimizer === "periodic_tile" && s.pattern === "custom" && s.custom_tile) {
    box.textContent = t("ui.holes.info_tile", { n: s.custom_tile.holes.length, width: round(s.custom_tile.width, 2), height: round(s.custom_tile.height, 2) });
  } else { box.hidden = true; return; }
  box.hidden = false;
}
