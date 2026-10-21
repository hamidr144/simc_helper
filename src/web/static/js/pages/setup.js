// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: pages/setup)
// RED-3: the rail stepper is deleted and the workflow panels are static HTML;
// renderWorkflow() is now "refresh the workspace after a character lands",
// plus the §10 boot restore (draft rehydration + results apply-back queue).

import { state } from '../core/state.js';

import { wirePopover } from '../core/dom.js';

import { wireTheme } from '../core/theme.js';

import { loadUpgradeData, renderSeasonChip } from '../core/season.js';

import { pollWorkerStatus } from '../core/workers.js';

import { renderCharChip } from '../setup/char-chip.js';

import { renderEnhancements } from '../setup/enhancements.js';

import { renderGear } from '../setup/gear.js';

import { updateCharCount, wire as wirePaste } from '../setup/paste.js';

import { wire as wireArmory } from '../setup/armory.js';

import { wire as wireRealms } from '../setup/realms.js';

import { applyDraftToState, applyPayloadToState, consumeApply, loadDrafts } from '../setup/draft.js';

import { persistDraft } from '../setup/draft.js';

import { generateInput } from '../setup/payload.js';

import { downloadLog, runSimulation, stopSimulation } from '../setup/run.js';

import { renderReviewPopover, selectionChanged, setWorkflowStatus, updateSummary } from '../setup/runbar.js';
import { fetchVersion } from '../core/version.js';

/* Boot restore (§10), held until a character lands: apply-back from the
   results page wins over the newest draft; both only for their own char. */
const pendingBoot = { apply: consumeApply(), drafts: loadDrafts() };

export function afterSelectionsInit() {
  const char = state.parsedData?.char_name;
  if (!char) return;
  const note = document.getElementById('draft-note');
  if (pendingBoot.apply?.payload?.char_name === char) {
    applyPayloadToState(pendingBoot.apply.payload);
    pendingBoot.apply = null;
    if (note) note.textContent = 'applied your run selection ✓';
  } else {
    pendingBoot.apply = null;
    const draft = pendingBoot.drafts.find(d => d.parsedData.char_name === char);
    if (draft) {
      applyDraftToState(draft);
      if (note) note.textContent =
        `draft restored (saved ${new Date(draft.savedAt * 1000).toLocaleString()})`;
    }
  }
  pendingBoot.drafts = [];
}

/* Called by paste.js after each successful export/Armory load. */
export function renderWorkflow() {
  afterSelectionsInit();
  renderGear();
  renderEnhancements();
  renderCharChip();
  // t_16e4f177 (leader ruling): skip link must reach the run controls in one
  // activation now that the gear list renders above them.
  const skipLink = document.querySelector('.skip-link');
  if (skipLink) {
    skipLink.href = '#btn-run';
    skipLink.textContent = 'Skip to run controls';
  }
  updateSummary();
  void generateInput(true);
  persistDraft();
}

export function wire() {
  wireTheme(document.querySelector('.pal .seg'));
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
  document.getElementById('btn-run').addEventListener('click', runSimulation);
  document.getElementById('fight-style').addEventListener('change', selectionChanged);
  document.getElementById('compare-mode').addEventListener('change', selectionChanged);
  document.getElementById('btn-stop').addEventListener('click', stopSimulation);
  document.getElementById('btn-log-download').addEventListener('click', downloadLog);
  wirePopover(document.getElementById('btn-review'),
    document.getElementById('review-popover'), renderReviewPopover);
  // §10: fresh draft hint before any import (offer rehydration path).
  if (pendingBoot.drafts.length) {
    const d = pendingBoot.drafts[0];
    const note = document.getElementById('draft-note');
    if (note) {
      note.textContent =
        `draft: ${d.parsedData.char_name} (saved ${new Date(d.savedAt * 1000).toLocaleString()}) — paste or load that character to restore`;
    }
    setWorkflowStatus(`You have a saved draft for ${d.parsedData.char_name}. ` +
      'Loading that character restores your selection automatically.');
  }
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
