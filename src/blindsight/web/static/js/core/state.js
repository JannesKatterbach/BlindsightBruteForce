"use strict";
// Shared state of the UI. cfg is the configuration in the JSON format of the core. All lengths in mm.

let cfg = null;  // current configuration (tests access it through the global name)
let schema = null;  // /api/schema (fields, constraint types, export formats, languages)
let defaults = null;  // /api/default

/**
 * Field kinds of the schema. read turns the input text into the value (mm) and returns undefined for
 * invalid input, write turns the value into the shown text. length marks lengths (unit in the label).
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
