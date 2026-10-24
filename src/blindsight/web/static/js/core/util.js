"use strict";
// Allgemeine Hilfen ohne Fachbezug. Klassische Skripte ohne Build Schritt, Reihenfolge siehe index.html.

const $ = (selector) => document.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const SVG_NS = "http://www.w3.org/2000/svg";

// Farben der Motorebenen (gleiche Tabelle wie im SVG Export)
const PLANE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"];
const col = (plane) => PLANE_COLORS[(plane - 1) % PLANE_COLORS.length];
const COLORS = { bad: "#e00", tight: "#e08a00", rod: "#222", obstacle: "#bbb", obstacleStroke: "#555", g0: "#a1887f", gear: "#f28e2b" };
const KIND_LABELS = { housing: "Motor", gear: "Zahnrad", rod: "Stange", obstacle: "Hindernis" };

/** SVG Element mit Attributen anlegen und optional anhaengen. */
function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

/** SVG Text mit Inhalt. */
function svgText(parent, attrs, content) {
  const node = el("text", attrs, parent);
  node.textContent = content;
  return node;
}

/** Text fuer HTML maskieren (auch Zahlen und null sind erlaubt). */
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Zahl runden. Alles, was keine endliche Zahl ist, kommt unveraendert zurueck. */
function round(value, digits = 4) {
  if (typeof value !== "number" || !Number.isFinite(value)) return value;
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

const clone = (obj) => JSON.parse(JSON.stringify(obj));
const getPath = (obj, path) => path.split(".").reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
function setPath(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  keys.reduce((acc, key) => acc[key], obj)[last] = value;
}

/** Liste aus Text (Trenner Komma, Semikolon oder Leerzeichen). */
const splitList = (text) => String(text).split(/[,; ]+/).filter(Boolean);

/** Datei zum Herunterladen anbieten. */
function download(name, content, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(content instanceof Blob ? content : new Blob([content], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/** Dateiauswahl zuruecksetzen, damit dieselbe Datei erneut ein change Ereignis ausloest. */
function resetFileInput(input) { input.value = ""; }

// --- Server ----------------------------------------------------------------------------------------
const JSON_HEADERS = { "Content-Type": "application/json" };  // der Server weist andere Typen bei POST ab

/** GET (ohne body) oder POST mit JSON. Rueckgabe {status, data}. */
async function api(path, body) {
  const options = body === undefined ? {} : { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const type = response.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  return { status: response.status, data };
}

/** Fehlermeldungen einer Antwort als Liste (Server liefert {error, errors}). */
const errorsOf = (data) => (data && (data.errors || (data.error ? [data.error] : []))) || [];

/**
 * Nur die Antwort des neuesten Aufrufs zaehlt. Liefert eine Funktion, die wie fn aufgerufen wird
 * und fuer veraltete Aufrufe undefined zurueckgibt (spaete Antworten ueberschreiben keine neueren).
 */
function latestOnly(fn) {
  let seq = 0;
  return async (...args) => {
    const mine = ++seq;
    const result = await fn(...args);
    return mine === seq ? result : undefined;
  };
}

/** Fuehrt asynchrone Aufgaben nacheinander aus (keine Ueberholungen). */
function serialQueue() {
  let tail = Promise.resolve();
  return (task) => {
    const run = tail.then(task, task);
    tail = run.catch(() => {});
    return run;
  };
}
