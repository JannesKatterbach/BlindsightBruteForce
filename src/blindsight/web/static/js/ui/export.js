"use strict";
// Export der angezeigten Anordnung, Speichern und Laden von Ergebnissen.

/** Formatauswahl aus dem Schema (Exportformate des Kerns). */
function buildExportFormats() {
  const select = $("#expFmt");
  select.innerHTML = "";
  for (const format of schema.exporters || []) select.add(new Option(format.label, format.name));
}

async function doExport() {
  if (!lastGeo) return;
  const format = $("#expFmt").value;
  const body = { project: cfg, placements: placementsOf(lastGeo), format };
  const response = await fetch("/api/export-layout", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) });
  if (!response.ok) { alert("Export fehlgeschlagen. " + (await response.text())); return; }
  // Typ der Datei kommt vom Server (frueher immer text/plain)
  const exporter = (schema.exporters || []).find((e) => e.name === format);
  download(exporter ? exporter.filename : "blindsight." + format, await response.blob());
}

function saveResult() {
  if (!lastGeo) return;
  download("blindsight-ergebnis.json", JSON.stringify({ project: cfg, placements: placementsOf(lastGeo) }, null, 2), "application/json");
}

async function loadResultFile(file) {
  let obj;
  try { obj = JSON.parse(await file.text()); } catch (e) { alert("Keine gültige Datei."); return; }
  if (!obj || !obj.project || !Array.isArray(obj.placements)) { alert("Datei enthält kein Ergebnis (project und placements erwartet)."); return; }
  await loadCfg(obj.project);
  const { status, data } = await api("/api/validate", { project: cfg, placements: obj.placements });
  if (status !== 200) { alert(errorsOf(data).join("\n")); return; }
  showLoadedResult(data.geometry);
  switchTab("results");
}
