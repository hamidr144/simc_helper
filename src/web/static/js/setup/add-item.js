// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/add-item)

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { inferMidnightUpgrade, resolveAddedGrade } from '../core/items.js';

import { renderCharChip } from './char-chip.js';

import { renderGear } from './gear.js';

import { selectionChanged, updateSummary } from './runbar.js';
import { apiFetch } from '../core/api.js';
import { persistDraft } from './draft.js';

function showSlotAddMessage(host, kind, message) {
  host.hidden = false;
  host.className = `slot-add-preview is-${kind}`;
  host.textContent = message;
}
/* Add-by-ID slot guard (t_1699829f): preview.invslot is the Wowhead item-XML
   inventorySlot id; ids and names verified live 2026-10-21 against real gear
   (1 Head, 2 Neck, 3 Shoulder, 5 Chest, 6 Waist, 7 Legs, 8 Feet, 9 Wrist,
   10 Hands, 11 Finger, 12 Trinket, 13 One-Hand, 14 Off Hand, 15 Ranged,
   16 Back, 17 Two-Hand; 0 = non-equip — gems/bags/mounts, empty name).
   Keys are the payload-side slot keys gear.js hands wireSlotAddForm (the
   finger/trinket pools are single sections). Values are the slots the item
   may join; an empty list means "known id, never an equip slot here".
   Additive on purpose: ids with a NUMERIC invslot absent from this table
   fail open (Add still offered) so valid future DBC ids are never blocked.
   A preview with NO numeric invslot is rejected (t_2fa2e1fe): set-bonus
   "1/2 ..." pseudo-items, aspects and other spell wrappers carry no equip
   slot, and the old fail-open let them into items_by_slot as gear
   candidates (phantom rows surviving every load through the draft).
   shortcut: client-side only; upgrade to server-side validation at
   run-build time if false-positive rejections are reported. */
const INV_SLOT_TABLE = {
  0: [], 4: [], 15: [], 19: [],
  1: ['head'], 2: ['neck'], 3: ['shoulder'], 5: ['chest'], 6: ['waist'],
  7: ['legs'], 8: ['feet'], 9: ['wrist'], 10: ['hands'],
  11: ['finger'], 12: ['trinket'],
  13: ['main_hand', 'off_hand'], 14: ['off_hand'],
  16: ['back'],
  17: ['main_hand', 'off_hand', 'two_hand'],
};
export function slotAddDecision(slot, preview) {
  // t_2fa2e1fe: no numeric inventorySlot = not equipment (slot lookup said
  // so, or Wowhead has no slot for this id — pseudo-items). Reject; the
  // fail-open stays ONLY for numeric invslots absent from the table above.
  if (typeof preview.invslot !== 'number') {
    return { offer: false, message:
      `${preview.name || 'That item'} has no equip slot on Wowhead — set bonuses, aspects and other pseudo-items are not gear candidates. If this is real gear, the Wowhead slot lookup failed; try again in a minute.` };
  }
  const allowed = Object.hasOwn(INV_SLOT_TABLE, preview.invslot)
    ? INV_SLOT_TABLE[preview.invslot] : null;
  if (allowed && !allowed.includes(slot)) {
    return { offer: false, message:
      `${preview.name || 'This item'} fits ${preview.invslot_name || 'no equip slot'}, not ${slot.replace('_', ' ')}.` };
  }
  return { offer: true, showSlotName: !allowed && Boolean(preview.invslot_name) };
}
function commitAddedItem(slot, itemId, preview) {
  const key = `id=${itemId}`;
  const items = state.parsedData.items_by_slot[slot] || (state.parsedData.items_by_slot[slot] = []);
  if (!items.includes(key)) {
    items.push(key);
    state.parsedData.item_names[key] = `${preview.name || `Item ${itemId}`} (${preview.ilvl || 0})`;
    // t_910b4761: carry the tooltip's Wowhead quality into resolveRowQuality's
    // parsedData.item_qualities slot (qualityOf takes numbers) — without it the
    // committed row rendered Common while its preview showed Epic. Drafts round
    // the whole parsedData through localStorage, so the grade survives restore.
    if (Number.isInteger(preview.quality)) (state.parsedData.item_qualities ||= {})[key] = preview.quality;
    state.gearUpgrades[slot] = state.gearUpgrades[slot] || {};
    state.voidforgedItems[slot] = state.voidforgedItems[slot] || {};
    // t_4149ba6b (A4): resolve the added key's grade from data already in
    // hand (same-id sibling in this slot, else the preview's Upgrade Level
    // line) before falling back to the label-only ladder inference — the bare
    // key alone never resolves (off-ladder preview ilvl).
    const inferred = resolveAddedGrade(slot, itemId, preview)
      || inferMidnightUpgrade(slot, key, state.parsedData.item_names[key]);
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
  delete state.parsedData.item_qualities?.[item];
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
  const decision = slotAddDecision(slot, preview);
  if (!decision.offer) {
    showSlotAddMessage(host, 'error', decision.message);
    return;
  }
  // t_1699829f fail-open: unknown/failed invslot still offers Add, naming the
  // returned slot in the meta line so the mismatch is at least visible.
  const slotNote = decision.showSlotName
    ? ` · ${escapeHtml(preview.invslot_name)}` : '';
  host.className = 'slot-add-preview';
  host.innerHTML =
    `<img src="api/item-icon/${itemId}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` +
    `<span class="slot-add-name"${preview.quality_color ? ` style="color:${escapeHtml(preview.quality_color)}"` : ''}>` +
      `${escapeHtml(preview.name || `Item ${itemId}`)}</span>` +
    `<span class="slot-add-meta">${preview.ilvl ? `ilvl ${preview.ilvl}` : 'ilvl unknown'}` +
      `${preview.upgrade_level ? ` · ${escapeHtml(preview.upgrade_level)}` : ''}${slotNote}</span>` +
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

/* t_2fa2e1fe: drafts saved before the add-time guard persist add-by-ID
   pseudo-items (set bonuses, aspects: no equip slot on Wowhead) as gear
   candidates, and restoreAddedItem rides them into every later load —
   including fresh Armory loads (user report: phantom Neck/Shoulders/Legs/
   Feet rows). Validate each persisted added key once per boot: ONLY a
   CONFIRMED non-equip item (invslot === 0 — gems/bags/mounts/spell
   wrappers) drops from state and the draft re-persists. Every other
   outcome KEEPS the row: fetch failure, non-OK response, and invslot
   null/absent all mean the slot LOOKUP FAILED (fetch_wowhead_item_slot
   fail-softs to (None, None), review round 1), and gear lost to a flaky
   wowhead.com fetch is unrecoverable work loss (t_26c5ddef precedent).
   Add-side slotAddDecision keeps its null rejection — non-destructive and
   retryable. */
export async function validateAddedItems() {
  let dropped = false;
  for (const [key, slot] of [...state.addedItems]) {
    const id = /^id=(\d+)$/.exec(key)?.[1];
    if (!id) continue;
    try {
      const response = await apiFetch(`api/wowhead/tooltip?item=${id}`);
      if (!response.ok) continue;
      const data = await response.json().catch(() => ({}));
      const invslot = data.preview?.invslot;
      if (invslot === 0) {
        removeAddedItem(slot, key);
        dropped = true;
      }
    } catch { /* keep on network failure */ }
  }
  if (dropped) persistDraft();
}
