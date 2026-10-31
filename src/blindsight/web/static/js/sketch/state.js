"use strict";
// Motor sketch modelled after Onshape. State, constants and namespace.
//
// The canvas shows the motor in top view in the rod frame (rod at the origin). The sketch holds points,
// entities (point, line, circle, arc) and constraints (relations and dimensions), see
// src/blindsight/sketch/entities.py. The constraint solver runs in the Python core (/api/sketch/solve),
// these scripts handle drawing, selection and display. All functions live in the namespace Sketch
// (files under js/sketch, order see index.html).
//
// References are texts like in the core. "p3" point, "e2" entity, "o" origin, "c5" a constraint (UI only).

const SK = {
  sk: { points: [], entities: [], constraints: [] },  // current sketch (mm)
  res: null,  // last answer of the solver
  attached: false,  // the sketch is part of the configuration (otherwise a preview of the motor fields)
  sel: new Set(),  // selected references (points, entities, constraints)
  tool: "select",  // select, line, rect, circle, arc, gear, dimension or the name of a relation
  draft: null,  // drawing in progress {tool, clicks: [{x, y, snap}], chainStart}
  pick: [],  // references collected by a relation or dimension tool
  dimPlace: null,  // dimension waiting for its position {type, refs}
  cursor: null,  // mouse position in mm
  snap: null,  // inference at the cursor {x, y, ref, kind}
  hover: null,  // reference under the mouse or highlighted by the list
  view: { cx: -4, cy: -10, k: 0.12 },  // centre and mm per screen pixel
  fitted: false,
  rot: 0,  // rotation preview in degrees
  hist: [],
  redo: [],
  drag: null,
  msg: "",
  busy: 0,  // running server calls (tests wait for 0)
  rendering: false,  // the list is being rebuilt, ignore change events meanwhile
  lastDown: null,  // for the own double click detection
};
window.__sk = SK;  // for tests and debugging

const Sketch = {};  // namespace of the sketch functions

// Colours like Onshape. Free geometry blue, fully defined geometry in the text colour, conflicts red
const SK_COLORS = {
  free: "#1f6fd1", defined: "currentColor", conflict: "#d32f2f", redundant: "#e08a00", sel: "#ff9800", hover: "#f5b041",
  grid: "#8883", axis: "#8888", gear: "#f28e2b", gearDark: "#a65e00", hull: "#8a8f99", rotation: "#a58", snap: "#16a085",
  dimension: "var(--mut)", rod: "#556",
};
const SK_HISTORY_LIMIT = 100;
const SK_EPS = 1e-9;
const SK_POINT_PX = 7;  // hit radius of points on the screen
const SK_CURVE_PX = 8;  // hit distance of lines and curves
const SK_SNAP_PX = 10;  // distance at which drawing snaps to points and curves
const SK_AXIS_SNAP_DEG = 4;  // a new line closer than this to horizontal or vertical gets the relation

const DRAW_TOOLS = ["line", "rect", "circle", "arc", "gear"];
const RELATIONS = ["coincident", "horizontal", "vertical", "parallel", "perpendicular", "equal", "midpoint", "concentric", "fix"];
const ENTITY_POINT_COUNT = { point: 1, line: 2, circle: 1, arc: 3 };

/** Length in mm (3 decimals) and angle in degrees (2 decimals) for display. */
const fmtLen = (mm) => String(Math.round(mm * 1000) / 1000);
const fmtDeg = (deg) => String(Math.round(deg * 100) / 100);

/** New constraint with all fields. */
const makeConstraint = (type, refs, fields = {}) => ({ type, refs, value: null, at: null, enabled: true, name: "", label: null, ...fields });

/** Remember a change in the history (bounded). */
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

/** Status of constraint k from the last solve (ok, redundant, conflict, disabled). */
const constraintStatus = (k) => (SK.res && SK.res.constraints && SK.res.constraints[k] ? SK.res.constraints[k].status : "ok");
const statusColor = (status) => (status === "conflict" ? SK_COLORS.conflict : status === "redundant" ? SK_COLORS.redundant : SK_COLORS.free);
