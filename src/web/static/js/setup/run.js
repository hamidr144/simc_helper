// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/run)
// t_37e0320e: run progress is a dedicated page on the results surface
// (results?run_task=), not a modal over the gear page. run.js keeps the one
// copy of the run-state + SSE polling; the panel hosts (#run-progress,
// #runview-log, #simulation-log, #run-result, …) moved to results.html with
// their ids intact, and js/pages/results.js imports this module. No logic
// duplicated: the gear page only starts runs and links back to them.

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { generateInput } from './payload.js';

import { setWorkflowStatus } from './runbar.js';
import { apiFetch } from '../core/api.js';

/* Active-run session: survives navigation so the gear page keeps a plain
   "View run" link, and a mid-run reload/re-entry re-attaches to the same
   stream. Live SSE joins are incremental (the server queues per viewer from
   connect time); the full log stays available via the download endpoint.
   Closing the tab mid-run is safe: the run is server-side and drafts persist
   per change — the session row is cleared when the run terminalizes. */
const ACTIVE_RUN_KEY = 'simc-active-run@1';
function saveActiveRun(run) {
  try { localStorage.setItem(ACTIVE_RUN_KEY, JSON.stringify(run)); } catch { /* storage off: link is a convenience */ }
}
export function loadActiveRun() {
  try {
    const run = JSON.parse(localStorage.getItem(ACTIVE_RUN_KEY));
    return run && run.task_id ? run : null;
  } catch { return null; }
}
export function clearActiveRun() { localStorage.removeItem(ACTIVE_RUN_KEY); }
export function activeRunHref(run) {
  const baseline = run.baseline ? `&baseline=${encodeURIComponent(run.baseline)}` : '';
  return `results?run_task=${encodeURIComponent(run.task_id)}&worker=${encodeURIComponent(run.worker_id || '')}${baseline}`;
}

function formatElapsed(ms) {
  const secs = Math.floor(ms / 1000);
  return `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;
}
function startRunProgress(combosLabel, startedAt) {
  stopRunProgress();
  state.simulationDone = false;
  state.runStartedAt = Number(startedAt) || Date.now();
  state.logLineCount = 0;
  state.logLines = [];
  lastProgressPct = 0;
  lastMetaAt = 0;
  const resultSlot = document.getElementById('run-result');
  if (resultSlot) { resultSlot.hidden = true; resultSlot.innerHTML = ''; }
  const combos = document.getElementById('runview-combos');
  if (combos) combos.textContent = combosLabel || '';
  const toolbar = document.getElementById('log-toolbar');
  if (toolbar) toolbar.hidden = false;
  document.getElementById('run-progress').hidden = false;
  setRunProgress(0, 'Starting…');
  setRunStage('');
  const renderElapsed = () => {
    document.getElementById('run-elapsed').textContent = formatElapsed(Date.now() - state.runStartedAt);
  };
  renderElapsed();
  state.runTimer = setInterval(renderElapsed, 1000);
}
function stopRunProgress() {
  if (state.runTimer) { clearInterval(state.runTimer); state.runTimer = null; }
}
// Stage markers printed by src/cli/sim_helper.py (STAGE 1/2/3, BASELINE).
const RUN_STAGE_LABELS = {
  'STAGE 1': 'Stage 1 of 3 · Fast filtering',
  'STAGE 2': 'Stage 2 of 3 · Refinement',
  'STAGE 3': 'Stage 3 of 3 · Final selection',
  'BASELINE': 'Baseline only',
};
let lastProgressPct = 0;
let lastMetaAt = 0;
function updateRunProgressMeta(text) {
  const line = String(text).trim();
  if (!line) return;
  const progress = line.match(/Progress:\s*(\d+)%\s*\(([^)]+)\)/);
  if (progress) {
    setRunProgress(Number(progress[1]), `${progress[1]}% · ${progress[2]} profiles`);
    return;
  }
  for (const marker of Object.keys(RUN_STAGE_LABELS)) {
    if (line.includes(marker)) { setRunStage(RUN_STAGE_LABELS[marker]); return; }
  }
  setRunMeta(line.length > 90 ? `${line.slice(0, 90)}…` : line);
}
function setRunProgress(pct, meta) {
  lastProgressPct = Math.min(100, Math.max(0, pct));
  const fill = document.getElementById('run-progress-fill');
  if (fill) {
    fill.style.width = `${lastProgressPct}%`;
    fill.setAttribute('aria-valuenow', String(lastProgressPct));
  }
  setRunMeta(meta);
  updateRunEta();
}
function setRunStage(label) {
  const el = document.getElementById('run-stage');
  if (el) el.textContent = label;
}
// aria-live polite throttled to <=1 update/s (doc 4.2) so fast log lines
// never spam screen readers.
function setRunMeta(text) {
  const now = Date.now();
  if (now - lastMetaAt < 1000) return;
  lastMetaAt = now;
  const meta = document.getElementById('run-progress-meta');
  if (meta) meta.textContent = text;
}
// t_2ab8f3be: log rendering was O(n^2) (textContent += per line) and froze
// the tab on long runs. Full lines stay in state.logLines for the download button;
// the DOM shows only the last LOG_RENDER_CAP lines, repainted once per frame.
const LOG_RENDER_CAP = 2000;
function pushLogLines(lines) {
  state.logLines.push(...lines);
  state.logLineCount += lines.length;
  if (!state.logRenderQueued) {
    state.logRenderQueued = true;
    requestAnimationFrame(renderLogTail);
  }
}
function renderLogTail() {
  state.logRenderQueued = false;
  const log = document.getElementById('simulation-log');
  if (!log) return;
  log.textContent = state.logLines.slice(-LOG_RENDER_CAP).join('\n') + '\n';
  const follow = document.getElementById('log-follow');
  if (!follow || follow.checked) log.scrollTop = log.scrollHeight;
}
export function downloadLog() {
  const blob = new Blob([state.logLines.join('\n')], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `simc-run-${state.currentTaskId || Date.now()}.log`;
  a.click();
  URL.revokeObjectURL(a.href);
}
function updateRunEta() {
  const eta = document.getElementById('run-eta');
  if (!eta) return;
  // ETA only after 5% so the first noisy samples do not skew it (doc 4.2).
  if (lastProgressPct < 5 || !state.runStartedAt) { eta.hidden = true; return; }
  const remainSec = Math.round((Date.now() - state.runStartedAt) * (100 - lastProgressPct) / lastProgressPct / 1000);
  eta.hidden = false;
  eta.textContent = remainSec < 60 ? `~${remainSec}s left` : `~${Math.round(remainSec / 60)} min left`;
}
export async function stopSimulation() {
  let token = window.localStorage.getItem('simc-admin-token') || '';
  const entered = window.prompt(
    'Stopping a simulation requires the master admin token (ADMIN_TOKEN):', token);
  if (entered === null) return;
  token = entered.trim();
  try {
    const response = await apiFetch('api/stop-simulation', {
      method: 'POST', headers: { 'X-Admin-Token': token }
    });
    if (response.status === 403) {
      setWorkflowStatus('The admin token was rejected.');
      window.localStorage.removeItem('simc-admin-token');
      return;
    }
    const data = await response.json();
    window.localStorage.setItem('simc-admin-token', token);
    setWorkflowStatus(data.message || 'Stop requested.');
  } catch (error) {
    setWorkflowStatus(`Could not stop simulation: ${error.message}`);
  }
}
/* t_37e0320e: attach to a run on the run page. This is the runSimulation
   SSE block moved, not duplicated: stream, progress parsing and the failure
   card all live here. onDone fires on done, error and on a stream that
   closes early — a fresh EventSource for a finished task 404s (the master
   frees the queue), so the results page falls back to fetching the saved
   report. */
export function watchRun({ taskId, workerId, combosLabel, startedAt, onDone }) {
  state.currentTaskId = taskId;
  startRunProgress(combosLabel, startedAt);
  const events = new EventSource(`api/simulation/stream/${taskId}?worker_id=${encodeURIComponent(workerId || '')}`);
  events.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === 'log') {
      pushLogLines([message.text]);
      updateRunProgressMeta(message.text);
    }
    if (message.type === 'log_batch') {
      pushLogLines(message.lines);
    }
    if (message.type === 'log' || message.type === 'log_batch') {
      const linesEl = document.getElementById('log-lines');
      if (linesEl) linesEl.textContent = `${state.logLineCount.toLocaleString()} lines`;
    }
    if (message.type === 'done' || message.type === 'error') {
      stopRunProgress();
      document.getElementById('run-progress').hidden = true;
      clearActiveRun();
      if (message.type === 'done') state.simulationDone = true;
      else showRunFailureCard(message);
      events.close();
      if (onDone) onDone(message);
    }
  };
  events.onerror = () => {
    events.close();
    stopRunProgress();
    clearActiveRun();
    if (onDone) onDone({ type: 'closed' });
  };
}
export async function runSimulation() {
  // t_4485565b: generate even when the client-side estimate is 0 — a
  // 0-candidate input is a valid baseline current-gear run.
  if (!state.generatedInput) await generateInput();
  if (!state.generatedInput) return;
  setWorkflowStatus('Looking for an idle worker…');
  try {
    const response = await apiFetch(`api/run-simulation?input_id=${encodeURIComponent(state.generatedInput.input_id)}`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Simulation could not start');
    state.currentTaskId = data.task_id;
    const run = {
      task_id: data.task_id,
      worker_id: data.worker_id,
      started_at: Date.now(),
      combos: `${document.getElementById('combo-count').textContent} ${document.getElementById('combo-word').textContent}`,
      baseline: state.parsedData?.char_name || '',
    };
    saveActiveRun(run);
    setWorkflowStatus(`Simulation ${data.task_id} is running on worker ${data.worker_id}.`);
    // t_37e0320e: navigate to the run page instead of opening a panel over
    // the gear grid. Gear drafts persist per change (draft.js) and the run
    // itself is server-side, so navigation is safe mid-flight.
    window.location.href = activeRunHref(run);
  } catch (error) {
    setWorkflowStatus(`Could not start simulation: ${error.message}`);
  }
}

function showRunFailureCard(message) {
  const slot = document.getElementById('run-result');
  setWorkflowStatus(message.text || 'The simulation stopped unexpectedly.');
  if (!slot) return;
  const tail = state.logLines.slice(-12).join('\n');
  slot.hidden = false;
  slot.innerHTML = `<div class="success-card is-failed"><span class="success-icon" aria-hidden="true">\u2715</span><div><h3>Run failed</h3><p>${escapeHtml(message.text || 'The simulation stopped unexpectedly \u2014 see the log below.')}</p>${tail ? `<pre class="success-log-tail">${escapeHtml(tail)}</pre>` : ''}<div class="success-actions"><button type="button" data-open-log class="btn-ghost">Open log</button><a href="./" class="btn-ghost">Back to gear</a></div></div></div>`;
  slot.querySelector('[data-open-log]').addEventListener('click', () => document.getElementById('simulation-log')?.scrollIntoView({ block: 'start' }));
}
