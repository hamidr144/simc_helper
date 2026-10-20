// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/gear)

import { state } from '../core/state.js';

import { escapeHtml, wirePopover } from '../core/dom.js';

import { exportRanksFor, itemLevelFromLabel, parseItemParams } from '../core/items.js';

import { seasonTracks } from '../core/season.js';

import { createWowheadIconLink, refreshWowheadLinks } from '../core/wowhead.js';

import { removeAddedItem, wireSlotAddForm } from './add-item.js';

import { renderSlotConflict } from './conflict.js';

import { enhancementChipLabel, jumpToEnhancement, syncEnhancementChips } from './enhancements.js';

import { cardBadges, syncCraftedAscensionEntry, upgradePopoverMarkup, upgradeStateText } from './gear-card.js';

import { scheduleUpgradePreview } from './preview.js';

import { selectionChanged } from './runbar.js';

import { ensureStatScores, sortItemsForSlot } from './sort.js';

export function renderGear() {
  const grid = document.getElementById('gear-grid');
  if (!grid) return;
  grid.innerHTML = '';
  // MGE-2 §5/§6 (A7/A7.2/A9): fixed doll order; slots missing from the export
  // still render (0/0 selected); unknown export slots append after off_hand.
  const bySlot = state.parsedData.items_by_slot;
  const extraSlots = Object.keys(bySlot).filter(s => !PAPER_DOLL_SLOTS.includes(s));
  for (const [slot, items] of [...PAPER_DOLL_SLOTS, ...extraSlots].map(s => [s, bySlot[s] || []])) {
    const group = document.createElement('section');
    group.className = 'slot-group';
    group.dataset.slot = slot;
    const chipDefs = [['enchants', 'Open enchantment controls in step 3'],
      ['gems', 'Open gem controls in step 3']];
    let chipsHtml = '';
    for (const [kind, hint] of chipDefs) {
      const chipLabel = enhancementChipLabel(kind, slot);
      if (chipLabel) {
        chipsHtml += `<button type="button" class="enh-chip" data-kind="${kind}" ` +
          `data-slot="${slot}" title="${hint}">${escapeHtml(chipLabel)}</button>`;
      }
    }
    group.innerHTML = `<div class="slot-group-header"><h3>${escapeHtml(slot.replace('_', ' '))}</h3>` +
      `<span class="slot-count"></span>${chipsHtml}` +
      `<select class="slot-sort-select" aria-label="Sort ${escapeHtml(slot)} candidates" ` +
      `title="Sort candidates. 'Stat priority' is a heuristic class weight order, not a sim result.">` +
      `<option value="ilvl">ilvl ↓</option><option value="name">Name</option>` +
      `<option value="priority">Stat priority*</option></select>` +
      `<button type="button" class="slot-toggle-all">Select none</button>` +
      `<button type="button" class="btn-ghost slot-add-toggle" aria-expanded="false">Add by ID</button></div>` +
      `<div class="slot-add-form">` +
      `<input type="text" class="slot-add-input" inputmode="numeric" autocomplete="off" ` +
      `placeholder="Own it but not in the export? Add by Wowhead item id…" ` +
      `aria-label="Wowhead item id to add to ${escapeHtml(slot)}">` +
      `<button type="button" class="slot-add-button">Preview</button></div>` +
      `<div class="slot-add-preview" hidden></div>` +
      `<div class="slot-items"></div>`;
    const itemGrid = group.querySelector('.slot-items');
    const slotCountEl = group.querySelector('.slot-count');
    const slotToggleAll = group.querySelector('.slot-toggle-all');
    const sortSelect = group.querySelector('.slot-sort-select');
    sortSelect.value = state.slotSorts[slot] || 'ilvl';
    sortSelect.addEventListener('change', () => {
      state.slotSorts[slot] = sortSelect.value;
      if (sortSelect.value === 'priority') {
        void ensureStatScores(slot, items, sortSelect).then(renderGear);
      } else {
        renderGear();
      }
    });
    wireSlotAddForm(group, slot);
    // t_2ab8f3be: add-by-id is a power feature — collapsed until asked for.
    const addToggle = group.querySelector('.slot-add-toggle');
    const addForm = group.querySelector('.slot-add-form');
    addForm.hidden = true;
    addToggle.addEventListener('click', () => {
      const open = addForm.hidden;
      addForm.hidden = !open;
      addToggle.setAttribute('aria-expanded', String(open));
      if (open) addForm.querySelector('.slot-add-input').focus();
    });
    const syncSlotHeader = () => {
      slotCountEl.textContent = `${state.selectedItems[slot].size}/${items.length} selected`;
      slotToggleAll.textContent = items.length && state.selectedItems[slot].size === items.length
        ? 'Select none' : 'Select all';
      // §3.3: chips ride the same listener so counts refresh on select-all
      // or any item toggle without new state.
      syncEnhancementChips();
    };
    syncSlotHeader();
    group.querySelectorAll('.enh-chip').forEach(chip => {
      chip.addEventListener('click', () => jumpToEnhancement(chip.dataset.kind, chip.dataset.slot));
    });
    slotToggleAll.addEventListener('click', () => {
      const selectAll = !(items.length && state.selectedItems[slot].size === items.length);
      state.selectedItems[slot] = new Set(selectAll ? items : []);
      itemGrid.querySelectorAll('.item-select-input').forEach(input => {
        input.checked = selectAll;
        input.closest('.gear-card')?.classList.toggle('is-selected', selectAll);
      });
      syncSlotHeader();
      selectionChanged();
    });
    for (const item of sortItemsForSlot(slot, items)) {
      const params = parseItemParams(item);
      const label = state.parsedData.item_names[item] || `${slot} ${params.id || ''}`;
      const level = itemLevelFromLabel(label) || Number(params.ilevel) || null;
      const card = document.createElement('article');
      card.className = `item-option gear-card ${state.selectedItems[slot].has(item) ? 'is-selected' : ''}`;
      card.dataset.slot = slot;
      card.dataset.item = item;
      card.innerHTML = `
        <label class="item-select-row">
          <input type="checkbox" class="item-select-input" ${state.selectedItems[slot].has(item) ? 'checked' : ''}>
          <span class="gear-card-info">${createWowheadIconLink(params.id, params.bonus_id, `<span class="item-option-name gear-card-name">${escapeHtml(label.replace(/\s*\(\d+\)/, ''))}</span>`)}${state.addedItems.has(item) ? '<span class="added-badge">Added</span>' : ''}<span class="gear-card-slot"><span>ilvl</span><span class="gear-card-slot-ilvl">${level ? level : '—'}</span></span></span>
        </label>
        ${cardBadges(slot, item)}
        ${upgradePopoverMarkup(slot, item)}
        ${state.addedItems.has(item) ? `<button type="button" class="slot-remove-added" title="Remove this added item from the candidates"><span class="sr-only">Remove ${escapeHtml(label.replace(/\s*\(\d+\)/, ''))} from candidates</span>×</button>` : ''}
      `;

      const removeAddedButton = card.querySelector('.slot-remove-added');
      if (removeAddedButton) {
        removeAddedButton.addEventListener('click', () => removeAddedItem(slot, item));
      }

      card.querySelector('.item-select-input').addEventListener('change', event => {
        if (event.target.checked) state.selectedItems[slot].add(item);
        else state.selectedItems[slot].delete(item);
        card.classList.toggle('is-selected', event.target.checked);
        syncSlotHeader();
        selectionChanged();
      });

      const trackSelect = card.querySelector('.gear-track-select');
      const rankSelect = card.querySelector('.gear-rank-select');
      if (trackSelect) {
        trackSelect.addEventListener('change', () => {
          const track = trackSelect.value;
          if (exportRanksFor(slot, item)) {
            // Export-provided ranks stay; track only labels ascension context.
            const entry = state.gearUpgrades[slot][item] ||
              { source: 'export', rank: 0, item_level: exportRanksFor(slot, item)[0].level };
            if (track === 'none') delete entry.track;
            else entry.track = track;
            entry.user_selected = true;
            state.gearUpgrades[slot][item] = entry;
            rankSelect.disabled = false;
          } else if (track === 'none') {
            delete state.gearUpgrades[slot][item];
            rankSelect.innerHTML = '';
            rankSelect.disabled = true;
          } else {
            state.gearUpgrades[slot][item] = { track, rank: 1, user_selected: true };
            rankSelect.innerHTML = (seasonTracks()[track] || []).map((level, index) =>
              `<option value="${index + 1}">Rank ${index + 1} · ${level}</option>`
            ).join('');
            rankSelect.disabled = false;
          }
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
        rankSelect.addEventListener('change', () => {
          const entry = state.gearUpgrades[slot][item];
          if (entry) {
            entry.rank = Number(rankSelect.value);
            const exportRanks = exportRanksFor(slot, item);
            if (exportRanks) {
              const picked = exportRanks.find(rank => rank.rank === entry.rank);
              if (picked) entry.item_level = picked.level;
            } else {
              const levels = seasonTracks()[entry.track] || [];
              entry.item_level = levels[entry.rank - 1] ?? null;
            }
            // Export rank 0 is the item's current level again, so the entry
            // stops being a user-chosen upgrade; anything else is a choice
            // that belongs to the candidate copies only.
            if (entry.rank === 0) delete entry.user_selected;
            else entry.user_selected = true;
          }
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
      }

      const voidforgeInput = card.querySelector('.voidforge-input');
      if (voidforgeInput) {
        voidforgeInput.addEventListener('change', event => {
          state.voidforgedItems[slot][item] = event.target.checked;
          // Checking Ascension is a user choice: mark the grade entry so the
          // backend keeps it off the baseline (only meaningful when a grade
          // entry exists to carry the flag).
          if (event.target.checked && state.gearUpgrades[slot]?.[item]) {
            state.gearUpgrades[slot][item].user_selected = true;
          }
          const craftedGrade = card.querySelector('.crafted-grade-select');
          if (craftedGrade) {
            craftedGrade.disabled = !event.target.checked;
            syncCraftedAscensionEntry(slot, item, craftedGrade.value);
          }
          event.currentTarget.closest('.voidforge-field-container')?.classList.toggle('is-active', event.target.checked);
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
      }
      const craftedGradeSelect = card.querySelector('.crafted-grade-select');
      if (craftedGradeSelect) {
        craftedGradeSelect.addEventListener('change', () => {
          syncCraftedAscensionEntry(slot, item, craftedGradeSelect.value);
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
      }
      const upgradeTrigger = card.querySelector('.upgrade-trigger');
      if (upgradeTrigger) {
        const pop = card.querySelector('.popover');
        wirePopover(upgradeTrigger, pop);
        pop.addEventListener('change', () => {
          card.querySelector('.upgrade-state').textContent = upgradeStateText(slot, item);
        });
      }
      itemGrid.appendChild(card);
    }

    // t_2ab8f3be: slot collapse (doc 4.2) — selected + top 3 visible, rest
    // behind a toggle so 42-card slots stop dominating the tab order.
    const cards = [...itemGrid.children];
    let collapsedCount = 0;
    cards.forEach((card, index) => {
      if (index >= 3 && !card.classList.contains('is-selected')) {
        card.classList.add('is-collapsed');
        collapsedCount += 1;
      }
    });
    if (collapsedCount) {
      const showAll = document.createElement('button');
      showAll.type = 'button';
      showAll.className = 'btn-ghost slot-show-all';
      showAll.setAttribute('aria-expanded', 'false');
      const label = `Show all ${cards.length} items (${collapsedCount} hidden)`;
      showAll.textContent = label;
      showAll.addEventListener('click', () => {
        const open = itemGrid.classList.toggle('is-expanded');
        showAll.setAttribute('aria-expanded', String(open));
        showAll.textContent = open ? 'Show fewer' : label;
      });
      itemGrid.after(showAll);
    }

    if ((state.appConfig.gems?.standard || []).length) {
      const socketControl = document.createElement('label');
      socketControl.className = 'extra-socket-control';
      socketControl.innerHTML = `<input type="checkbox"> Add/test an extra socket on ${escapeHtml(slot.replace('_', ' '))}`;
      socketControl.querySelector('input').addEventListener('change', event => {
        state.extraSockets[slot] = event.target.checked;
        selectionChanged();
      });
      group.appendChild(socketControl);
    }
    grid.appendChild(group);
  }
  refreshWowheadLinks();
  renderSlotConflict();
}
