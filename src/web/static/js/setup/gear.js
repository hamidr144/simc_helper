// js/setup/gear.js — RED-3 slot-section renderer (design contract §3). The
// mockup gear-run.html structure ported: equipped cards (.eqc, delta base),
// always-visible candidate rows (.vrow native buttons, one click = add/remove
// on the frozen payload sets), per-section lock, scrollY-preserving render
// (F-5). Surviving features keep their hosts: per-slot sort select and
// Add-by-ID live in the header cluster (decision D-7), extra sockets moved to
// the enhancements panel (D-6); enh-chips are gone (§6). Row identity is the
// (itemString, rank, voidforged) triple carried as data-attrs.
import { state } from '../core/state.js';

import { escapeHtml as esc } from '../core/dom.js';

import { SLOT_SECTIONS, craftedBadgeHtml, isCraftedItem, itemLevelFromLabel, normalizedEquippedItems, parseItemParams, ranksForItem } from '../core/items.js';

import { removeAddedItem, wireSlotAddForm } from './add-item.js';

import { renderSlotConflict } from './conflict.js';

import { persistDraft } from './draft.js';

import { scheduleUpgradePreview } from './preview.js';


import { selectionChanged } from './runbar.js';

import { ensureStatScores, sortItemsForSlot } from './sort.js';

import { foldChips, ilvlDeltaHtml, itemRow } from '../core/ui.js';
import { refreshWowheadLinks } from '../core/wowhead.js';  // RED-3: tooltips rebind after innerHTML rebuilds

/* Which row of an item is the picked variant. UI truth mirrors the
   payload-side fields: a user-selected grade entry carries the rank,
   voidforgedItems carries the ascension flag. */
function variantMatches(slot, item, rank, voidforged) {
  if (!state.selectedItems[slot]?.has(item)) return false;
  const entry = state.gearUpgrades[slot]?.[item];
  const pickedRank = entry?.user_selected ? (entry.rank || 0) : 0;
  const pickedVf = Boolean(entry?.user_selected && state.voidforgedItems[slot]?.[item]);
  const rowRank = rank || 0;
  return voidforged ? (pickedVf && pickedRank === rowRank)
    : (!pickedVf && pickedRank === rowRank);
}

/* §7 contract override: pre-run delta = ilvl only, % never. For the
   two-equipment slots (trinkets) the delta baselines against the weakest
   equipped item — the natural swap target where "the" equipped item is
   ambiguous (kept as ilvl; the old % delta does not exist pre-run). */
function rowDelta(equipped, level) {
  if (!equipped.length) return '<span class="d eq">—</span>';
  const base = equipped.length === 1
    ? equipped[0].ilvl
    : Math.min(...equipped.map(e => e.ilvl ?? 0));
  return ilvlDeltaHtml(level != null && base != null ? level - base : 0);
}

export function renderGear() {
  const list = document.getElementById('gear-grid');
  if (!list || !state.parsedData) return;
  const y = window.scrollY;   // F-5: toggling a row never moves the page
  const bySlot = state.parsedData.items_by_slot || {};

  const sections = SLOT_SECTIONS.filter(s => !s.hideWhen || !s.hideWhen());
  for (const key of Object.keys(bySlot)) {
    if (!sections.some(s => s.slot === key)) {
      sections.push({ key, label: key.replace('_', ' '), slot: key, equipKeys: [key] });
    }
  }

  // sticky jump nav — the same list, in the same order (§3)
  document.getElementById('qj').innerHTML = sections.map(s =>
    `<a href="#sec-${esc(s.key)}">${esc(s.label)}</a>`).join('');

  list.innerHTML = sections.map(section => {
    const slot = section.slot;
    const items = sortItemsForSlot(slot, bySlot[slot] || []);
    const locked = Boolean(state.slotLocks[section.key]);
    const equippedStrings = normalizedEquippedItems(slot);
    const equipped = equippedStrings.map(item => ({
      ilvl: Number(parseItemParams(item).ilevel)
        || itemLevelFromLabel(state.parsedData.item_names[item]) || 0,
    }));
    const equippedSet = new Set(equippedStrings);

    const eqBlock = section.equipKeys.map((equipKey, index) => {
      const item = (state.parsedData.equipped_gear || {})[equipKey];
      if (!item) return '';
      const label = state.parsedData.item_names[item] || item;
      const params = parseItemParams(item);
      const card = itemRow('eqc', {
        id: params.id,
        name: String(label).replace(/\s*\(\d+\)/, ''),
        quality: params.quality,
        ilvl: Number(params.ilevel) || itemLevelFromLabel(label),
        slotLabel: section.label,
        slotTag: section.equipKeys.length > 1 ? `slot ${index + 1}` : '',
        link: true,  // shortcut: no bonus ids here; bonus-aware eq icons need the W map, upgrade when it lands
      });
      return `<div class="eqrow"><div class="eqtag"><span class="tag eq">equipped${section.equipKeys.length > 1 ? ` · slot ${index + 1}` : ''}</span></div>${card}</div>`;
    }).join('');

    const rows = items.filter(item => !equippedSet.has(item)).flatMap(item => {
      const params = parseItemParams(item);
      const cleanName = String(state.parsedData.item_names[item] || `item ${params.id || ''}`)
        .replace(/\s*\(\d+\)/, '');
      return ranksForItem(slot, item).map(variant => {
        const level = variant.ilvl
          ?? (Number(params.ilevel) || itemLevelFromLabel(state.parsedData.item_names[item]) || null);
        const suffix = variant.rank
          ? ` · ${variant.label || `rank ${variant.rank}`} ⬥${level}` : '';
        const title = [cleanName + (variant.rank ? ` (${variant.label || `rank ${variant.rank}`})` : ''),
          `ilvl ${level ?? '?'}`,
          isCraftedItem(item) ? craftedBadgeHtml(item) : '',
          state.addedItems.has(item) ? 'added by you — click the × in the row to drop it' : '']
          .filter(Boolean).join(' · ');
        return itemRow('vrow', {
          id: params.id,
          name: cleanName + suffix,
          quality: variant.voidforged ? 'epic' : params.quality,
          ilvl: level,
          sel: variantMatches(slot, item, variant.rank, variant.voidforged),
          disabled: locked,
          deltaHtml: rowDelta(equipped, level),
          title,
          item, rank: variant.rank, voidforged: variant.voidforged,
        });
      });
    }).join('');

    // added-items line: the old per-card × keeps a host (parity), outside the
    // native row button so nothing nests interactive elements
    const addedLine = items.filter(item => state.addedItems.has(item)).map(item =>
      `<span class="addeditem">added · ${esc(String(state.parsedData.item_names[item] || item).replace(/\s*\(\d+\)/, ''))}<button type="button" class="row-x" data-remove="${esc(item)}" aria-label="Remove ${esc(String(state.parsedData.item_names[item] || item).replace(/\s*\(\d+\)/, ''))} from candidates">×</button></span>`).join('');
    const addedBlock = addedLine ? `<div class="addedline">${addedLine}</div>` : '';

    const sortValue = state.slotSorts[slot] || 'ilvl';
    return `<section class="slotsec${locked ? ' locked' : ''}" id="sec-${esc(section.key)}"
        aria-labelledby="h-${esc(section.key)}" data-slot="${esc(slot)}" data-section="${esc(section.key)}">
      <header class="sechead">
        <h2 id="h-${esc(section.key)}">${esc(section.label)}</h2>
        <span class="cnt num">${items.length} candidates</span>
        <span class="headtools">
          <select class="slot-sort-select" aria-label="Sort ${esc(section.label)} candidates"
            title="Sort candidates. 'Stat priority' is a heuristic class weight order, not a sim result.">
            <option value="ilvl"${sortValue === 'ilvl' ? ' selected' : ''}>ilvl ↓</option>
            <option value="name"${sortValue === 'name' ? ' selected' : ''}>Name</option>
            <option value="priority"${sortValue === 'priority' ? ' selected' : ''}>Stat priority*</option>
          </select>
          <button type="button" class="btn-ghost slot-add-toggle" aria-expanded="false">Add by ID</button>
          <button type="button" class="btn-ghost slot-toggle-all">Select all</button>
          <button type="button" class="lock${locked ? ' on' : ''}" aria-pressed="${locked}"
            aria-label="${locked ? 'Unlock' : 'Lock'} ${esc(section.label)} — keep this slot fixed while runs test the rest">${locked ? '🔒 Locked' : '🔓 Lock'}</button>
        </span></header>
      <div class="slot-add-form">
        <input type="text" class="slot-add-input" inputmode="numeric" autocomplete="off"
          placeholder="Own it but not in the export? Add by Wowhead item id…"
          aria-label="Wowhead item id to add to ${esc(section.label)}">
        <button type="button" class="slot-add-button">Preview</button></div>
      <div class="slot-add-preview" hidden></div>
      ${eqBlock}
      <div class="rows">${rows}</div></section>`;
  }).join('');
  if (window.scrollTo) window.scrollTo(0, y);
  refreshWowheadLinks();
  wireSections(list);
  renderSlotConflict();
}

function wireSections(list) {
  // doc 4.2 collapse parity on v11 rows: top 3 unselected visible, rest fold
  // behind a +N chip (foldChips keeps selected/excluded always visible).
  for (const rows of list.querySelectorAll('.rows')) foldChips(rows, 3);
  for (const section of list.querySelectorAll('.slotsec')) {
    const slot = section.dataset.slot;
    const key = section.dataset.section;
    const items = state.parsedData.items_by_slot[slot] || [];

    const toggleAll = section.querySelector('.slot-toggle-all');
    toggleAll.textContent = items.length && (state.selectedItems[slot]?.size || 0) === items.length
      ? 'Select none' : 'Select all';

    const sortSelect = section.querySelector('.slot-sort-select');
    sortSelect.addEventListener('change', () => {
      state.slotSorts[slot] = sortSelect.value;
      if (sortSelect.value === 'priority') void ensureStatScores(slot, items, sortSelect).then(renderGear);
      else renderGear();
    });

    const addToggle = section.querySelector('.slot-add-toggle');
    const addForm = section.querySelector('.slot-add-form');
    addForm.hidden = true;
    addToggle.addEventListener('click', () => {
      const open = addForm.hidden;
      addForm.hidden = !open;
      addToggle.setAttribute('aria-expanded', String(open));
      if (open) addForm.querySelector('.slot-add-input').focus();
    });
    wireSlotAddForm(section, slot);

    toggleAll.addEventListener('click', () => {
      const selectAll = toggleAll.textContent === 'Select all';
      state.selectedItems[slot] = new Set(selectAll ? items : []);
      if (!selectAll) {
        for (const item of items) {
          if (state.gearUpgrades[slot]?.[item]?.user_selected) delete state.gearUpgrades[slot][item];
          if (state.voidforgedItems[slot]?.[item]) delete state.voidforgedItems[slot][item];
        }
      }
      renderGear();
      selectionChanged();
      persistDraft();
    });

    section.querySelector('.lock').addEventListener('click', () => {
      state.slotLocks[key] = !state.slotLocks[key];
      renderGear();
      persistDraft();
    });

    for (const row of section.querySelectorAll('.vrow')) {
      row.addEventListener('click', () => onRowClick(section, row));
    }
    // D-9: upgrade-rank rows carry a real export/Wowhead delta — enrich the
    // native title on first hover (debounced + cached inside preview.js).
    section.addEventListener('mouseover', event => {
      const row = event.target.closest('.vrow[data-rank]');
      if (row) scheduleUpgradePreview(slot, row.dataset.item, row);
    });
  }
}

/* §3 one-click semantics: a click adds and encodes the variant; clicking the
   selected row reverts to the equipped baseline (remove + drop the variant). */
function onRowClick(section, row) {
  if (row.disabled) return;
  const slot = section.dataset.slot;
  const item = row.dataset.item;
  const rank = row.dataset.rank ? Number(row.dataset.rank) : null;
  const vf = row.dataset.vf === '1';
  state.selectedItems[slot] ||= new Set();
  if (variantMatches(slot, item, rank, vf)) {
    state.selectedItems[slot].delete(item);
    delete state.gearUpgrades[slot]?.[item];
    delete state.voidforgedItems[slot]?.[item];
  } else {
    state.selectedItems[slot].add(item);
    if (rank) {
      const variant = ranksForItem(slot, item)
        .find(v => Number(v.rank) === rank && Boolean(v.voidforged) === vf);
      const current = state.gearUpgrades[slot]?.[item] || {};
      state.gearUpgrades[slot][item] = {
        ...current, source: 'export', rank,
        item_level: variant?.ilvl ?? current.item_level,
        user_selected: true,
      };
      state.voidforgedItems[slot][item] = vf;
    } else {
      delete state.gearUpgrades[slot]?.[item];
      delete state.voidforgedItems[slot]?.[item];
    }
    state.gearTouchedByUser.set(item, true);
  }
  renderGear();
  selectionChanged();
  persistDraft();
}
