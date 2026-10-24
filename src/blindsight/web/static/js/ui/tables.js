"use strict";
// Tabellen. Einstellungen je Motorebene, feste Hindernisse, Montagebereiche.

const MAX_TABLE_PLANES = 200;

// --- Einstellungen je Motorebene -------------------------------------------------------------------
function renderPlaneTable() {
  const stack = cfg.stack;
  const n = stack.n_motor_planes;
  const box = $("#planeTable");
  if (!(Number.isInteger(n) && n >= 1 && n <= MAX_TABLE_PLANES)) { box.innerHTML = ""; return; }
  const caps = stack.max_per_plane || {};
  const angles = stack.plane_angles || {};
  let html = `<table class="grid"><tr><th>Ebene</th><th>erlaubt</th><th>max. Motoren</th><th>Winkel (Grad)</th><th>Dicke [mm]</th></tr>`;
  for (let i = 1; i <= n; i++) {
    const allowed = stack.allowed_planes == null || stack.allowed_planes.includes(i);
    const thickness = stack.thicknesses && stack.thicknesses[i - 1] != null ? round(stack.thicknesses[i - 1]) : "";
    html += `<tr><td>G${i}</td>
      <td><input type="checkbox" data-pt="allowed" data-i="${i}" ${allowed ? "checked" : ""}></td>
      <td><input type="number" min="0" step="1" data-pt="cap" data-i="${i}" value="${esc(caps[i] ?? "")}"></td>
      <td><input type="text" data-pt="ang" data-i="${i}" value="${esc((angles[i] || []).join(", "))}"></td>
      <td><input type="number" step="any" min="0" data-pt="th" data-i="${i}" value="${esc(thickness)}" placeholder="${esc(round(stack.thickness))}"></td></tr>`;
  }
  box.innerHTML = html + "</table>";
  $$("input", box).forEach((input) => input.addEventListener("change", () => { readPlaneTable(); refresh(); }));
}

function readPlaneTable() {
  const stack = cfg.stack;
  const allowed = [], caps = {}, angles = {}, thicknesses = [];
  let anyThickness = false;
  for (const row of $$("#planeTable tr")) {
    const cell = (name) => row.querySelector(`[data-pt="${name}"]`);
    if (!cell("allowed")) continue;  // Kopfzeile
    const i = +cell("allowed").dataset.i;
    if (cell("allowed").checked) allowed.push(i);
    if (cell("cap").value !== "") caps[i] = parseInt(cell("cap").value, 10);
    const list = splitList(cell("ang").value).map(parseFloat);
    if (list.length) angles[i] = list;
    const thickness = cell("th").value;
    thicknesses.push(thickness !== "" ? parseFloat(thickness) : stack.thickness);
    anyThickness = anyThickness || thickness !== "";
  }
  stack.allowed_planes = allowed.length === thicknesses.length ? null : allowed;
  stack.max_per_plane = caps;
  stack.plane_angles = angles;
  stack.thicknesses = anyThickness ? thicknesses : null;
}

// --- Hindernisse ---------------------------------------------------------------------------------------
// [Feld, Spaltentitel, Art] mit Art sel (Auswahl), len (Laenge), num, int oder text
const OBSTACLE_COLUMNS = [["shape", "Form", "sel"], ["x", "x", "len"], ["y", "y", "len"], ["w", "Breite", "len"], ["h", "Höhe", "len"],
  ["r", "Radius", "len"], ["angle", "Winkel", "num"], ["plane", "Ebene", "int"], ["name", "Name", "text"]];
const OBSTACLE_SHAPES = [["rect", "Rechteck"], ["circle", "Kreis"]];

function obstacleCell(obstacle, i, [field, , kind]) {
  if (kind === "sel") {
    const options = OBSTACLE_SHAPES.map(([v, t]) => `<option value="${v}" ${obstacle.shape === v ? "selected" : ""}>${t}</option>`).join("");
    return `<td><select data-ob="${i}" data-f="${field}">${options}</select></td>`;
  }
  const value = obstacle[field];
  const shown = value == null ? "" : kind === "len" ? round(value) : value;
  const type = kind === "text" ? "type=text" : "type=number step=any";
  return `<td><input ${type} data-ob="${i}" data-f="${field}" value="${esc(shown)}"></td>`;
}

function renderObstacles() {
  const head = OBSTACLE_COLUMNS.map(([, title, kind]) => `<th>${title}${kind === "len" ? ` [mm]` : ""}</th>`).join("");
  let html = `<table class="grid"><tr>${head}<th></th></tr>`;
  cfg.obstacles.forEach((obstacle, i) => {
    html += "<tr>" + OBSTACLE_COLUMNS.map((c) => obstacleCell(obstacle, i, c)).join("") + `<td><button data-obdel="${i}">x</button></td></tr>`;
  });
  const box = $("#obsTable");
  box.innerHTML = html + "</table>";
  $$("[data-ob]", box).forEach((input) => input.addEventListener("change", () => { readObstacleCell(input); refresh(); }));
  $$("[data-obdel]", box).forEach((button) => button.addEventListener("click", () => {
    cfg.obstacles.splice(+button.dataset.obdel, 1);
    renderObstacles();
    refresh();
  }));
}

function readObstacleCell(input) {
  const obstacle = cfg.obstacles[+input.dataset.ob];
  const field = input.dataset.f;
  const kind = OBSTACLE_COLUMNS.find((c) => c[0] === field)[2];
  if (kind === "sel" || kind === "text") obstacle[field] = input.value;
  else if (input.value === "") obstacle[field] = field === "plane" ? null : 0;
  else if (kind === "len") obstacle[field] = parseFloat(input.value);
  else obstacle[field] = kind === "int" ? parseInt(input.value, 10) : parseFloat(input.value);
}

function addObstacle() {
  const b = cfg.bounds;
  cfg.obstacles.push({ shape: "circle", x: b.width / 2, y: b.height / 2, w: 10, h: 10, r: 5, angle: 0, z0: -1e6, z1: 1e6, plane: null, name: "" });
  renderObstacles();
  refresh();
}

// --- Montagebereiche -------------------------------------------------------------------------------------
const ZONE_TITLES = ["x min", "y min", "x max", "y max"];

function renderZones() {
  const rows = [];
  for (const [plane, zones] of Object.entries(cfg.stack.mount_zones || {})) zones.forEach((zone, j) => rows.push([plane, j, zone]));
  let html = `<table class="grid"><tr><th>Ebene</th>${ZONE_TITLES.map((t) => `<th>${t} [mm]</th>`).join("")}<th></th></tr>`;
  for (const [plane, j, zone] of rows) {
    const key = `${esc(plane)}:${j}`;
    html += `<tr><td><input type="number" min="1" step="1" data-z="${key}" data-f="plane" value="${esc(plane)}"></td>` +
      zone.map((v, q) => `<td><input type="number" step="any" data-z="${key}" data-f="${q}" value="${esc(round(v))}"></td>`).join("") +
      `<td><button data-zdel="${key}">x</button></td></tr>`;
  }
  const box = $("#zoneTable");
  box.innerHTML = html + "</table>";
  $$("[data-z]", box).forEach((input) => input.addEventListener("change", () => { readZones(); refresh(); }));
  $$("[data-zdel]", box).forEach((button) => button.addEventListener("click", () => {
    const [plane, j] = button.dataset.zdel.split(":");
    cfg.stack.mount_zones[plane].splice(+j, 1);
    if (!cfg.stack.mount_zones[plane].length) delete cfg.stack.mount_zones[plane];
    renderZones();
    refresh();
  }));
}

function readZones() {
  const rows = {};
  $$("#zoneTable [data-z]").forEach((input) => { (rows[input.dataset.z] ||= {})[input.dataset.f] = input.value; });
  const out = {};
  for (const [key, row] of Object.entries(rows)) {
    const plane = parseInt(row.plane, 10);
    // Leere oder ungueltige Ebene. Die Zeile behaelt ihre bisherige Ebene (frueher entstand der Schluessel "NaN")
    const planeKey = Number.isInteger(plane) && plane >= 1 ? String(plane) : key.split(":")[0];
    (out[planeKey] ||= []).push([0, 1, 2, 3].map((q) => parseFloat(row[q])));
  }
  cfg.stack.mount_zones = out;
}

function addZone() {
  const b = cfg.bounds;
  cfg.stack.mount_zones ||= {};
  (cfg.stack.mount_zones["1"] ||= []).push([0, 0, b.width, b.height]);
  renderZones();
  refresh();
}
