"use strict";
// Motor Skizze. Zustand, Konstanten und Namensraum.
//
// Die Zeichenflaeche zeigt die Gehaeusekontur im Stangenrahmen (Stange im Ursprung). Der Constraint Solver
// laeuft im Python Kern (/api/sketch/*), diese Skripte sind nur Eingabe und Darstellung. Alle Funktionen
// der Skizze liegen im Namensraum Sketch (Dateien unter js/sketch, Reihenfolge siehe index.html).

const SK = {
  sk: { points: [], constraints: [] },  // aktuelle Skizze (Punkte gegen den Uhrzeigersinn, mm)
  res: null,  // letzte Antwort des Solvers
  attached: false,  // Skizze ist Teil der Konfiguration (sonst nur Vorschau des Rechtecks)
  sel: { p: new Set(), s: new Set() },  // ausgewaehlte Punkte und Seiten
  tool: null,  // "draw" waehrend des Zeichnens
  drawPts: [],
  cursor: null,
  view: { cx: -4, cy: -8, k: 0.12 },  // Mitte und mm pro Bildschirmpixel
  fitted: false,
  rot: 0,  // Drehvorschau in Grad
  hist: [],
  redo: [],
  hover: null,  // hervorgehobene Seiten und Punkte (Maus ueber einem Constraint)
  drag: null,
  msg: "",
  busy: 0,  // laufende Serveraufrufe (Tests warten auf 0)
  rendering: false,  // Tabellen werden neu aufgebaut, change Ereignisse dabei ignorieren
  lastDown: null,  // fuer die eigene Doppelklick Erkennung
};
window.__sk = SK;  // fuer Tests und Fehlersuche

const Sketch = {};  // Namensraum der Skizzenfunktionen

const SK_COLORS = { ok: "#2f6fed", full: "#2e9d4b", conflict: "#d32f2f", redundant: "#e08a00", sel: "#ff9800", grid: "#8884", axis: "#8888", gear: "#f28e2b", gearDark: "#a60", rotation: "#a58" };
const SK_HISTORY_LIMIT = 100;
const SK_EPS = 1e-9;

const skCount = () => SK.sk.points.length;
const skClearSelection = () => { SK.sel = { p: new Set(), s: new Set() }; };
/** Laenge in der Anzeigeeinheit (3 Nachkommastellen). */
const fmtLen = (mm) => String(Math.round((mm / UNIT[unit]) * 1000) / 1000);
const fmtDeg = (deg) => String(Math.round(deg * 100) / 100);
/** Neuer Constraint mit allen Feldern. */
const makeConstraint = (type, fields = {}) => ({ type, a: null, b: null, value: null, value2: null, ref: "rod", enabled: true, name: "", ...fields });

/** Aenderung im Verlauf merken (begrenzt, frueher wuchs der Verlauf ueber einige Wege unbegrenzt). */
function skPushHistory(snapshot) {
  SK.hist.push(snapshot);
  if (SK.hist.length > SK_HISTORY_LIMIT) SK.hist.shift();
  SK.redo = [];
}

/** Zaehlt einen asynchronen Vorgang als laufend (SK.busy), bis er fertig ist. */
const skTracked = (fn) => async (...args) => {
  SK.busy++;
  try { return await fn(...args); } finally { SK.busy--; }
};

/** Farbe nach Constraint Status. */
const statusColor = (status) => (status === "conflict" ? SK_COLORS.conflict : status === "redundant" ? SK_COLORS.redundant : SK_COLORS.ok);
const constraintStatus = (k) => (SK.res && SK.res.constraints && SK.res.constraints[k] ? SK.res.constraints[k].status : "ok");
