"use strict";
// Tiling of a repeating block (pattern 2a). The block of the shown solution is set side by side nx x ny
// times on a board fitted around it (/api/tile, tiling.py in the core). The tiled arrangement can become the
// result (then every export works with it), the block can be saved as a file or as an own tile.

const tileLatest = latestOnly((body) => api("/api/tile", body));
const tileState = { response: null };

function initTiling() {
  $$("[data-result-view]").forEach((b) => b.addEventListener("click", () => showResultView(b.dataset.resultView)));
  ["#tileNx", "#tileNy"].forEach((id) => $(id).addEventListener("change", renderTiling));
  $("#tileApply").addEventListener("click", applyTiling);
  $("#tileDownloadBlock").addEventListener("click", downloadBlock);
  $("#tileDownloadTile").addEventListener("click", downloadBlockAsTile);
}

function showResultView(view) {
  $$("[data-result-view]").forEach((b) => b.classList.toggle("active", b.dataset.resultView === view));
  $("#resultMain").classList.toggle("active", view === "main");
  $("#tileView").classList.toggle("active", view === "tile");
  if (view === "tile") renderTiling();
}

/** Why there is nothing to tile, or null. */
function tilingUnavailable() {
  if (currentTile()) return null;
  if (lastResult && lastResult.optimizer === "pattern_holes") return t("ui.tile.only_holes_repeat");
  return t(edited ? "ui.tile.edited" : "ui.tile.no_block");
}

const blockCount = (id) => Math.max(1, Math.min(40, parseInt($(id).value, 10) || 1));

async function renderTiling() {
  const reason = tilingUnavailable();
  $("#tileUnavailable").hidden = !reason;
  $("#tileUnavailable").textContent = reason || "";
  $("#tileContent").hidden = !!reason;
  if (reason) return;
  const tile = currentTile(), nx = blockCount("#tileNx"), ny = blockCount("#tileNy");
  const [block, tiled] = await Promise.all([
    api("/api/tile", { project: cfg, tile, nx: 1, ny: 1 }),
    tileLatest({ project: cfg, tile, nx, ny }),
  ]);
  if (block.status === 200) drawPlan($("#blockPreview"), block.data.geometry, null, true);
  if (!tiled) return;  // a newer request is on its way
  const box = $("#tileStatus");
  if (tiled.status !== 200) {
    tileState.response = null;
    box.className = "statusBox warn";
    box.textContent = errorsOf(tiled.data).join(" ");
    $("#tiledPreview").innerHTML = "";
    return;
  }
  const data = tiled.data, b = data.project.bounds;
  tileState.response = data;
  box.className = "statusBox" + (data.valid ? "" : " warn");
  box.textContent = [t("ui.tile.status", { w: round(b.width, 2), h: round(b.height, 2), n: data.placements.length }),
    t(data.valid ? "ui.tile.valid" : "ui.tile.invalid", { n: data.geometry.collisions.length }), ...data.notes].join(" ");
  drawPlan($("#tiledPreview"), data.geometry, null, true);
  $("#tileApply").disabled = !data.valid;
}

/** The tiled arrangement becomes the result. The board of the configuration grows with it. */
function applyTiling() {
  const data = tileState.response;
  if (!data) return;
  const b = data.project.bounds;
  if (!confirm(t("ui.tile.apply_confirm", { w: round(b.width, 2), h: round(b.height, 2) }))) return;
  Object.assign(cfg.bounds, { width: b.width, height: b.height });
  cfg.obstacles = [];
  cfg.stack.mount_zones = {};
  cfg.target_count = data.placements.length;
  writeInputs();
  refresh();
  showLoadedResult(data.geometry);
  showResultView("main");
}

function blockFile() {
  const tile = currentTile();
  return { format: "blindsight.block", version: 1, units_of_length: "mm", pattern: tile.pattern, pitch: tile.pitch,
           width: tile.width, height: tile.height, cols: tile.cols, rows: tile.rows, units: tile.units };
}

function downloadBlock() {
  if (currentTile()) downloadJson("blindsight-block.json", blockFile());
}

/** The holes of the block as an own tile (format blindsight.holes), the hole editor loads it again. */
function downloadBlockAsTile() {
  const tile = currentTile();
  if (!tile) return;
  downloadJson("blindsight-tile.json", {
    format: HOLE_FORMAT, version: 1, units: { length: "mm" }, holes: [],
    tile: { width: tile.width, height: tile.height, scalable: false, holes: tile.units.map((u) => ({ x: u.x, y: u.y })) },
  });
}
