"use strict";
// General helpers without domain logic. Classic scripts without a build step, order see index.html.

const $ = (selector) => document.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const SVG_NS = "http://www.w3.org/2000/svg";

// Colours of the motor layers (same table as in the SVG export)
const PLANE_COLORS = ["#4e79a7", "#f28e2b", "#59a14f", "#b07aa1", "#edc948", "#76b7b2", "#ff9da7", "#9c755f"];
const col = (plane) => PLANE_COLORS[(plane - 1) % PLANE_COLORS.length];
// Rods take the text colour, so they stay visible in the light and the dark mode
const COLORS = { bad: "#e00", tight: "#e08a00", rod: "currentColor", obstacle: "#bbb", obstacleStroke: "#555", g0: "#a1887f", gear: "#f28e2b" };
/** Label of a part kind (housing, gear, rod, obstacle). */
const kindLabel = (kind) => t("ui.kind." + kind);

/** Create an SVG element with attributes and optionally append it. */
function el(name, attrs = {}, parent) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

/** Board in top view (origin at the bottom left, y drawn upwards). The edge strip for motors light between
 * the keep out edge and the area of the holes, the area of the holes dashed. */
function drawBoardFrame(svg, w, h, edgeMargin, rodMargin, strokeWidth) {
  el("rect", { x: 0, y: -h, width: w, height: h, fill: "none", stroke: "currentColor", "stroke-width": strokeWidth }, svg);
  const frame = (m) => `M ${m} ${-h + m} H ${w - m} V ${-m} H ${m} Z`;
  if (rodMargin > edgeMargin) el("path", { d: frame(edgeMargin) + " " + frame(rodMargin), "fill-rule": "evenodd", fill: COLORS.gear, "fill-opacity": 0.16, "pointer-events": "none", class: "edgeStrip" }, svg);
  if (rodMargin > 0) el("path", { d: frame(rodMargin), fill: "none", stroke: "#888", "stroke-dasharray": `${w / 120} ${w / 120}`, "stroke-width": strokeWidth / 1.5, "pointer-events": "none", class: "holeArea" }, svg);
}

/** SVG text with content. */
function svgText(parent, attrs, content) {
  const node = el("text", attrs, parent);
  node.textContent = content;
  return node;
}

/** Escape text for HTML (numbers and null are allowed too). */
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Round a number. Anything that is not a finite number comes back unchanged. */
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

/** List from text (separated by comma, semicolon or space). */
const splitList = (text) => String(text).split(/[,; ]+/).filter(Boolean);

/** Placeholder of an empty table (instead of a lone header row). */
const emptyTable = (key = "ui.table.empty") => `<p class="hint">${esc(t(key))}</p>`;
/** Delete button of a table row. */
const deleteButton = (attr, value) => `<button ${attr}="${esc(value)}" title="${esc(t("ui.table.delete"))}" aria-label="${esc(t("ui.table.delete"))}">×</button>`;

/** Offer a file for download. */
function download(name, content, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(content instanceof Blob ? content : new Blob([content], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

/** Reset a file input so that the same file triggers a change event again. */
/** Download data as a formatted JSON file. */
const downloadJson = (name, data) => download(name, JSON.stringify(data, null, 2), "application/json");

/** Call handler with the file chosen in a file input. The input is reset, so the same file works again. */
function onFile(selector, handler) {
  $(selector).addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) await handler(file);
  });
}

// --- Server ----------------------------------------------------------------------------------------
const JSON_HEADERS = { "Content-Type": "application/json" };  // the server rejects other types for POST
/** Headers of every request. The server answers in the language of the UI. */
const requestHeaders = (extra = {}) => ({ "X-Language": currentLanguage, ...extra });

/** GET (without body) or POST with JSON. Returns {status, data}. */
async function api(path, body) {
  const options = body === undefined ? { headers: requestHeaders() } : { method: "POST", headers: requestHeaders(JSON_HEADERS), body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const type = response.headers.get("Content-Type") || "";
  const data = type.includes("json") ? await response.json() : await response.text();
  return { status: response.status, data };
}

/** Error messages of a response as a list (the server sends {error, errors}). */
const errorsOf = (data) => (data && (data.errors || (data.error ? [data.error] : []))) || [];

/**
 * Only the answer of the newest call counts. Returns a function that is called like fn and returns
 * undefined for outdated calls (late answers do not overwrite newer ones).
 */
function latestOnly(fn) {
  let seq = 0;
  return async (...args) => {
    const mine = ++seq;
    const result = await fn(...args);
    return mine === seq ? result : undefined;
  };
}

/** Run asynchronous tasks one after another (no overtaking). */
function serialQueue() {
  let tail = Promise.resolve();
  return (task) => {
    const run = tail.then(task, task);
    tail = run.catch(() => {});
    return run;
  };
}
