// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: pages/setup)

import { state } from '../core/state.js';

import { escapeHtml, wirePopover } from '../core/dom.js';

import { observeWorkflowSteps, renderRail } from '../core/rail.js';

import { loadUpgradeData, renderSeasonChip } from '../core/season.js';

import { pollWorkerStatus } from '../core/workers.js';

import { renderCharChip } from '../setup/char-chip.js';

import { renderEnhancements } from '../setup/enhancements.js';

import { renderGear } from '../setup/gear.js';

import { updateCharCount, wire as wirePaste } from '../setup/paste.js';

import { wire as wireArmory } from '../setup/armory.js';

import { wire as wireRealms } from '../setup/realms.js';

import { generateInput } from '../setup/payload.js';

import { downloadLog, runSimulation, stopSimulation } from '../setup/run.js';

import { renderReviewPopover, selectionChanged, updateSummary } from '../setup/runbar.js';
import { fetchVersion } from '../core/version.js';

export const workflowContainer = document.getElementById('gear-workspace-container');

/* ---------- Rail stepper ---------- */
export function renderWorkflow() {
  workflowContainer.innerHTML = `
    <section class="panel-card workflow-panel full-width baseline-gear-panel" id="baseline-gear-panel"><div class="step-heading"><span class="num-badge num-badge-lg">2</span><div><h2>Baseline Gear · select candidates for ${escapeHtml(state.parsedData.char_name)}</h2><small>Grades are inferred from the export and refined with Wowhead. Toggle whole slots with Select all/none.</small></div></div><div id="gear-grid"></div></section>
    <section class="panel-card workflow-panel full-width" id="step-enhance"><div class="step-heading"><span class="num-badge num-badge-lg">3</span><div><h2>Select gems and enchantments</h2><small>Checked enhancements are included in generated variations; the ones you already wear are pre-checked as the baseline. You can also jump here from the chips in each gear slot above.</small></div></div><div id="enhancement-options" class="enhancement-options"></div></section>
    <section class="panel-card workflow-panel run-panel full-width" id="step-run"><div class="step-heading"><span class="num-badge num-badge-lg">4</span><div><h2>Run comparison</h2><small>Combinations update automatically as you change gear. Start the run from the bar at the bottom.</small></div></div><div id="run-progress" hidden><div class="progress-card" aria-live="polite"><div class="progress-head"><span class="progress-elapsed" id="run-elapsed">00:00</span><span class="progress-stage" id="run-stage"></span><span class="progress-eta" id="run-eta" hidden></span><button type="button" id="btn-stop" class="btn-danger">Stop run</button></div><div class="progress-track"><div class="progress-fill" id="run-progress-fill" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Simulation progress"></div></div><span class="progress-meta" id="run-progress-meta">Starting…</span></div></div><div id="run-result" hidden></div><div class="log-toolbar" id="log-toolbar" hidden><label class="log-follow"><input type="checkbox" id="log-follow" checked> Follow log</label><span class="char-count" id="log-lines">0 lines</span><button type="button" id="btn-log-download" class="btn-ghost">Download full log</button></div><pre id="simulation-log" class="simulation-log" role="log" aria-live="off" hidden></pre></section>
  `;
  renderGear();
  renderEnhancements();
  renderCharChip();
  document.getElementById('run-bar').hidden = false;
  // t_16e4f177 (leader ruling): with the gear list rendered, the skip link
  // must move focus past it to the run controls in one activation.
  const skipLink = document.querySelector('.skip-link');
  if (skipLink) {
    skipLink.href = '#btn-run';
    skipLink.textContent = 'Skip to run controls';
  }
  document.getElementById('btn-run').addEventListener('click', runSimulation);
  document.getElementById('fight-style').addEventListener('change', selectionChanged);
  document.getElementById('compare-mode').addEventListener('change', selectionChanged);
  document.getElementById('btn-stop').addEventListener('click', stopSimulation);
  document.getElementById('btn-log-download').addEventListener('click', downloadLog);
  wirePopover(document.getElementById('btn-review'),
    document.getElementById('review-popover'), renderReviewPopover);
  observeWorkflowSteps();
  updateSummary();
  void generateInput(true);
}

export function wire() {
renderRail();
observeWorkflowSteps();
updateCharCount();
// t_94a15fe3 split dropped these module wires (t_f9a0df27, QA t_23879205):
// paste/armory listener attach and the realms dropdown fetch.
wirePaste();
wireArmory();
wireRealms();
pollWorkerStatus();
setInterval(pollWorkerStatus, 15000);
loadUpgradeData().then(renderSeasonChip);
renderSeasonChip();
}


// entry module (script type=module, deferred boot): wire + version chip (t_94a15fe3, §3.1).
// Microtask boot: the paste<->pages import cycle resolves bodies-before-boot only
// when this file is the entry; non-entry importers (the .mjs realm harness) would
// otherwise boot mid-cycle and hit TDZ. Module scripts are deferred, so the DOM
// is parsed and the microtask runs before any user event can fire.
queueMicrotask(() => {
  try { wire(); fetchVersion(); }
  catch (err) { console.error('boot failed', err); }
});
