"use strict";
// Weights of the objectives. The sliders come from the schema fields of the group weights (search.weights.*).

const WEIGHT_SLIDER_MAX = 20;  // larger values are kept, the slider grows with them
const WEIGHT_PRESETS = {
  count: { count: 20, area: 3, uniformity: 1, regularity: 1 },
  area: { count: 8, area: 20, uniformity: 2, regularity: 1 },
  uniform: { count: 6, area: 3, uniformity: 15, regularity: 4 },
  balanced: { count: 10, area: 8, uniformity: 2, regularity: 1 },
};

const weightFields = () => schema.fields.filter((f) => f.group === "weights");
const weightKey = (field) => field.path.split(".").pop();

function buildWeights() {
  const box = $("#weights");
  box.innerHTML = "";
  for (const field of weightFields()) {
    const key = weightKey(field);
    const label = document.createElement("label");
    setFieldLabel(label, field, field.label);
    label.title = field.tip;
    const range = document.createElement("input");
    range.type = "range";
    range.min = 0;
    range.max = WEIGHT_SLIDER_MAX;
    range.step = 0.5;
    range.dataset.w = key;
    range.title = field.tip;
    const value = document.createElement("span");
    value.id = "wv-" + key;
    range.addEventListener("input", () => {
      cfg.search.weights[key] = parseFloat(range.value);
      value.textContent = range.value;
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
    $("#wv-" + key).textContent = value;
  }
}

function applyWeightPreset(name) {
  Object.assign(cfg.search.weights, WEIGHT_PRESETS[name]);
  writeWeights();
}
