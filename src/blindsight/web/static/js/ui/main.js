"use strict";
// Start of the UI, tabs, language switch, loading configurations and wiring of the controls.

function switchTab(name) {
  if (name === "sketch" && window.skReload) setTimeout(skReload, 0);
  if (name === "holes") setTimeout(holesChanged, 0);  // the build area may have changed
  $$("#tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
  });
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
}

/** Recursive merge. Objects are merged, lists and values replaced. */
function mergeConfig(base, update) {
  const isObject = (v) => v && typeof v === "object" && !Array.isArray(v);
  for (const key of Object.keys(update)) {
    if (isObject(update[key]) && isObject(base[key])) mergeConfig(base[key], update[key]);
    else base[key] = update[key];
  }
  return base;
}

/** Load a configuration (missing values from the defaults). */
async function loadCfg(obj) {
  cfg = mergeConfig(clone(defaults), obj || {});
  writeInputs();
  await refresh();
  if (window.skReload) skReload();
}

/** Read a file from a file input and reset the input (the same file works again). */
function onFile(selector, handler) {
  $(selector).addEventListener("change", async (e) => {
    const file = e.target.files[0];
    resetFileInput(e.target);
    if (file) await handler(file);
  });
}

function bindHeader() {
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#btnSave").addEventListener("click", () => download("blindsight-config.json", JSON.stringify(cfg, null, 2), "application/json"));
  $("#btnReset").addEventListener("click", () => { if (confirm(t("ui.confirm.reset"))) loadCfg({}); });
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
  $("#btnGoOptim").addEventListener("click", () => switchTab("optim"));
  $$("[data-preset]").forEach((b) => b.addEventListener("click", () => applyWeightPreset(b.dataset.preset)));
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
  initMotorPreview();
  initLibrary();
  if (window.initSketch) initSketch();
  initIsoDrag();
  initEdit();
  bindHeader();
  bindTabs();
  await loadExamples();
  await loadCfg({});
  initHoles();
}

window.addEventListener("load", init);
