"use strict";
// Guided workflow. The steps run from left to right (basics, motor, mode, board, holes or pattern, run,
// result). Every step gets Back and Next, the step bar shows which steps were visited and which have a problem.
// Jumping to any step stays possible.

const STEPS = ["basics", "motor", "mode", "board", "holes", "run", "results"];
const stepState = { current: "basics", visited: new Set(["basics"]), motorView: "dims" };

/** Show a step. "sketch" opens the motor step with the sketch, the motor step otherwise keeps its last view. */
function switchTab(name) {
  if (name === "sketch") stepState.motorView = "sketch";
  const step = name === "sketch" ? "motor" : name;
  stepState.current = step;
  stepState.visited.add(step);
  $$("#steps button").forEach((b) => {
    b.classList.toggle("active", b.dataset.step === step);
    b.setAttribute("aria-selected", String(b.dataset.step === step));
  });
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + step));
  showMotorView(stepState.motorView);
  if (step === "holes") setTimeout(holesChanged, 0);  // the build area may have changed
  renderStepStates();
  const active = document.querySelector(`#steps [data-step="${step}"]`);
  if (active && active.scrollIntoView) active.scrollIntoView({ inline: "center", block: "nearest" });  // narrow screens
  window.scrollTo(0, 0);
}

/** Dimensions or sketch inside the motor step. The sketch only counts as open while it is visible. */
function showMotorView(view) {
  stepState.motorView = view;
  const open = stepState.current === "motor";
  $("#motorDims").classList.toggle("active", view === "dims");
  $("#tab-sketch").classList.toggle("active", view === "sketch" && open);
  $$("[data-motor-view]").forEach((b) => b.classList.toggle("active", b.dataset.motorView === view));
  if (view === "sketch" && open && window.skReload) setTimeout(skReload, 0);
}

/** Steps whose fields have errors (from the field markers of forms.js). */
function stepsWithProblems() {
  const out = new Set();
  for (const node of $$(".err")) {
    const section = node.closest(".tab");
    if (section) out.add(section.id.slice(4));
  }
  return out;
}

function renderStepStates() {
  const problems = stepsWithProblems();
  $$("#steps button").forEach((b) => {
    const step = b.dataset.step;
    const state = problems.has(step) ? "problem" : stepState.visited.has(step) && step !== stepState.current ? "done" : "";
    b.dataset.state = state;
    const icon = b.querySelector(".state");
    icon.textContent = state === "problem" ? "!" : state === "done" ? "✓" : "";
    icon.title = state ? t("ui.step.state." + state) : "";
  });
}

/** Back and Next at the end of every step. */
function addStepButtons() {
  STEPS.forEach((step, i) => {
    const nav = document.createElement("div");
    nav.className = "stepNav";
    if (i > 0) nav.appendChild(stepButton("ui.step.back", STEPS[i - 1], ""));
    if (i < STEPS.length - 1) nav.appendChild(stepButton("ui.step.next", STEPS[i + 1], "primary"));
    $("#tab-" + step).appendChild(nav);
  });
}

function stepButton(key, target, className) {
  const button = document.createElement("button");
  button.className = className;
  button.dataset.i18n = key;
  button.dataset.goto = target;
  button.textContent = t(key);
  button.addEventListener("click", () => switchTab(target));
  return button;
}

function initSteps() {
  $$("#steps button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.step)));
  $$("[data-motor-view]").forEach((b) => b.addEventListener("click", () => { stepState.motorView = b.dataset.motorView; switchTab("motor"); }));
  addStepButtons();
  renderStepStates();
}
