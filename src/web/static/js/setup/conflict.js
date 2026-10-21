// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/conflict)

import { state } from '../core/state.js';

import { SLOT_LABELS, twoHandedConflict } from '../core/items.js';

import { renderGear } from './gear.js';

import { generateInput } from './payload.js';

import { setWorkflowStatus, updateSummary } from './runbar.js';
import { apiFetch } from '../core/api.js';

export async function hydrateWowheadUpgrades(itemsBySlot) {
  try {
    // Items whose upgrade path the export itself already provided never need
    // (and must not be overwritten by) the Wowhead lookup.
    const lookupItems = {};
    for (const [slot, items] of Object.entries(itemsBySlot || {})) {
      const rest = (items || []).filter(item => !state.parsedData?.item_upgrades?.[item]);
      if (rest.length) lookupItems[slot] = rest;
    }
    const response = await apiFetch('api/wowhead-upgrades', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items_by_slot: lookupItems })
    });
    if (!response.ok) return;
    const data = await response.json();
    for (const items of Object.values(data.two_handed || {})) {
      for (const item of items) state.twoHandedItems.add(item);
    }
    for (const [slot, itemUpgrades] of Object.entries(data.gear_upgrades || {})) {
      for (const [item, upgrade] of Object.entries(itemUpgrades)) {
        if (state.parsedData?.item_upgrades?.[item]) continue;
        // Never clobber a grade the user already picked while this lookup
        // was in flight.
        if (state.gearUpgrades[slot]?.[item]?.user_selected) continue;
        (state.gearUpgrades[slot] ||= {})[item] = upgrade;
      }
    }
    renderGear();
    updateSummary();
  } catch (error) {
    console.warn('Could not refine item grades from Wowhead', error);
  }
}

/* TG3-C slot conflict (design t_784b91c7 §3.4) + RED-3: the inline
   role="alert" line now renders once per conflicting weapon SECTION (rows
   replaced cards), plus the aggregate line in #workflow-status. The
   authoritative rejection is the server-side 400 from generate-simc, which
   generateInput() surfaces here too; this is the pre-submit hint mirroring it
   — we never auto-remove selections. */
export function renderSlotConflict() {
  document.querySelectorAll('.gear-conflict').forEach(el => el.remove());
  const conflict = twoHandedConflict();
  if (!conflict) return;
  const mark = (slot, text) => {
    const section = document.querySelector(`#gear-grid .slotsec[data-slot="${slot}"]`);
    const items = state.selectedItems[slot];
    if (!section || !items?.size) return;
    if (slot === conflict.slot && ![...items].some(item => state.twoHandedItems.has(item))) return;
    const line = document.createElement('p');
    line.className = 'gear-conflict conflict-note';
    line.setAttribute('role', 'alert');
    line.textContent = text;
    section.querySelector('.slot-add-preview')?.after(line);
  };
  mark(conflict.slot, `Two-handed weapon — cannot be combined with ${SLOT_LABELS[conflict.other]}.`);
  mark(conflict.other, `Conflicts with the two-handed weapon in ${SLOT_LABELS[conflict.slot]}.`);
  setWorkflowStatus(
    `Slot conflict: ${SLOT_LABELS[conflict.slot]} and ${SLOT_LABELS[conflict.other]} cannot be equipped together — a two-handed weapon occupies both weapon slots. Deselect one of the two slots.`);
}
