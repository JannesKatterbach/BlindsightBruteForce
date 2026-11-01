"use strict";
// Priorities of the goals in percent. Every mode rates its own goals (scoring.goals_for), few layers only when
// the layer count is not fixed. Every goal has a slider and a number field, both move freely. The sum must be
// 100 percent before a run starts, the line below the goals says how far off it is.

const WEIGHT_MAX = 100;
const GOALS_BY_MODE = {
  free: ["count", "area", "uniformity", "regularity"],
  holes: ["border", "alignment"],
  pattern: ["border", "alignment"],
};
// Presets in percent. Goals that are not shown are left out and the rest is scaled to 100
const WEIGHT_PRESETS = {
  free: {
    count: { count: 70, area: 15, uniformity: 10, regularity: 5 },
    area: { count: 30, area: 60, uniformity: 6, regularity: 4 },
    uniform: { count: 25, area: 15, uniformity: 45, regularity: 15 },
    balanced: { count: 48, area: 38, uniformity: 10, regularity: 4 },
  },
  goals: {
    layers: { layers: 60, border: 20, alignment: 20 },
    border: { layers: 10, border: 70, alignment: 20 },
    alignment: { layers: 10, border: 20, alignment: 70 },
    balanced: { layers: 34, border: 33, alignment: 33 },
  },
};
const PRESET_LABELS = {
  count: "ui.optim.preset_count", area: "ui.optim.preset_area", uniform: "ui.optim.preset_uniform", balanced: "ui.optim.preset_balanced",
  layers: "ui.preset.layers", border: "ui.preset.border", alignment: "ui.preset.alignment",
};

const weightFields = () => schema.fields.filter((f) => f.group === "weights");
const weightKey = (field) => field.path.split(".").pop();
/** Goals of the current mode, like scoring.goals_for in the core. */
const modeGoals = () => GOALS_BY_MODE[currentMode()].concat(cfg.stack.layers_fixed ? [] : ["layers"]);
const weightSum = () => modeGoals().reduce((sum, k) => sum + (cfg.search.weights[k] || 0), 0);
const weightsComplete = () => Math.abs(weightSum() - 100) < 1e-6;

function buildWeights() {
  const box = $("#weights");
  box.innerHTML = "";
  for (const field of weightFields()) {
    const key = weightKey(field);
    const row = document.createElement("div");
    row.className = "weightRow";
    row.dataset.wRow = key;
    const label = document.createElement("label");
    setFieldLabel(label, field, field.label);
    label.title = field.tip;
    label.htmlFor = "wn-" + key;
    const range = document.createElement("input");
    Object.assign(range, { type: "range", min: 0, max: WEIGHT_MAX, step: 1, title: field.tip });
    range.dataset.w = key;
    range.setAttribute("aria-label", field.label);
    const number = document.createElement("input");
    Object.assign(number, { type: "number", min: 0, max: WEIGHT_MAX, step: 1, id: "wn-" + key });
    number.dataset.wNumber = key;
    const unit = document.createElement("span");
    unit.textContent = "%";
    const note = document.createElement("span");
    note.className = "hint weightNote";
    note.id = "wnote-" + key;
    const set = (value) => {
      const v = Math.max(0, Math.min(WEIGHT_MAX, Math.round(Number(value) || 0)));
      cfg.search.weights[key] = v;
      range.value = number.value = v;
      renderWeightSum();
    };
    range.addEventListener("input", () => set(range.value));
    number.addEventListener("change", () => set(number.value));
    row.append(label, range, number, unit, note);
    box.appendChild(row);
  }
  const sum = document.createElement("div");
  sum.className = "weightSum";
  sum.innerHTML = '<span id="weightSum"></span> <button id="weightNormalize" type="button"></button>';
  box.appendChild(sum);
  $("#weightNormalize").addEventListener("click", normalizeWeights);
}

function writeWeights() {
  for (const field of weightFields()) {
    const key = weightKey(field);
    const value = Math.round(cfg.search.weights[key] || 0);
    document.querySelector(`[data-w="${key}"]`).value = value;
    document.querySelector(`[data-w-number="${key}"]`).value = value;
  }
  renderWeightsForMode();
}

/** Only the goals of the mode. The edge goal says when it has no effect (edge strip off). */
function renderWeightsForMode() {
  if (!cfg || !schema) return;
  const goals = modeGoals();
  for (const field of weightFields()) {
    const key = weightKey(field);
    const row = document.querySelector(`[data-w-row="${key}"]`);
    if (row) row.hidden = !goals.includes(key);
  }
  const note = $("#wnote-border");
  if (note) note.textContent = cfg.bounds.border ? "" : t("ui.run.border_off");
  renderWeightSum();
  renderPresets();
}

/** Sum of the shown goals, green at 100 percent, otherwise how much is missing or too much. */
function renderWeightSum() {
  const box = $("#weightSum");
  if (!box || !cfg) return;
  const sum = Math.round(weightSum()), rest = Math.abs(100 - sum);
  box.textContent = sum === 100 ? t("ui.run.sum_ok") : t(sum < 100 ? "ui.run.sum_missing" : "ui.run.sum_over", { sum, rest });
  box.className = sum === 100 ? "ok" : "warn";
  $("#weightNormalize").textContent = t("ui.run.normalize");
  $("#weightNormalize").hidden = sum === 100;
  updateStartButton();
}

/** Scale the shown goals to 100 percent (whole numbers, the rest goes to the largest). */
function normalizeWeights() {
  const goals = modeGoals(), w = cfg.search.weights, sum = weightSum();
  const values = goals.map((k) => (sum > 0 ? Math.round((100 * (w[k] || 0)) / sum) : Math.floor(100 / goals.length)));
  const largest = values.indexOf(Math.max(...values));
  values[largest] += 100 - values.reduce((a, b) => a + b, 0);
  goals.forEach((k, i) => { w[k] = values[i]; });
  writeWeights();
}

/** Start only with priorities of 100 percent and no run going on. */
function updateStartButton() {
  const button = $("#btnStart");
  if (!button || !cfg) return;
  const ready = weightsComplete();
  button.disabled = jobRunning || !ready;
  button.title = ready ? "" : t("ui.run.start_blocked");
  $("#startHint").textContent = ready || jobRunning ? "" : t("ui.run.start_blocked");
}

function renderPresets() {
  const box = $("#presets"), group = currentMode() === "free" ? "free" : "goals";
  const key = `${group}|${currentLanguage}|${cfg.stack.layers_fixed}`;
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.innerHTML = `<span>${esc(t("ui.optim.preset"))}</span>`;
  for (const name of Object.keys(WEIGHT_PRESETS[group])) {
    if (name === "layers" && cfg.stack.layers_fixed) continue;  // the goal is not shown
    const button = document.createElement("button");
    button.dataset.preset = name;
    button.textContent = t(PRESET_LABELS[name]);
    button.addEventListener("click", () => applyWeightPreset(group, name));
    box.appendChild(button);
  }
}

function applyWeightPreset(group, name) {
  const preset = WEIGHT_PRESETS[group][name];
  for (const key of modeGoals()) cfg.search.weights[key] = preset[key] || 0;
  normalizeWeights();  // goals that are not shown were left out, the rest makes 100 percent again
}
