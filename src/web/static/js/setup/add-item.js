// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/add-item)

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { inferMidnightUpgrade } from '../core/items.js';

import { renderCharChip } from './char-chip.js';

import { renderGear } from './gear.js';

import { selectionChanged, updateSummary } from './runbar.js';
import { apiFetch } from '../core/api.js';

function showSlotAddMessage(host, kind, message) {
  host.hidden = false;
  host.className = `slot-add-preview is-${kind}`;
  host.textContent = message;
}
function commitAddedItem(slot, itemId, preview) {
  const key = `id=${itemId}`;
  const items = state.parsedData.items_by_slot[slot] || (state.parsedData.items_by_slot[slot] = []);
  if (!items.includes(key)) {
    items.push(key);
    state.parsedData.item_names[key] = `${preview.name || `Item ${itemId}`} (${preview.ilvl || 0})`;
    state.gearUpgrades[slot] = state.gearUpgrades[slot] || {};
    state.voidforgedItems[slot] = state.voidforgedItems[slot] || {};
    const inferred = inferMidnightUpgrade(slot, key, state.parsedData.item_names[key]);
    if (inferred) state.gearUpgrades[slot][key] = inferred;
    state.voidforgedItems[slot][key] = false;
    state.addedItems.set(key, slot);
  }
  state.selectedItems[slot] = state.selectedItems[slot] || new Set();
  state.selectedItems[slot].add(key);
  renderGear();
  renderCharChip();
  updateSummary();
  selectionChanged();
}
export function removeAddedItem(slot, item) {
  const items = state.parsedData.items_by_slot[slot];
  if (items) {
    const index = items.indexOf(item);
    if (index >= 0) items.splice(index, 1);
  }
  delete state.parsedData.item_names[item];
  state.selectedItems[slot]?.delete(item);
  delete state.gearUpgrades[slot]?.[item];
  delete state.voidforgedItems[slot]?.[item];
  delete state.statScores[item];
  state.addedItems.delete(item);
  renderGear();
  renderCharChip();
  selectionChanged();
}
function renderSlotAddPreview(slot, itemId, preview, host, addInput) {
  host.className = 'slot-add-preview';
  host.innerHTML =
    `<img src="api/item-icon/${itemId}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` +
    `<span class="slot-add-name"${preview.quality_color ? ` style="color:${escapeHtml(preview.quality_color)}"` : ''}>` +
      `${escapeHtml(preview.name || `Item ${itemId}`)}</span>` +
    `<span class="slot-add-meta">${preview.ilvl ? `ilvl ${preview.ilvl}` : 'ilvl unknown'}` +
      `${preview.upgrade_level ? ` · ${escapeHtml(preview.upgrade_level)}` : ''}</span>` +
    `<button type="button" class="slot-add-confirm">Add to ${escapeHtml(slot.replace('_', ' '))}</button>`;
  host.querySelector('.slot-add-confirm').addEventListener('click', () => {
    commitAddedItem(slot, itemId, preview);
    addInput.value = '';
    addInput.focus();
  });
}
export function wireSlotAddForm(group, slot) {
  const addInput = group.querySelector('.slot-add-input');
  const addButton = group.querySelector('.slot-add-button');
  const addPreview = group.querySelector('.slot-add-preview');
  const previewAdd = async () => {
    const raw = addInput.value.trim();
    if (!/^\d{1,9}$/.test(raw)) {
      showSlotAddMessage(addPreview, 'error', 'Enter a numeric Wowhead item ID (see the item link, e.g. wowhead.com/item=276000).');
      return;
    }
    const itemId = Number(raw);
    showSlotAddMessage(addPreview, 'loading', `Resolving item ${itemId} on Wowhead…`);
    try {
      const response = await apiFetch(`api/wowhead/tooltip?item=${itemId}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `status ${response.status}`);
      renderSlotAddPreview(slot, itemId, data.preview || {}, addPreview, addInput);
    } catch (error) {
      showSlotAddMessage(addPreview, 'error',
        `Could not resolve item ${itemId} on Wowhead (${error.message}).`);
    }
  };
  addButton.addEventListener('click', previewAdd);
  addInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); previewAdd(); }
  });
}
