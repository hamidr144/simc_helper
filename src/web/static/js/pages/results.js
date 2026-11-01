// js/pages/results.js — results page entry (I-37): fetch with retry, chip
// batch pre-resolve, render. Ported from results.js by t_94a15fe3.
// t_37e0320e: ?run_task= enters the dedicated run page — the run panel
// (hosts moved from the gear page's dialog; logic lives in js/setup/run.js,
// imported not duplicated) streams live progress here and the finished
// results render in place on done. ?task_id= stays the plain report view.
import { apiFetch } from '../core/api.js';
import {
  pickBaseline, changesFromBaseline, bestGearChanges,
} from '../results/model.js';
import { resolveChips } from '../results/chips.js';
import { renderResults, renderRuns } from '../results/table.js';
import { renderHeroExtras } from '../results/hero.js';
import { wireTheme } from '../core/theme.js';
import { fetchVersion } from '../core/version.js';
import { watchRun, loadActiveRun, clearActiveRun, downloadLog, stopSimulation } from '../setup/run.js';

wireTheme(document.querySelector('.pal .seg'));
fetchVersion();

const query = new URLSearchParams(window.location.search);
const runTask = query.get('run_task');
const taskId = query.get('task_id') || runTask;
const els = {
  subtitle: document.getElementById('results-subtitle'),
  baselineName: query.get('baseline'),
  taskId,
};

// t_37e0320e: wire the run panel's controls (hosts live in results.html).
document.getElementById('btn-stop').addEventListener('click', stopSimulation);
document.getElementById('btn-log-download').addEventListener('click', downloadLog);

async function fetchResults(task = taskId, attempt = 0) {
  if (!task) {
    els.subtitle.textContent = 'No simulation task was provided.';
    return;
  }
  els.taskId = task;
  renderHeroExtras(task);
  // §4 Runs panel (ruling O-4): independent fetch — a failure leaves the
  // panel hidden, never blocks results.
  apiFetch(`api/history?limit=3`).then(async (response) => {
    const data = await response.json().catch(() => null);
    if (response.ok && data?.status === 'success') renderRuns(data.runs || [], task);
  }).catch(() => {});
  try {
    const response = await apiFetch(`api/get-results?task_id=${encodeURIComponent(task)}`);
    const data = await response.json();
    if (response.ok && data.status === 'success' && data.results?.length) {
      const healthy = data.results.filter(result => result && Number(result.dps) > 0);
      const { baseline } = pickBaseline(healthy, els.baselineName);
      // A2 (MGE-2 §2): below-rank-1 diffs are described against BEST, and the
      // best-combination ids join the same batched chip resolve.
      const rankedAll = healthy.filter(result => result !== baseline)
        .sort((a, b) => b.dps - a.dps);
      const ranked = baseline
        ? rankedAll.filter(result => changesFromBaseline(result, baseline).length)
        : rankedAll;
      const topRow = ranked[0] || baseline;
      await resolveChips(ranked, topRow, topRow ? bestGearChanges(topRow, baseline) : []);
      // R2: /api/config feeds the dashed rec chips and the set gem line;
      // on failure both render as honest absence.
      try {
        const configResponse = await apiFetch('api/config');
        els.appConfig = configResponse.ok ? await configResponse.json() : null;
      } catch { els.appConfig = null; }
      return renderResults(data.results, data.mode, els);
    }
    if (attempt < 5) return setTimeout(() => fetchResults(task, attempt + 1), 1200);
    els.subtitle.textContent = data.message || 'The report could not be loaded.';
  } catch {
    if (attempt < 5) return setTimeout(() => fetchResults(task, attempt + 1), 1200);
    els.subtitle.textContent = 'The report could not be loaded.';
  }
}

if (runTask) {
  // t_37e0320e run page: live progress first, results in place on done.
  els.subtitle.textContent = 'Running — the ranked results will appear here.';
  document.getElementById('run-panel').hidden = false;
  // The session row survives navigation/re-entry, so elapsed + combo count
  // keep their true start even after a mid-run reload.
  const session = loadActiveRun();
  const meta = session && session.task_id === runTask ? session : {};
  watchRun({
    taskId: runTask,
    workerId: query.get('worker') || meta.worker_id || '',
    combosLabel: meta.combos,
    startedAt: meta.started_at,
    onDone: () => {
      // Terminal state (done, error, or stream closed on an already-finished
      // task): the run is over, so the session link is stale — clear it and
      // render the saved report below the panel.
      clearActiveRun();
      els.subtitle.textContent = 'Your ranked results.';
      document.getElementById('run-panel-title').textContent = 'Simulation finished';
      document.getElementById('run-progress').hidden = true;
      const log = document.getElementById('simulation-log');
      if (!(log.textContent || '').trim()) { // re-entry: no replayed stream
        log.hidden = true;
        document.getElementById('log-toolbar').hidden = true;
      }
      fetchResults(runTask);
    },
  });
} else {
  fetchResults();
}
