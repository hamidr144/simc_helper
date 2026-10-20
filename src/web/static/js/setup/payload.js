// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/payload)

import { state } from '../core/state.js';

import { season } from '../core/season.js';

import { setWorkflowStatus, updateSummary } from './runbar.js';
import { apiFetch } from '../core/api.js';

function buildPayload() {
  const enchantPayload = {};
  for (const slot of Object.keys(state.appConfig.enchantments || {})) {
    enchantPayload[slot] = Array.from(state.selectedEnchants[slot] || []).map(Number);
  }
  return {
    char_class: state.parsedData.char_class,
    char_name: state.parsedData.char_name,
    base_profile: state.parsedData.base_profile,
    fight_style: document.getElementById('fight-style')?.value || 'single_boss',
    mode: document.getElementById('compare-mode')?.value || 'single_swap',
    equipped_gear: state.parsedData.equipped_gear,
    selected_items: Object.fromEntries(Object.entries(state.selectedItems).map(([slot, items]) => [slot, Array.from(items)])),
    selected_enchants: enchantPayload,
    selected_gems: Array.from(state.selectedGems).map(Number),
    selected_meta_gems: Array.from(state.selectedMetaGems).map(Number),
    item_levels: {},
    gear_upgrades: state.gearUpgrades,
    voidforged_items: state.voidforgedItems,
    extra_sockets: state.extraSockets,
    upgrade_season: season().id
  };
}
export async function generateInput(quiet = false) {
  if (!quiet) setWorkflowStatus('Preparing comparison…');
  try {
    const response = await apiFetch('api/generate-simc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload())
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Generation failed');
    state.generatedInput = data;
    document.getElementById('combo-count').textContent = data.combinations.toLocaleString();
    // t_4485565b: 0 candidates is a valid baseline run, not a doomed job.
    let statusText = data.combinations === 0
      ? 'Ready to run a baseline current-gear report. Select gear changes, gems, or enchants to compare candidates.'
      : `Ready to run ${data.combinations.toLocaleString()} candidate ${data.combinations === 1 ? 'combination' : 'combinations'}.`;
    if (data.embedded_copies) {
      // TG3-D2: never let carried copy= blocks disappear silently.
      statusText += ` Removed ${data.embedded_copies} embedded ${data.embedded_copies === 1 ? 'copy' : 'copies'} carried by the uploaded profile (their gear stays selectable).`;
    }
    setWorkflowStatus(statusText);
  } catch (error) {
    state.generatedInput = null;
    setWorkflowStatus(`Could not generate input: ${error.message}`);
  } finally {
    updateSummary();
  }
}
