"use strict";
// Modes of the guided workflow. The optimizer decides the mode like in the core (config.mode_of).
//   holes    given holes on G0 (fixed_holes), the hole editor is step 5
//   pattern  regular lattice, 2a holes and motors repeat as a block (periodic_tile), 2b only the holes,
//            every motor on its own (pattern_holes)
//   free     distribution without a fixed pattern (pattern_greedy, anneal_free, exhaustive_small)

const MODE_OF_OPTIMIZER = { fixed_holes: "holes", periodic_tile: "pattern", pattern_holes: "pattern" };
const FREE_OPTIMIZERS = ["pattern_greedy", "anneal_free", "exhaustive_small"];
const PATTERN_CARDS = ["square", "centered_square", "hex", "hex_rotated", "staggered", "rectangle", "custom", "free"];
const modeMemory = { pattern: "periodic_tile", free: "pattern_greedy" };  // last optimizer per mode

const currentMode = () => MODE_OF_OPTIMIZER[cfg.search.optimizer] || "free";

/** Choose a mode. The optimizer of that mode that was used last comes back. */
function setMode(mode) {
  if (mode !== currentMode()) {
    cfg.search.optimizer = mode === "holes" ? "fixed_holes" : modeMemory[mode];
    if (cfg.search.optimizer === "pattern_holes" && cfg.search.pattern === "free") cfg.search.pattern = "square";
  }
  modesChanged();
}

function modesChanged() {
  updateFieldVisibility();
  refresh();
}

// --- Pattern pictures ---------------------------------------------------------------------------------------
/** Lattice cell like optimizers/periodic_tile.pattern_cell (a = distance to the nearest hole). */
function patternCell(pattern, a, b = null) {
  const r3 = Math.sqrt(3), r2 = Math.SQRT2;
  switch (pattern) {
    case "square": return { w: a, h: a, holes: [[0, 0]] };
    case "centered_square": return { w: a * r2, h: a * r2, holes: [[0, 0], [a * r2 / 2, a * r2 / 2]] };
    case "hex": return { w: a, h: a * r3, holes: [[0, 0], [a / 2, a * r3 / 2]] };
    case "hex_rotated": return { w: a * r3, h: a, holes: [[0, 0], [a * r3 / 2, a / 2]] };
    case "staggered": { const row = b || a * r3 / 2; return { w: a, h: 2 * row, holes: [[0, 0], [a / 2, row]] }; }
    case "rectangle": return { w: a, h: b || a * 1.5, holes: [[0, 0]] };
    case "custom": { const tile = cfg && cfg.search.custom_tile; if (tile && tile.holes.length) return { w: tile.width, h: tile.height, holes: tile.holes }; return { w: a, h: a, holes: [[a * 0.2, a * 0.3], [a * 0.7, a * 0.6]] }; }
    default: return { w: a * 2, h: a, holes: [[0, 0], [a, 0]] };  // free. some rods per tile
  }
}

/** Small picture of a pattern. Holes of a few cells, the cell of free and custom dashed. */
function patternPicture(pattern) {
  const size = 60, cell = patternCell(pattern, 12);
  const scale = pattern === "custom" ? 24 / Math.max(cell.w, cell.h) : 1;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("aria-hidden", "true");
  for (let i = -1; i * cell.w * scale < size; i++) {
    for (let j = -1; j * cell.h * scale < size; j++) {
      for (const [u, v] of cell.holes) {
        const x = 6 + (i * cell.w + u) * scale, y = size - 6 - (j * cell.h + v) * scale;
        if (x > 1 && x < size - 1 && y > 1 && y < size - 1) el("circle", { cx: x, cy: y, r: 2.4, fill: "currentColor" }, svg);
      }
    }
  }
  if (pattern === "free" || pattern === "custom") {
    el("rect", { x: 6 - 3, y: size - 6 - cell.h * scale - 3, width: cell.w * scale + 6, height: cell.h * scale + 6, fill: "none", stroke: "currentColor", "stroke-dasharray": "3 2", "stroke-width": 0.8 }, svg);
  }
  return svg;
}

function buildPatternCards() {
  const box = $("#patternCards");
  box.innerHTML = "";
  for (const pattern of PATTERN_CARDS) {
    const card = document.createElement("button");
    card.className = "card pattern";
    card.dataset.pattern = pattern;
    card.appendChild(patternPicture(pattern));
    const label = document.createElement("span");
    label.textContent = optionLabel("search.pattern", pattern);
    card.appendChild(label);
    card.addEventListener("click", () => {
      if (card.disabled) return;
      cfg.search.pattern = pattern;
      if (pattern === "custom" && !cfg.search.custom_tile) cfg.search.custom_tile = { width: 30, height: 30, holes: [[0, 0]], scalable: true };
      modesChanged();
    });
    box.appendChild(card);
  }
}

function buildFreeMethods() {
  const select = $("#freeMethod"), field = fieldByPath("search.optimizer");
  select.innerHTML = "";
  for (const [value, text] of field.options.filter(([v]) => FREE_OPTIMIZERS.includes(v))) select.add(new Option(text, value));
}

// --- Rendering ------------------------------------------------------------------------------------------------
/** Cards, panels of step 5 and the label of step 5 follow the mode. */
function renderModes() {
  if (!cfg) return;
  const mode = currentMode(), se = cfg.search;
  if (mode !== "holes") modeMemory[mode] = se.optimizer;
  $$("[data-mode]").forEach((c) => {
    c.classList.toggle("chosen", c.dataset.mode === mode);
    c.setAttribute("aria-pressed", String(c.dataset.mode === mode));
  });
  if (mode === "free") $("#moreModes").open = true;
  $$("#patternCards [data-pattern]").forEach((c) => {
    c.classList.toggle("chosen", c.dataset.pattern === se.pattern);
    c.disabled = c.dataset.pattern === "free" && se.optimizer === "pattern_holes";  // 2b needs a lattice
    c.title = c.disabled ? t("ui.pattern.free_needs_block") : "";
  });
  $$("input[name=patternRepeat]").forEach((r) => { r.checked = r.value === se.optimizer; });
  if (mode === "free") $("#freeMethod").value = se.optimizer;
  $("#patternPanel").classList.toggle("active", mode === "pattern");
  $("#freePanel").classList.toggle("active", mode === "free");
  const editor = mode === "holes" ? "fixed" : mode === "pattern" && se.pattern === "custom" ? "tile" : null;
  $("#holeEditor").classList.toggle("active", !!editor);
  if (editor && holeState.mode !== editor) { holeState.mode = editor; holesChanged(); }
  const label = $("#stepHolesLabel");
  label.dataset.i18n = { holes: "ui.step.holes", pattern: "ui.step.pattern", free: "ui.step.free" }[mode];
  label.textContent = t(label.dataset.i18n);
  placeCountField(mode);
  renderRunSummary();
}

/** The target count belongs to the pattern task or the free distribution, the field moves along. */
function placeCountField(mode) {
  const label = document.querySelector('[data-label-for="target_count"]'), input = $("#in-target_count");
  const box = $(mode === "free" ? "#f-free" : "#f-pattern");
  if (!label || !input || box.lastElementChild === input || box.lastElementChild === input.nextElementSibling) return;
  const error = input.nextElementSibling && input.nextElementSibling.classList.contains("errmsg") ? input.nextElementSibling : null;
  box.append(label, input, ...(error ? [error] : []));
}

/** Short summary above the goals. What is computed, on which board. */
function renderRunSummary() {
  const box = $("#runSummary");
  if (!box || !cfg) return;
  const se = cfg.search, b = cfg.bounds, mode = currentMode();
  let what;
  if (mode === "holes") what = t("ui.summary.holes", { n: (cfg.holes || []).length });
  else if (mode === "pattern") {
    what = t("ui.summary.pattern", {
      pattern: optionLabel("search.pattern", se.pattern), task: optionLabel("search.pattern_task", se.pattern_task),
      repeat: t(se.optimizer === "pattern_holes" ? "ui.summary.repeat_holes" : "ui.summary.repeat_block"),
    });
  } else what = t("ui.summary.free", { n: cfg.target_count, method: optionLabel("search.optimizer", se.optimizer) });
  const board = t("ui.summary.board", { w: round(b.width, 2), h: round(b.height, 2) }) + ", " +
    (b.border ? t("ui.summary.border", { b: round(b.border_width, 2) }) : t("ui.summary.no_border"));
  box.innerHTML = `<b>${esc(what)}</b><br>${esc(board)}. ${esc(t("ui.summary.layers", { n: cfg.stack.n_motor_planes }))}`;
}

function initModes() {
  $$("[data-mode]").forEach((c) => c.addEventListener("click", () => setMode(c.dataset.mode)));
  $$("input[name=patternRepeat]").forEach((r) => r.addEventListener("change", () => {
    cfg.search.optimizer = r.value;
    if (r.value === "pattern_holes" && cfg.search.pattern === "free") cfg.search.pattern = "square";
    modesChanged();
  }));
  $("#freeMethod").addEventListener("change", () => { cfg.search.optimizer = $("#freeMethod").value; modesChanged(); });
  for (const box of $$("[data-pic]")) box.appendChild(patternPicture(box.dataset.pic === "pattern" ? "hex" : "custom"));
  buildModeTexts();
}

/** Parts of the modes that come from the schema (labels of patterns and methods). Again after a language switch. */
function buildModeTexts() {
  buildPatternCards();
  buildFreeMethods();
  renderModes();
}
