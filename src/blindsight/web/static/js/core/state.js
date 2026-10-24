"use strict";
// Gemeinsamer Zustand der Oberflaeche. cfg ist die Konfiguration im JSON Format des Kerns. Alle Laengen in mm.

let cfg = null;  // aktuelle Konfiguration (Tests greifen ueber den globalen Namen zu)
let schema = null;  // /api/schema (Felder, Constraint Typen, Exportformate)
let defaults = null;  // /api/default

/**
 * Feldarten des Schemas. read wandelt den Eingabetext in den Wert (mm) und liefert undefined bei
 * ungueltiger Eingabe, write wandelt den Wert in den Anzeigetext. length markiert Laengen (Einheit im Label).
 */
const parseNumber = (text) => { const v = parseFloat(text); return Number.isFinite(v) ? v : undefined; };
const parseInteger = (text) => { const v = Number(text); return Number.isInteger(v) ? v : undefined; };
function parseNumbers(text, parse) {
  const values = splitList(text).map(parse);
  return values.some((v) => v === undefined) ? undefined : values;
}
const KINDS = {
  len: { length: true, read: parseNumber, write: (v) => round(v) },
  num: { read: parseNumber, write: (v) => v },
  int: { read: parseInteger, write: (v) => v },
  text: { read: (t) => t, write: (v) => v },
  enum: { read: (t) => t, write: (v) => v },
  list: { list: true, read: (t) => parseNumbers(t, parseNumber), write: (v) => v.map((x) => round(x)).join(", ") },
  lenlist: { list: true, length: true, read: (t) => parseNumbers(t, parseNumber), write: (v) => v.map((x) => round(x)).join(", ") },
  listint: { list: true, read: (t) => parseNumbers(t, parseInteger), write: (v) => v.join(", ") },
  liststr: { list: true, read: (t) => splitList(t), write: (v) => v.join(", ") },
};
const kindOf = (name) => KINDS[name] || KINDS.text;
const lenLabel = (label, kind) => (kindOf(kind).length ? `${label} [mm]` : label);
