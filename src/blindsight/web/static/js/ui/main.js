"use strict";
// Start of the UI, language switch, loading configurations and wiring of the controls. The steps of the
// guided workflow live in steps.js, the modes in modes.js.

/** Recursive merge. Objects are merged, lists and values replaced. */
function mergeConfig(base, update) {
  const isObject = (v) => v && typeof v === "object" && !Array.isArray(v);
  for (const key of Object.keys(update)) {
    if (isObject(update[key]) && isObject(base[key])) mergeConfig(base[key], update[key]);
    else base[key] = update[key];
  }
  return base;
}

// Start and "Defaults" of the UI. The guided workflow starts in the pattern mode, the core default is free distribution
const UI_START = { search: { optimizer: "periodic_tile" } };

/** Load a configuration (missing values from the defaults). */
async function loadCfg(obj) {
  cfg = mergeConfig(clone(defaults), obj || {});
  if (!weightsComplete()) normalizeWeights();  // older files kept relative weights, their ratio stays
  loadHolesFromCfg();
  writeInputs();
  await refresh();
  if (window.skReload) skReload();
}

function bindHeader() {
  $("#btnSave").addEventListener("click", () => downloadJson("blindsight-config.json", cfg));
  $("#btnReset").addEventListener("click", () => { if (confirm(t("ui.confirm.reset"))) loadCfg(UI_START); });
  onFile("#fileLoad", async (file) => {
    let obj;
    try { obj = JSON.parse(await file.text()); } catch (err) { alert(t("ui.main.bad_config_file")); return; }
    await loadCfg(obj);
  });
}

function bindTabs() {
  $("#btnStart").addEventListener("click", startJob);
  $("#btnCancel").addEventListener("click", cancelJob);
  ["viewSel", "planeSel", "optDist"].forEach((id) => $("#" + id).addEventListener("change", drawView));
  $("#optEdit").addEventListener("change", () => { editMode = $("#optEdit").checked; renderEditPanel(); drawView(); });
  $("#solSel").addEventListener("change", () => loadResult(+$("#solSel").value));
  $("#btnExport").addEventListener("click", doExport);
  $("#btnSaveResult").addEventListener("click", saveResult);
  onFile("#fileResult", loadResultFile);
  $("#btnGoOptim").addEventListener("click", () => switchTab("run"));
  $("#obsAdd").addEventListener("click", addObstacle);
  $("#zoneAdd").addEventListener("click", addZone);
}

async function loadExamples() {
  const names = (await api("/api/examples")).data;
  names.forEach((name) => $("#exampleSel").add(new Option(name, name)));
  $("#exampleSel").addEventListener("change", async (e) => {
    if (!e.target.value) return;
    const { status, data } = await api("/api/example/" + e.target.value);
    if (status === 200) await loadCfg(data);
    else alert(errorsOf(data).join("\n"));
  });
}

// --- Language ------------------------------------------------------------------------------------------
function buildLanguageSelect() {
  const select = $("#langSel");
  select.innerHTML = "";
  for (const { code, name } of schema.languages || []) select.add(new Option(name, code));
  select.value = currentLanguage;
  select.addEventListener("change", () => changeLanguage(select.value));
}

/**
 * Switch the language of the whole UI. The schema (field labels, tips, options, export formats) and all
 * results come again from the server in the new language, the inputs keep their values.
 */
async function changeLanguage(language) {
  closeHelp();
  setLanguage(language);
  $("#langSel").value = currentLanguage;
  schema = (await api("/api/schema")).data;
  buildForms();
  buildExportFormats();
  buildHoleFillPatterns();
  buildModeTexts();
  writeInputs();
  holesChanged();
  await refresh();
  if (jobId && !JOB_DONE_STATES.includes(lastJobState)) pollStatus();
  if (resultSource === "job" && jobId) await loadResult(solIndex);
  else if (lastGeo) renderResult();
  if (window.skRelocalize) await skRelocalize();
}

/** Buttons made of a label (file choice) are reachable with the keyboard like real buttons. */
function makeLabelButtonsFocusable() {
  for (const label of $$("label.btn")) {
    label.tabIndex = 0;
    label.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); label.click(); }
    });
  }
}

async function init() {
  initHelp();
  makeLabelButtonsFocusable();
  applyStaticTexts();
  schema = (await api("/api/schema")).data;
  defaults = (await api("/api/default")).data;
  buildLanguageSelect();
  buildForms();
  buildExportFormats();
  initSteps();
  initModes();
  initMotorPreview();
  initLibrary();
  if (window.initSketch) initSketch();
  initIsoDrag();
  initEdit();
  initTiling();
  bindHeader();
  bindTabs();
  initHoles();
  await loadExamples();
  await loadCfg(UI_START);
}

window.addEventListener("load", init);
