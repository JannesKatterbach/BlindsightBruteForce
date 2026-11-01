"use strict";
// Forms from the schema (FIELD_META of the core), reading and writing the fields, field errors.

const GROUP_TARGET = { general: "f-general", rod: "f-rod", motor: "f-motor", stack: "f-stack", bounds: "f-bounds", search: "f-search" };
// These fields are edited in the table per motor layer (otherwise there would be two editors for one value)
const TABLE_FIELDS = new Set(["stack.allowed_planes", "stack.thicknesses"]);
// Rarely changed fields. They sit in a folded part "More settings" below their form and stay editable there
const ADVANCED_FIELDS = new Set([
  "tolerance", "rod.length_tolerance", "rod.retract_depth", "rod.hole_clearance",
  "motor.shaft_x", "motor.gear_gap", "motor.center_distance_min", "motor.center_distance_max", "motor.center_distance_steps",
  "motor.own_clearance",
  "search.patterns", "search.fixed_pitch", "search.angle_step", "search.angle_min", "search.angle_max", "search.allowed_angles",
  "search.max_candidates", "search.seed", "search.top_k", "search.refine_fraction", "search.stagnation_s", "search.workers",
  "search.tile_step", "search.max_block_holes",
]);

const fieldByPath = (path) => schema.fields.find((f) => f.path === path);
/** Label of an option of an enum field in the current language (the value itself if unknown). */
function optionLabel(path, value) {
  const field = fieldByPath(path);
  const option = field && field.options && field.options.find(([v]) => v === value);
  return option ? option[1] : value;
}

// Fields that only matter for some settings. They are hidden otherwise (the values stay in cfg)
const usesPattern = (c) => c.search.optimizer === "periodic_tile";
const FIELD_VISIBLE = {
  "target_count": (c) => c.search.optimizer !== "fixed_holes",
  "search.pattern": usesPattern,
  "search.pattern_pitch": (c) => usesPattern(c) && c.search.pattern !== "free",
  "search.pattern_pitch_y": (c) => usesPattern(c) && ["rectangle", "staggered"].includes(c.search.pattern),
  "search.max_block_holes": (c) => usesPattern(c) && c.search.pattern !== "free",
  "search.tile_rods": (c) => usesPattern(c) && c.search.pattern === "free",
  "search.tile_width": (c) => usesPattern(c) && c.search.pattern === "free",
  "search.tile_height": (c) => usesPattern(c) && c.search.pattern === "free",
  "search.tile_step": usesPattern,
  "search.patterns": (c) => c.search.optimizer === "pattern_greedy",
  "search.fixed_pitch": (c) => ["pattern_greedy", "exhaustive_small"].includes(c.search.optimizer),
  "stack.uniform_spacing": (c) => c.stack.mode === "uniform",
  "stack.gaps": (c) => c.stack.mode === "gaps",
  "stack.distances": (c) => c.stack.mode === "distances",
};

/** Show only the fields that matter for the current settings. */
function updateFieldVisibility() {
  for (const [path, visible] of Object.entries(FIELD_VISIBLE)) {
    const input = document.querySelector(`[data-path="${path}"]`);
    const label = document.querySelector(`[data-label-for="${path}"]`);
    if (!input || !label) continue;
    const show = !!visible(cfg);
    for (const node of [input, label]) node.hidden = !show;
    const next = input.nextElementSibling;
    if (next && next.classList.contains("errmsg")) next.hidden = !show;
  }
  updateAdvancedParts();
  renderHolesInfo();
}

/** Folded part "More settings" of a form group, created on first use right below the form. */
function advancedBox(group) {
  const id = GROUP_TARGET[group] + "-more";
  if (!$("#" + id)) {
    const details = document.createElement("details");
    details.className = "advanced";
    details.innerHTML = `<summary></summary><div class="form" id="${id}"></div>`;
    $("#" + GROUP_TARGET[group]).insertAdjacentElement("afterend", details);
  }
  return $("#" + id);
}

/** Summary of the folded parts with the number of changed values. Parts without visible fields are hidden. */
function updateAdvancedParts() {
  for (const details of $$("details.advanced")) {
    const inputs = $$("[data-path]", details);
    const changed = inputs.filter((i) => JSON.stringify(getPath(cfg, i.dataset.path)) !== JSON.stringify(getPath(defaults, i.dataset.path))).length;
    details.querySelector("summary").textContent = t("ui.form.advanced") + (changed ? ` · ${t("ui.form.changed", { n: changed })}` : "");
    details.hidden = inputs.every((i) => i.hidden);
  }
}
const inputId = (path) => "in-" + path.replace(/\./g, "-");

function buildForms() {
  for (const id of Object.values(GROUP_TARGET)) $("#" + id).innerHTML = "";
  for (const box of $$("details.advanced .form")) box.innerHTML = "";  // the folded parts keep their open state
  for (const field of schema.fields) {
    if (!(field.group in GROUP_TARGET) || TABLE_FIELDS.has(field.path)) continue;
    const box = ADVANCED_FIELDS.has(field.path) ? advancedBox(field.group) : $("#" + GROUP_TARGET[field.group]);
    const label = document.createElement("label");
    setFieldLabel(label, field, lenLabel(field.label, field.kind));
    label.title = field.tip;
    label.dataset.labelFor = field.path;
    box.appendChild(label);
    box.appendChild(createInput(field));
  }
  buildWeights();
}

function createInput(field) {
  let input;
  if (field.kind === "enum") {
    input = document.createElement("select");
    for (const [value, text] of field.options) input.add(new Option(text, value));
  } else {
    input = document.createElement("input");
    input.type = field.kind === "text" || kindOf(field.kind).list ? "text" : "number";
    input.step = "any";
  }
  input.title = field.tip;
  input.dataset.tip = field.tip;  // restores the tooltip when a field was locked temporarily
  input.dataset.path = field.path;
  input.dataset.kind = field.kind;
  input.dataset.optional = field.optional ? "1" : "";
  input.id = inputId(field.path);
  input.addEventListener("change", () => {
    // The browser may report change a second time when the field is left. Without a real change
    // nothing is redrawn (otherwise inputs in rebuilt tables would get lost)
    const before = JSON.stringify(getPath(cfg, field.path));
    if (!readInput(input) || JSON.stringify(getPath(cfg, field.path)) === before) return;
    if (field.path.startsWith("stack.")) renderPlaneTable();  // layer count or thickness changed
    updateFieldVisibility();
    refresh();
  });
  return input;
}

/** Take the field value into cfg. false for invalid input (cfg stays unchanged then). */
function readInput(input) {
  const path = input.dataset.path;
  const text = input.value;
  if (text.trim() === "") {
    if (input.dataset.optional) { setPath(cfg, path, null); clearFieldError(input); return true; }
    if (!kindOf(input.dataset.kind).list) { markFieldError(input, t("ui.form.value_required")); return false; }
  }
  const value = kindOf(input.dataset.kind).read(text);
  if (value === undefined) { markFieldError(input, t("ui.form.invalid_input")); return false; }
  setPath(cfg, path, value);
  clearFieldError(input);
  return true;
}

function writeInputs() {
  for (const input of $$("[data-path]")) {
    const value = getPath(cfg, input.dataset.path);
    input.value = value == null ? "" : kindOf(input.dataset.kind).write(value);
  }
  for (const label of $$("[data-label-for]")) {
    const field = fieldByPath(label.dataset.labelFor);
    setFieldLabel(label, field, lenLabel(field.label, field.kind));
  }
  writeWeights();
  updateFieldVisibility();
  renderPlaneTable();
  renderObstacles();
  renderZones();
}

// --- Errors -------------------------------------------------------------------------------------------
function markFieldError(input, message) {
  clearFieldError(input);
  const folded = input.closest("details");
  if (folded) folded.open = true;  // an error in "More settings" must not stay hidden
  input.classList.add("err");
  const box = document.createElement("div");
  box.className = "errmsg";
  box.textContent = message;
  input.insertAdjacentElement("afterend", box);
}

function clearFieldError(input) {
  input.classList.remove("err");
  const next = input.nextElementSibling;
  if (next && next.classList.contains("errmsg")) next.remove();
}

/** Show messages of the form "path. text" at the field and all messages in the banner. */
function showFieldErrors(errors) {
  $$(".err").forEach((node) => node.classList.remove("err"));
  $$(".errmsg").forEach((node) => node.remove());
  for (const message of errors) {
    const match = /^([\w.\[\]]+)\. (.*)$/.exec(message);
    const input = match && document.querySelector(`[data-path="${match[1]}"]`);
    if (input) markFieldError(input, match[2]);
  }
  const banner = $("#banner");  // role alert in index.html, screen readers announce it
  banner.hidden = errors.length === 0;
  banner.innerHTML = errors.length ? "<ul>" + errors.map((e) => `<li>${esc(e)}</li>`).join("") + "</ul>" : "";
}
