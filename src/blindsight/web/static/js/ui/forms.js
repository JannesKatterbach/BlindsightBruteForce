"use strict";
// Formulare aus dem Schema (FIELD_META des Kerns), Lesen und Schreiben der Felder, Feldfehler.

const GROUP_TARGET = { general: "f-general", rod: "f-rod", motor: "f-motor", stack: "f-stack", bounds: "f-bounds", search: "f-search" };
// Diese Felder werden in der Tabelle je Motorebene bearbeitet (sonst gaebe es zwei Editoren fuer denselben Wert)
const TABLE_FIELDS = new Set(["stack.allowed_planes", "stack.thicknesses"]);

const fieldByPath = (path) => schema.fields.find((f) => f.path === path);
const inputId = (path) => "in-" + path.replace(/\./g, "-");

function buildForms() {
  for (const id of Object.values(GROUP_TARGET)) $("#" + id).innerHTML = "";
  for (const field of schema.fields) {
    if (!(field.group in GROUP_TARGET) || TABLE_FIELDS.has(field.path)) continue;
    const box = $("#" + GROUP_TARGET[field.group]);
    const label = document.createElement("label");
    label.textContent = lenLabel(field.label, field.kind);
    label.title = field.tip;
    label.dataset.labelFor = field.path;
    box.appendChild(label);
    box.appendChild(createInput(field));
  }
  buildWeights();
}

function createInput(field) {
  let input;
  if (field.kind === "enum") {
    input = document.createElement("select");
    for (const [value, text] of field.options) input.add(new Option(text, value));
  } else {
    input = document.createElement("input");
    input.type = field.kind === "text" || kindOf(field.kind).list ? "text" : "number";
    input.step = "any";
  }
  input.title = field.tip;
  input.dataset.tip = field.tip;  // Tooltip wiederherstellen, wenn ein Feld voruebergehend gesperrt war
  input.dataset.path = field.path;
  input.dataset.kind = field.kind;
  input.dataset.optional = field.optional ? "1" : "";
  input.id = inputId(field.path);
  input.addEventListener("change", () => {
    // Der Browser meldet change beim Verlassen des Feldes unter Umstaenden ein zweites Mal.
    // Ohne echte Aenderung wird nichts neu gezeichnet (sonst gingen Eingaben in neu gebauten Tabellen verloren)
    const before = JSON.stringify(getPath(cfg, field.path));
    if (!readInput(input) || JSON.stringify(getPath(cfg, field.path)) === before) return;
    if (field.path.startsWith("stack.")) renderPlaneTable();  // Ebenenzahl oder Dicke geaendert
    refresh();
  });
  return input;
}

/** Uebernimmt den Feldwert in cfg. false bei ungueltiger Eingabe (cfg bleibt dann unveraendert). */
function readInput(input) {
  const path = input.dataset.path;
  const text = input.value;
  if (text.trim() === "") {
    if (input.dataset.optional) { setPath(cfg, path, null); clearFieldError(input); return true; }
    if (!kindOf(input.dataset.kind).list) { markFieldError(input, "Wert erforderlich"); return false; }
  }
  const value = kindOf(input.dataset.kind).read(text);
  if (value === undefined) { markFieldError(input, "Ungültige Eingabe"); return false; }
  setPath(cfg, path, value);
  clearFieldError(input);
  return true;
}

function writeInputs() {
  for (const input of $$("[data-path]")) {
    const value = getPath(cfg, input.dataset.path);
    input.value = value == null ? "" : kindOf(input.dataset.kind).write(value);
  }
  for (const label of $$("[data-label-for]")) {
    const field = fieldByPath(label.dataset.labelFor);
    label.textContent = lenLabel(field.label, field.kind);
  }
  writeWeights();
  renderPlaneTable();
  renderObstacles();
  renderZones();
}

// --- Fehler -------------------------------------------------------------------------------------------
function markFieldError(input, message) {
  clearFieldError(input);
  input.classList.add("err");
  const box = document.createElement("div");
  box.className = "errmsg";
  box.textContent = message;
  input.insertAdjacentElement("afterend", box);
}

function clearFieldError(input) {
  input.classList.remove("err");
  const next = input.nextElementSibling;
  if (next && next.classList.contains("errmsg")) next.remove();
}

/** Zeigt Meldungen der Form "pfad. Text" am Feld und alle Meldungen im Banner. */
function showFieldErrors(errors) {
  $$(".err").forEach((node) => node.classList.remove("err"));
  $$(".errmsg").forEach((node) => node.remove());
  for (const message of errors) {
    const match = /^([\w.\[\]]+)\. (.*)$/.exec(message);
    const input = match && document.querySelector(`[data-path="${match[1]}"]`);
    if (input) markFieldError(input, match[2]);
  }
  const banner = $("#banner");
  banner.hidden = errors.length === 0;
  banner.innerHTML = errors.length ? "<ul>" + errors.map((e) => `<li>${esc(e)}</li>`).join("") + "</ul>" : "";
}
