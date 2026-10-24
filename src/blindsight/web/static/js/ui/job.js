"use strict";
// Optimierungslauf. Starten, Fortschritt abfragen, Live Vorschau, Abbrechen.

const STATUS_POLL_MS = 400;
const LIVE_POLL_MS = 1200;
const JOB_STATE_LABELS = { queued: "wartet", running: "läuft", finished: "fertig", failed: "Fehler", cancelled: "abgebrochen" };
const JOB_DONE_STATES = ["finished", "failed", "cancelled"];

let jobId = null;  // laufender oder zuletzt beendeter Lauf
let statusTimer = null, liveTimer = null;
let statusBusy = false;  // eine Statusabfrage ist unterwegs (Abfragen ueberlappen sich nicht)
const liveLatest = latestOnly((id) => api("/api/live/" + id));

function stopPolling() {
  clearInterval(statusTimer);
  clearInterval(liveTimer);
  statusTimer = liveTimer = null;
}

function setRunning(running) {
  $("#btnStart").disabled = running;
  $("#btnCancel").disabled = !running;
}

async function startJob() {
  $("#errors").innerHTML = "";
  const { status, data } = await api("/api/start", cfg);
  if (status !== 200) {
    const errors = errorsOf(data);
    showFieldErrors(errors.length ? errors : ["Fehler"]);
    $("#errors").innerHTML = "<ul>" + errors.map((e) => `<li>${esc(e)}</li>`).join("") + "</ul>";
    return;
  }
  showFieldErrors([]);
  jobId = data.job_id;
  setRunning(true);
  stopPolling();
  statusTimer = setInterval(pollStatus, STATUS_POLL_MS);
  liveTimer = setInterval(pollLive, LIVE_POLL_MS);
  pollStatus();
  pollLive();
}

function cancelJob() {
  if (jobId) api("/api/cancel/" + jobId, {});
}

async function pollLive() {
  if (!jobId) return;
  const response = await liveLatest(jobId);
  if (response && response.data && response.data.geometry) drawPlan($("#liveView"), response.data.geometry, null, true);
}

async function pollStatus() {
  if (statusBusy || !jobId) return;
  statusBusy = true;
  const id = jobId;
  try {
    const { status, data } = await api("/api/status/" + id);
    if (id !== jobId) return;  // inzwischen wurde ein neuer Lauf gestartet
    if (status !== 200) {  // Lauf unbekannt (z.B. Server neu gestartet). Nicht endlos weiterfragen
      stopPolling();
      setRunning(false);
      $("#errors").textContent = errorsOf(data).join(" ") || "Status nicht abrufbar";
      return;
    }
    renderProgress(data);
    if (JOB_DONE_STATES.includes(data.state)) await finishJob(data);
  } finally {
    statusBusy = false;
  }
}

function renderProgress(s) {
  const p = s.progress;
  $("#bar").style.width = (p ? Math.round(p.fraction * 100) : 0) + "%";
  const rows = [
    ["Status", JOB_STATE_LABELS[s.state] || s.state],
    ["Phase", p ? p.phase : "-"],
    ["Untersuchte Kandidaten", s.candidates.toLocaleString("de") + " von " + s.max_candidates.toLocaleString("de")],
    ["Verstrichene Zeit", p ? p.elapsed.toFixed(1) + " s von " + s.time_limit + " s" : "-"],
    ["Beste Anzahl bisher", p ? p.best_count : "-"],
    ["Beste Bewertung bisher", p ? p.best_score.toFixed(3) : "-"],
    ["Info", p ? p.message : ""],
  ];
  $("#progTable").innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
}

async function finishJob(s) {
  stopPolling();
  setRunning(false);
  $("#bar").style.width = "100%";
  if (s.state === "failed") { $("#errors").textContent = s.error; return; }
  await loadResult(0);
  switchTab("results");
}
