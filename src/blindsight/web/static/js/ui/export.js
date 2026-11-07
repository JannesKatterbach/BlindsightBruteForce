"use strict";
// Export menu of the shown arrangement (preset, format, layer, contents), saving and loading results.
// Formats, parts and presets come from the schema (exporters and export_menu of the core).

const CUSTOM_PRESET = "custom";
const exportState = { preset: "everything", format: "svg", layer: "all", contents: {} };  // contents per format

const exporterOf = (name) => (schema.exporters || []).find((e) => e.name === name);
const exportMenu = () => schema.export_menu || { contents: [], presets: [] };
const presetOf = (name) => exportMenu().presets.find((p) => p.name === name);

/** Chosen parts of a format, its defaults until something was chosen. */
function chosenContents(format) {
  const exporter = exporterOf(format);
  if (!exporter) return [];
  if (!exportState.contents[format]) exportState.contents[format] = new Set(exporter.default_contents);
  return exporter.contents.filter((c) => exportState.contents[format].has(c));
}

/** Selects and check boxes of the menu. Again after a language switch. */
function buildExportMenu() {
  const formats = $("#expFmt");
  formats.innerHTML = "";
  for (const format of schema.exporters || []) formats.add(new Option(format.label, format.name));
  const presets = $("#expPreset");
  presets.innerHTML = "";
  presets.add(new Option(t("ui.export.custom"), CUSTOM_PRESET));
  for (const preset of exportMenu().presets) presets.add(new Option(preset.label, preset.name));
  const list = $("#expContentList");
  list.innerHTML = "";
  for (const { name, label } of exportMenu().contents) {
    const row = document.createElement("label");
    row.dataset.content = name;
    row.innerHTML = `<input type="checkbox" value="${esc(name)}"> ${esc(label)}`;
    row.querySelector("input").addEventListener("change", (e) => {
      chosenContents(exportState.format);
      exportState.contents[exportState.format][e.target.checked ? "add" : "delete"](name);
      exportChanged();
    });
    list.appendChild(row);
  }
  renderExportMenu();
}

/** A preset sets format, layer and parts. A layer the result does not have falls back to all layers. */
function applyPreset(name) {
  exportState.preset = name;
  const preset = presetOf(name);
  if (!preset) return renderExportMenu();
  if (preset.format) exportState.format = preset.format;
  exportState.layer = String(preset.layer);
  const exporter = exporterOf(exportState.format);
  exportState.contents[exportState.format] = new Set(preset.contents || exporter.default_contents);
  renderExportMenu();
}

/** A change by hand turns the preset into an own choice. */
function exportChanged() {
  exportState.preset = CUSTOM_PRESET;
  renderExportMenu();
}

function renderExportMenu() {
  if (!schema || !$("#expFmt").options.length) return;
  const exporter = exporterOf(exportState.format) || schema.exporters[0];
  exportState.format = exporter.name;
  $("#expPreset").value = exportState.preset;
  $("#expFmt").value = exporter.name;
  // Layers of the shown result (with layers not fixed only the used ones)
  const layers = $("#expLayer"), planes = exporter.layer_choice && lastGeo ? lastGeo.planes : [];
  layers.innerHTML = "";
  layers.add(new Option(t("ui.export.all_layers"), "all"));
  for (const plane of planes) layers.add(new Option(plane.name, String(plane.index)));
  if (!planes.some((p) => String(p.index) === exportState.layer)) exportState.layer = "all";
  layers.value = exportState.layer;
  layers.disabled = !exporter.layer_choice;
  // Parts the format can draw
  const chosen = chosenContents(exporter.name);
  for (const row of $$("#expContentList [data-content]")) {
    row.hidden = !exporter.contents.includes(row.dataset.content);
    row.querySelector("input").checked = chosen.includes(row.dataset.content);
  }
  $("#expContents").hidden = !exporter.contents.length;
  const preset = presetOf(exportState.preset);
  $("#expHint").textContent = preset ? preset.hint : exporter.layer_choice ? "" : t("ui.export.all_layers_only");
  const nothing = exporter.contents.length > 0 && !chosen.length;
  $("#expProblem").textContent = nothing ? t("ui.export.nothing") : "";
  $("#btnExport").disabled = nothing || !lastGeo;
}

/** The request body of the current choice. */
function exportRequest() {
  const exporter = exporterOf(exportState.format);
  const body = { project: cfg, placements: placementsOf(lastGeo), format: exporter.name, layer: exportState.layer };
  if (exporter.contents.length) body.contents = chosenContents(exporter.name);
  return body;
}

/** File name from the answer (the server adds the layer), otherwise from the schema. */
function exportFileName(response, exporter) {
  const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "");
  return match ? match[1] : exporter.filename;
}

async function doExport() {
  if (!lastGeo) return;
  const exporter = exporterOf(exportState.format);
  const response = await fetch("/api/export-layout", { method: "POST", headers: requestHeaders(JSON_HEADERS), body: JSON.stringify(exportRequest()) });
  if (!response.ok) { alert(t("ui.export.failed", { error: errorsOf(await response.json().catch(() => ({}))).join(" ") })); return; }
  download(exportFileName(response, exporter), await response.blob());
}

function initExportMenu() {
  $("#expPreset").addEventListener("change", (e) => applyPreset(e.target.value));
  $("#expFmt").addEventListener("change", (e) => { exportState.format = e.target.value; exportChanged(); });
  $("#expLayer").addEventListener("change", (e) => { exportState.layer = e.target.value; exportChanged(); });
  $("#btnExport").addEventListener("click", doExport);
  const menu = $("#exportMenu");
  menu.addEventListener("toggle", () => { if (menu.open) renderExportMenu(); });
  // Close on a click outside and with Escape, like other menus
  document.addEventListener("click", (e) => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  menu.addEventListener("keydown", (e) => { if (e.key === "Escape") { menu.open = false; menu.querySelector("summary").focus(); } });
}

function saveResult() {
  if (!lastGeo) return;
  download(t("ui.export.result_file"), JSON.stringify({ project: cfg, placements: placementsOf(lastGeo) }, null, 2), "application/json");
}

async function loadResultFile(file) {
  let obj;
  try { obj = JSON.parse(await file.text()); } catch (e) { alert(t("ui.export.bad_file")); return; }
  if (!obj || !obj.project || !Array.isArray(obj.placements)) { alert(t("ui.export.no_result")); return; }
  await loadCfg(obj.project);
  const { status, data } = await api("/api/validate", { project: cfg, placements: obj.placements });
  if (status !== 200) { alert(errorsOf(data).join("\n")); return; }
  showLoadedResult(data.geometry);
  switchTab("results");
}
