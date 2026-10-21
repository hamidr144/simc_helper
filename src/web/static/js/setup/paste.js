// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/paste)

import { initializeSelections, state } from '../core/state.js';

import { detectSeasonFromExport, loadUpgradeData, renderSeasonChip, upgradeData } from '../core/season.js';

// t_26c5ddef: token must equal the app.html entry ?v= token or the browser loads a second pages/setup.js instance (pinned by tests/test_add_item_sorting.py)
import { renderWorkflow } from '../pages/setup.js?v=red3-3';

import { updateArmoryState } from './armory.js';

import { clearDraftKeys, persistDraft } from './draft.js';

import { hydrateWowheadUpgrades } from './conflict.js';

import { updateSummary } from './runbar.js';
import { apiFetch } from '../core/api.js';

const addonInput = document.getElementById('addon-input');
const btnParseAddon = document.getElementById('btn-parse-addon');
export function updateCharCount() {
  const counter = document.getElementById('addon-char-count');
  const length = addonInput.value.trim().length;
  if (counter) counter.textContent = length
    ? `${length.toLocaleString()} characters pasted`
    : 'Nothing pasted yet';
  btnParseAddon.disabled = !length;
}
export function showParseError(message) {
  const panel = document.getElementById('parse-error');
  if (!panel) return;
  panel.hidden = false;
  panel.textContent = message;
}
export function clearParseError() {
  const panel = document.getElementById('parse-error');
  if (panel) { panel.hidden = true; panel.textContent = ''; }
  clearParseWarning();
}
function showParseWarning(messages) {
  const panel = document.getElementById('parse-warning');
  if (!panel) return;
  panel.hidden = false;
  panel.textContent = messages.join(' ');
}
function clearParseWarning() {
  const panel = document.getElementById('parse-warning');
  if (panel) { panel.hidden = true; panel.textContent = ''; }
}
function collapsePastePanel() {
  document.getElementById('paste-guide').hidden = true;
  addonInput.hidden = true;
  btnParseAddon.hidden = true;
  const armoryCard = document.getElementById('armory-import');
  if (armoryCard) armoryCard.hidden = true;
  document.getElementById('btn-new-export').hidden = false;
  const counter = document.getElementById('addon-char-count');
  if (counter) counter.textContent = 'Character ready below.';
}
function resetPastePanel() {
  document.getElementById('paste-guide').hidden = false;
  addonInput.hidden = false;
  addonInput.value = '';
  addonInput.focus();
  btnParseAddon.hidden = false;
  const armoryCard = document.getElementById('armory-import');
  if (armoryCard) armoryCard.hidden = false;
  document.getElementById('btn-new-export').hidden = true;
  clearParseError();
  updateCharCount();
  updateArmoryState();
}

/* ---------- Run progress ---------- */
export async function applyParsedCharacter(data) {
  state.parsedData = data;
  if (Array.isArray(state.parsedData.warnings) && state.parsedData.warnings.length) {
    showParseWarning(state.parsedData.warnings);
  } else {
    clearParseWarning();
  }
  if (!upgradeData) await loadUpgradeData();
  detectSeasonFromExport(state.parsedData);
  renderSeasonChip();
  state.simulationDone = false;
  initializeSelections();
  renderWorkflow();
  collapsePastePanel();
  hydrateWowheadUpgrades(state.parsedData.items_by_slot);
  persistDraft();
  document.getElementById('gear-grid')
    ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export function wire() {
btnParseAddon.addEventListener('click', async () => {
  const text = addonInput.value.trim();
  if (!text) return;
  btnParseAddon.disabled = true;
  btnParseAddon.textContent = 'Parsing…';
  clearParseError();
  try {
    const [parseResponse, configResponse] = await Promise.all([
      apiFetch('api/parse-addon', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ addon_text: text }) }),
      apiFetch('api/config')
    ]);
    if (!parseResponse.ok) {
      const detail = await parseResponse.json().catch(() => ({}));
      throw new Error(detail.detail || 'The addon export could not be parsed. Make sure you copied the full text from the /simc export window.');
    }
    state.appConfig = configResponse.ok ? await configResponse.json() : state.appConfig;
    await applyParsedCharacter(await parseResponse.json());
  } catch (error) {
    showParseError(`Could not parse the export: ${error.message}`);
  } finally {
    btnParseAddon.disabled = false;
    btnParseAddon.textContent = 'Load export';
  }
});

/* ---------- Armory load (Step 7: no addon needed) ---------- */

document.getElementById('btn-new-export').addEventListener('click', () => {
  // RED-3: the page chrome is static — a fresh export only clears the
  // rendered layers and re-opens the import band (draft keys are dropped:
  // "new export" means a different character or a deliberate restart, §10).
  state.parsedData = null;
  state.generatedInput = null;
  state.simulationDone = false;
  clearDraftKeys();
  document.getElementById('gear-grid').innerHTML = '';
  document.getElementById('qj').innerHTML = '';
  document.getElementById('enhancement-options').innerHTML = '';
  document.getElementById('char-chip').hidden = true;
  const result = document.getElementById('run-result');
  if (result) { result.hidden = true; result.innerHTML = ''; }
  document.getElementById('run-progress').hidden = true;
  document.getElementById('import-details').open = true;
  // t_16e4f177: no gear list anymore — restore the plain skip link.
  const skipLink = document.querySelector('.skip-link');
  if (skipLink) {
    skipLink.href = '#main';
    skipLink.textContent = 'Skip to content';
  }
  resetPastePanel();
  updateSummary();
});

addonInput.addEventListener('input', updateCharCount);
}

