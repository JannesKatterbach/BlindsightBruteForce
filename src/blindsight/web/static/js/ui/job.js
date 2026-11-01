"use strict";
// Optimization run. Start, poll progress, live preview, cancel.

const STATUS_POLL_MS = 400;
const LIVE_POLL_MS = 1200;
const JOB_DONE_STATES = ["finished", "failed", "cancelled"];

let jobId = null;  // running or last finished run
let lastJobState = null;  // state of that run at the last status poll
let statusTimer = null, liveTimer = null;
let statusBusy = false;  // a status request is on its way (requests do not overlap)
const liveLatest = latestOnly((id) => api("/api/live/" + id));

function stopPolling() {
  clearInterval(statusTimer);
  clearInterval(liveTimer);
  statusTimer = liveTimer = null;
}

let jobRunning = false;

function setRunning(running) {
  jobRunning = running;
  updateStartButton();
  $("#btnCancel").disabled = !running;
}

async function startJob() {
  $("#errors").innerHTML = "";
  const { status, data } = await api("/api/start", cfg);
  if (status !== 200) {
    const errors = errorsOf(data);
    showFieldErrors(errors.length ? errors : [t("ui.job.error")]);
    $("#errors").innerHTML = "<ul>" + errors.map((e) => `<li>${esc(e)}</li>`).join("") + "</ul>";
    return;
  }
  showFieldErrors([]);
  jobId = data.job_id;
  lastJobState = "queued";
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
    if (id !== jobId) return;  // a new run was started meanwhile
    if (status !== 200) {  // run unknown (e.g. server restarted). Do not keep asking forever
      stopPolling();
      setRunning(false);
      $("#errors").textContent = errorsOf(data).join(" ") || t("ui.job.status_unavailable");
      return;
    }
    lastJobState = data.state;
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
    ["status", t("ui.job." + s.state)],
    ["phase", p ? p.phase : "-"],
    ["candidates", t("ui.progress.candidates_value", { n: fmtCount(s.candidates), max: fmtCount(s.max_candidates) })],
    ["elapsed", p ? t("ui.progress.elapsed_value", { elapsed: p.elapsed.toFixed(1), limit: s.time_limit }) : "-"],
    ["best_count", p ? p.best_count : "-"],
    ["best_score", p ? p.best_score.toFixed(3) : "-"],
    ["info", p ? p.message : ""],
  ];
  $("#progTable").innerHTML = rows.map(([k, v]) => `<tr><td>${esc(t("ui.progress." + k))}</td><td>${esc(v)}</td></tr>`).join("");
}

async function finishJob(s) {
  stopPolling();
  setRunning(false);
  $("#bar").style.width = "100%";
  if (s.state === "failed") { $("#errors").textContent = s.error; return; }
  await loadResult(0);
  switchTab("results");
}
