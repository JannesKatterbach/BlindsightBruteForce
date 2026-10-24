"use strict";
// Motor sketch. State, constants and namespace.
//
// The canvas shows the housing outline in the rod frame (rod at the origin). The constraint solver runs in
// the Python core (/api/sketch/*), these scripts only handle input and display. All functions of the sketch
// live in the namespace Sketch (files under js/sketch, order see index.html).

const SK = {
  sk: { points: [], constraints: [] },  // current sketch (points counter clockwise, mm)
  res: null,  // last answer of the solver
  attached: false,  // the sketch is part of the configuration (otherwise only a preview of the rectangle)
  sel: { p: new Set(), s: new Set() },  // selected points and sides
  tool: null,  // "draw" while drawing
  drawPts: [],
  cursor: null,
  view: { cx: -4, cy: -8, k: 0.12 },  // centre and mm per screen pixel
  fitted: false,
  rot: 0,  // rotation preview in degrees
  hist: [],
  redo: [],
  hover: null,  // highlighted sides and points (mouse over a constraint)
  drag: null,
  msg: "",
  busy: 0,  // running server calls (tests wait for 0)
  rendering: false,  // tables are being rebuilt, ignore change events meanwhile
  lastDown: null,  // for the own double click detection
};
window.__sk = SK;  // for tests and debugging

const Sketch = {};  // namespace of the sketch functions

const SK_COLORS = { ok: "#2f6fed", full: "#2e9d4b", conflict: "#d32f2f", redundant: "#e08a00", sel: "#ff9800", grid: "#8884", axis: "#8888", gear: "#f28e2b", gearDark: "#a60", rotation: "#a58" };
const SK_HISTORY_LIMIT = 100;
const SK_EPS = 1e-9;

const skCount = () => SK.sk.points.length;
const skClearSelection = () => { SK.sel = { p: new Set(), s: new Set() }; };
/** Length in mm (3 decimals). */
const fmtLen = (mm) => String(Math.round(mm * 1000) / 1000);
const fmtDeg = (deg) => String(Math.round(deg * 100) / 100);
/** New constraint with all fields. */
const makeConstraint = (type, fields = {}) => ({ type, a: null, b: null, value: null, value2: null, ref: "rod", enabled: true, name: "", ...fields });

/** Remember a change in the history (bounded, the history used to grow without limit on some paths). */
function skPushHistory(snapshot) {
  SK.hist.push(snapshot);
  if (SK.hist.length > SK_HISTORY_LIMIT) SK.hist.shift();
  SK.redo = [];
}

/** Count an asynchronous operation as running (SK.busy) until it is done. */
const skTracked = (fn) => async (...args) => {
  SK.busy++;
  try { return await fn(...args); } finally { SK.busy--; }
};

/** Colour by constraint status. */
const statusColor = (status) => (status === "conflict" ? SK_COLORS.conflict : status === "redundant" ? SK_COLORS.redundant : SK_COLORS.ok);
const constraintStatus = (k) => (SK.res && SK.res.constraints && SK.res.constraints[k] ? SK.res.constraints[k].status : "ok");
