"use strict";
// Priorities of the goals. Every mode rates its own goals (scoring.GOALS_BY_MODE), the sliders show their
// share in percent. The values stay relative weights in cfg.search.weights.

const WEIGHT_SLIDER_MAX = 20;  // larger values are kept, the slider grows with them
const GOALS_BY_MODE = {
  free: ["count", "area", "uniformity", "regularity"],
  holes: ["layers", "border", "alignment"],
  pattern: ["layers", "border", "alignment"],
};
const WEIGHT_PRESETS = {
  free: {
    count: { count: 20, area: 3, uniformity: 1, regularity: 1 },
    area: { count: 8, area: 20, uniformity: 2, regularity: 1 },
    uniform: { count: 6, area: 3, uniformity: 15, regularity: 4 },
    balanced: { count: 10, area: 8, uniformity: 2, regularity: 1 },
  },
  goals: {
    layers: { layers: 10, border: 2, alignment: 2 },
    border: { layers: 2, border: 10, alignment: 2 },
    alignment: { layers: 2, border: 2, alignment: 10 },
    balanced: { layers: 1, border: 1, alignment: 1 },
  },
};
const PRESET_LABELS = {
  count: "ui.optim.preset_count", area: "ui.optim.preset_area", uniform: "ui.optim.preset_uniform", balanced: "ui.optim.preset_balanced",
  layers: "ui.preset.layers", border: "ui.preset.border", alignment: "ui.preset.alignment",
};

const weightFields = () => schema.fields.filter((f) => f.group === "weights");
const weightKey = (field) => field.path.split(".").pop();
const modeGoals = () => GOALS_BY_MODE[currentMode()];

function buildWeights() {
  const box = $("#weights");
  box.innerHTML = "";
  for (const field of weightFields()) {
    const key = weightKey(field);
    const label = document.createElement("label");
    setFieldLabel(label, field, field.label);
    label.title = field.tip;
    label.dataset.wLabel = key;
    const range = document.createElement("input");
    range.type = "range";
    range.min = 0;
    range.max = WEIGHT_SLIDER_MAX;
    range.step = 0.5;
    range.dataset.w = key;
    range.title = field.tip;
    range.setAttribute("aria-label", field.label);
    const value = document.createElement("span");
    value.id = "wv-" + key;
    range.addEventListener("input", () => {
      cfg.search.weights[key] = parseFloat(range.value);
      renderWeightShares();
    });
    box.append(label, range, value);
  }
}

function writeWeights() {
  for (const field of weightFields()) {
    const key = weightKey(field);
    const range = document.querySelector(`[data-w="${key}"]`);
    const value = cfg.search.weights[key];
    range.max = Math.max(WEIGHT_SLIDER_MAX, Math.ceil(value));  // values above 20 used to be cut off
    range.value = value;
  }
  renderWeightsForMode();
}

/** Only the goals of the mode, each with its share. The edge goal needs the edge strip. */
function renderWeightsForMode() {
  if (!cfg || !schema) return;
  const goals = modeGoals();
  for (const field of weightFields()) {
    const key = weightKey(field), shown = goals.includes(key);
    for (const node of [document.querySelector(`[data-w-label="${key}"]`), document.querySelector(`[data-w="${key}"]`), $("#wv-" + key)]) {
      if (node) node.hidden = !shown;
    }
  }
  const borderRange = document.querySelector('[data-w="border"]');
  if (borderRange) {
    borderRange.disabled = !cfg.bounds.border;
    borderRange.title = cfg.bounds.border ? fieldByPath("search.weights.border").tip : t("ui.run.border_off");
  }
  renderWeightShares();
  renderPresets();
}

function renderWeightShares() {
  const goals = modeGoals(), w = cfg.search.weights;
  const total = goals.reduce((sum, k) => sum + w[k], 0);
  for (const key of goals) {
    const node = $("#wv-" + key);
    if (node) node.textContent = `${Math.round(total > 0 ? (100 * w[key]) / total : 100 / goals.length)} %`;
  }
}

function renderPresets() {
  const box = $("#presets"), group = currentMode() === "free" ? "free" : "goals";
  if (box.dataset.group === group && box.dataset.lang === currentLanguage) return;
  box.dataset.group = group;
  box.dataset.lang = currentLanguage;
  box.innerHTML = `<span>${esc(t("ui.optim.preset"))}</span>`;
  for (const name of Object.keys(WEIGHT_PRESETS[group])) {
    const button = document.createElement("button");
    button.dataset.preset = name;
    button.textContent = t(PRESET_LABELS[name]);
    button.addEventListener("click", () => applyWeightPreset(group, name));
    box.appendChild(button);
  }
}

function applyWeightPreset(group, name) {
  Object.assign(cfg.search.weights, WEIGHT_PRESETS[group][name]);
  writeWeights();
}
