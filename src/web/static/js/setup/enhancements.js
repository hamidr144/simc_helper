// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/enhancements)

import { state } from '../core/state.js';

import { PAPER_DOLL_SLOTS } from '../core/items.js';

import { createEnhancementWowheadLink, refreshWowheadLinks } from '../core/wowhead.js';

import { selectionChanged } from './runbar.js';

// TG2-A (design t_0fbfd0bd §3.1): enhancement state chips on the slot-group
// header — pure state echo of step-3 selections plus a jump-and-open shortcut.
// No new state: labels recompute from state.selectedEnchants/state.selectedGems live.
// TG2-F (t_61442157): worn items are pre-checked without entering the selected
// sets, so the chip counts the UNION with the equipped sets to match the
// step-3 panel's checked count by construction.
export function enhancementChipLabel(kind, slot) {
  if (kind === 'enchants') {
    if (!(state.appConfig.enchantments?.[slot] || []).length) return null;
    const k = new Set([...(state.selectedEnchants[slot] || []), ...(state.equippedEnchants[slot] || [])]).size;
    const e = state.equippedEnchants[slot]?.size || 0;
    return `Enchants: ${k} selected` + (e > 0 && e < k ? ` · worn ${e}` : '');
  }
  if (!(state.appConfig.gems?.standard || []).length) return null;
  const k = new Set([...state.selectedGems, ...state.equippedGems]).size;
  return k ? `Gems: ${k} selected` : 'Gems: none';
}
export function syncEnhancementChips() {
  document.querySelectorAll('.enh-chip').forEach(chip => {
    const label = enhancementChipLabel(chip.dataset.kind, chip.dataset.slot);
    if (label) chip.textContent = label;
  });
}
export function jumpToEnhancement(kind, slot) {
  document.getElementById('step-enhance')?.scrollIntoView({ block: 'start' });
  // Mirror generate_input.py's off_hand -> main_hand enchant-list fallback.
  const titles = kind === 'gems'
    ? ['Flawless gems']
    : (slot === 'off_hand'
      ? [`${slot.replace('_', ' ')} enchants`, 'main hand enchants']
      : [`${slot.replace('_', ' ')} enchants`]);
  const sections = [...document.querySelectorAll('#enhancement-options .enh-section')];
  for (const title of titles) {
    const section = sections.find(s => s.dataset.enhTitle === title);
    if (section) {
      section.open = true;
      section.querySelector('summary')?.focus();
      return;
    }
  }
}
// shortcut: PVP meta gems are excluded by name substring; upgrade to item-id
// filtering when the backend exposes gem ids.
const PVP_META_NAME_MATCH = /heliotrope/i;
export function renderEnhancements() {
  const container = document.getElementById('enhancement-options');
  container.innerHTML = '';
  // t_2ab8f3be (doc 4.3): 68 flat checkboxes -> searchable, grouped <details>
  // sections. t_16e4f177 (leader ruling, supersedes doc 4.2 open-if-checked
  // clause): ALL groups start closed — the doc's clause forced every group
  // holding an equipped/checked candidate open, keeping 136 chip stops
  // permanently in the tab order. Selection state stays visible in the
  // summary label instead; the search input opens matches on demand.
  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'enh-search';
  search.placeholder = 'Search enchantments and gems\u2026';
  search.setAttribute('aria-label', 'Search enchantments and gems');
  container.appendChild(search);

  const addSection = (title, build) => {
    const section = document.createElement('details');
    section.className = 'enh-section';
    section.dataset.enhTitle = title; // chips open sections by stable title (§3.1)
    const summary = document.createElement('summary');
    const group = document.createElement('fieldset');
    group.className = 'enhancement-group';
    build(group);
    const total = group.querySelectorAll('input').length;
    const renderLabel = () => {
      const checked = group.querySelectorAll('input:checked').length;
      summary.textContent = checked
        ? `${title} \u00b7 ${checked} selected`
        : `${title} (${total})`;
    };
    renderLabel();
    group.addEventListener('change', renderLabel);
    section.append(summary, group);
    container.appendChild(section);
  };

  for (const [slot, enchants] of Object.entries(state.appConfig.enchantments || {})) {
    if (!enchants.length || !PAPER_DOLL_SLOTS.includes(slot)) continue;
    addSection(`${slot.replace('_', ' ')} enchants`, group => {
      for (const enchant of enchants) {
        const id = String(typeof enchant === 'object' ? enchant.id : enchant);
        const name = typeof enchant === 'object' ? enchant.name : `Enchant ${id}`;
        const equipped = state.equippedEnchants[slot].has(id);
        const label = document.createElement('label');
        label.className = 'choice-chip';
        label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(enchant, name)}` +
          (equipped ? '<span class="equipped-badge">equipped</span>' : '');
        const input = label.querySelector('input');
        input.checked = state.selectedEnchants[slot].has(id) || equipped;
        input.addEventListener('change', event => {
          if (event.target.checked) state.selectedEnchants[slot].add(id);
          else {
            state.selectedEnchants[slot].delete(id);
            state.equippedEnchants[slot].delete(id);
          }
          selectionChanged();
        });
        group.appendChild(label);
      }
    });
  }

  const gems = (state.appConfig.gems?.standard || []).filter(gem =>
    !PVP_META_NAME_MATCH.test(String(gem.name || ''))
  );
  if (gems.length) {
    addSection('Flawless gems', group => {
      group.className = 'enhancement-group gems-group';
      for (const gem of gems) {
        const id = String(typeof gem === 'object' ? gem.id : gem);
        const name = typeof gem === 'object' ? gem.name : `Gem ${id}`;
        const equipped = state.equippedGems.has(id);
        const label = document.createElement('label');
        label.className = 'choice-chip';
        label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(gem, name)}` +
          (equipped ? '<span class="equipped-badge">equipped</span>' : '');
        const input = label.querySelector('input');
        input.checked = state.selectedGems.has(id) || equipped;
        input.addEventListener('change', event => {
          if (event.target.checked) state.selectedGems.add(id);
          else {
            state.selectedGems.delete(id);
            state.equippedGems.delete(id);
          }
          selectionChanged();
        });
        group.appendChild(label);
      }
    });
  }

  const metaGems = state.appConfig.gems?.meta || [];
  if (metaGems.length) {
    const metaInputs = [];
    addSection('Meta gems', group => {
      group.className = 'enhancement-group meta-gems-group';
      for (const gem of metaGems) {
        const id = String(typeof gem === 'object' ? gem.id : gem);
        const name = typeof gem === 'object' ? gem.name : `Meta gem ${id}`;
        const equipped = state.equippedGems.has(id);
        const label = document.createElement('label');
        label.className = 'choice-chip';
        label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(gem, name)}` +
          (equipped ? '<span class="equipped-badge">equipped</span>' : '');
        const input = label.querySelector('input');
        input.dataset.id = id;
        input.checked = state.selectedMetaGems.has(id) || equipped;
        metaInputs.push(input);
        input.addEventListener('change', event => {
          for (const prev of state.selectedMetaGems) state.equippedGems.delete(prev);
          state.selectedMetaGems.clear();
          state.equippedGems.delete(id);
          if (event.target.checked) state.selectedMetaGems.add(id);
          for (const el of metaInputs) el.checked = state.selectedMetaGems.has(el.dataset.id);
          selectionChanged();
        });
        group.appendChild(label);
      }
    });
  }

  // NB4 (review t_89761608): remember which sections the SEARCH opened so
  // clearing the query re-closes exactly those, never user-opened ones.
  const searchOpened = new Set();
  search.addEventListener('input', () => {
    const needle = search.value.trim().toLowerCase();
    container.querySelectorAll('.enh-section').forEach(section => {
      let visible = 0;
      section.querySelectorAll('.choice-chip').forEach(chip => {
        const hit = !needle || chip.textContent.toLowerCase().includes(needle);
        chip.hidden = !hit;
        if (hit) visible += 1;
      });
      section.hidden = Boolean(needle) && visible === 0;
      if (needle && visible) {
        if (!section.open) searchOpened.add(section); // user-opened stays user-owned
        section.open = true;
      } else if (!needle && searchOpened.has(section)) {
        section.open = false;
        searchOpened.delete(section);
      }
    });
  });
  refreshWowheadLinks();
}
