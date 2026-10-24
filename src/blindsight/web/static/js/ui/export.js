"use strict";
// Export of the shown arrangement, saving and loading results.

/** Format selection from the schema (export formats of the core). */
function buildExportFormats() {
  const select = $("#expFmt"), current = select.value;
  select.innerHTML = "";
  for (const format of schema.exporters || []) select.add(new Option(format.label, format.name));
  if (current) select.value = current;  // keep the choice across a language switch
}

async function doExport() {
  if (!lastGeo) return;
  const format = $("#expFmt").value;
  const body = { project: cfg, placements: placementsOf(lastGeo), format };
  const response = await fetch("/api/export-layout", { method: "POST", headers: requestHeaders(JSON_HEADERS), body: JSON.stringify(body) });
  if (!response.ok) { alert(t("ui.export.failed", { error: errorsOf(await response.json().catch(() => ({}))).join(" ") })); return; }
  // The file type comes from the server (it used to be text/plain always)
  const exporter = (schema.exporters || []).find((e) => e.name === format);
  download(exporter ? exporter.filename : "blindsight." + format, await response.blob());
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
