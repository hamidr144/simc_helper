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

import { validateAddedItems } from '../setup/add-item.js';

import { generateInput } from '../setup/payload.js';

import { runSimulation, loadActiveRun, activeRunHref } from '../setup/run.js';

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
      // t_2fa2e1fe: purge pre-guard add-by-ID pseudo-items (set bonuses,
      // aspects) restored from the draft; every fetch failure keeps the row.
      void validateAddedItems();
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
  // t_76a0ceb9 directive 5: enhancements appear only once a gear import is
  // present (renderWorkflow runs only after a successful one). The log area
  // left the page with t_37e0320e — run progress is the results-page run page.
  document.getElementById('gear-step').hidden = false;
  document.getElementById('enh-card').hidden = false;
  // R7 (ruling D-4): the import band collapses once a character has loaded;
  // btn-new-export re-opens it (paste.js).
  const importBand = document.getElementById('import-details');
  if (importBand) importBand.open = false;
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

/* t_d671cd7c directive 6: header profile dropdown — native button trigger
   (Enter/Space), ArrowDown into the menu, Escape closes and restores focus,
   outside click closes. aria-expanded tracks the open state. */
function wireProfileMenu() {
  const trigger = document.getElementById('btn-profile-menu');
  const panel = document.getElementById('profile-menu-panel');
  const setMenu = open => {
    panel.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
  };
  setMenu(false);
  trigger.addEventListener('click', () => setMenu(panel.hidden));
  trigger.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setMenu(true);
      panel.querySelector('a')?.focus();
    }
  });
  panel.addEventListener('keydown', event => {
    if (event.key === 'Escape') { setMenu(false); trigger.focus(); }
  });
  document.addEventListener('click', event => {
    if (!panel.hidden && !event.target.closest('.profile-menu')) setMenu(false);
  });
}

export function wire() {
  wireTheme(document.querySelector('.pal .seg'));
  wireProfileMenu();
  updateCharCount();
  // t_94a15fe3 split dropped these module wires (t_f9a0df27, QA t_23879205):
  // paste/armory listener attach and the realms dropdown fetch.
  wirePaste();
  wireArmory();
  wireRealms();
  // t_75c08981: paint the run-bar state at boot so Run starts disabled with
  // no character (it was only recomputed after the first character load).
  updateSummary();
  pollWorkerStatus();
  setInterval(pollWorkerStatus, 15000);
  loadUpgradeData().then(renderSeasonChip);
  renderSeasonChip();
  document.getElementById('btn-run').addEventListener('click', runSimulation);
  document.getElementById('fight-style').addEventListener('change', selectionChanged);
  document.getElementById('compare-mode').addEventListener('change', selectionChanged);
  // t_37e0320e: run progress lives on its own page (results?run_task=). The
  // runbar keeps a plain "View run" link while a run is active; the run
  // itself streams on the other page, so the gear grid stays fully usable.
  // A finished run's stale row self-heals: the run page falls back to
  // rendering the saved report and clears the row.
  const activeRun = loadActiveRun();
  if (activeRun) {
    const viewRun = document.getElementById('btn-open-run');
    if (viewRun) {
      viewRun.href = activeRunHref(activeRun);
      viewRun.hidden = false;
    }
    setWorkflowStatus('A simulation run is in progress — gear editing stays free; View run follows its progress.');
  }
  wirePopover(document.getElementById('btn-review'),
    document.getElementById('review-popover'), renderReviewPopover);
  // §10: fresh draft hint before any import (offer rehydration path).
  // t_1699829f: the old hint sat in the footer and named only the newest
  // draft, so after a session-expiry re-login the page showed the empty
  // import band while the 401 banner claimed "your work is still here".
  // Persistent note INSIDE the import band, one line per saved character
  // (loadDrafts is newest-first). Draft lifecycle unchanged: nothing here
  // clears or writes drafts.
  if (pendingBoot.drafts.length) {
    const list = pendingBoot.drafts
      .map(d => `${d.parsedData.char_name} (saved ${new Date(d.savedAt * 1000).toLocaleString()})`)
      .join(', ');
    const band = document.getElementById('import-details');
    if (band?.querySelector('.cardbody')) {
      const note = document.createElement('p');
      note.className = 'drafts-note';
      note.setAttribute('role', 'status');
      note.textContent =
        `Draft${pendingBoot.drafts.length > 1 ? 's' : ''} saved for ${list} — load the character to restore.`;
      band.querySelector('.cardbody').append(note);
      // btn-new-export clears all drafts (paste.js) — do not leave the note claiming them.
      document.getElementById('btn-new-export')?.addEventListener('click', () => note.remove());
    }
    setWorkflowStatus(`Saved draft${pendingBoot.drafts.length > 1 ? 's' : ''} for ${pendingBoot.drafts.map(d => d.parsedData.char_name).join(', ')} — loading the character restores the selection.`);
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
