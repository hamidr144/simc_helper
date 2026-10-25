// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/enhancements)
// RED-3: the step-3 panel is the page's single enhancements surface (the
// per-slot enh-chips are deleted, design contract §6), and the old per-slot
// "extra socket" checkbox lives here (decision D-6).
// t_76a0ceb9 directives 5/10/11: the trio sections (Gems, Enchantments,
// Augurnium) are static markup inside #enh-card (hidden until an import
// lands) and start OPEN (supersedes the t_16e4f177 close-all ruling — the
// leader directive is explicit). Every entry carries the same Wowhead tooltip
// anchor pattern the gear rows use.
import { state } from '../core/state.js';

import { PAPER_DOLL_SLOTS } from '../core/items.js';

import { createEnhancementWowheadLink, refreshWowheadLinks } from '../core/wowhead.js';

import { selectionChanged } from './runbar.js';

// shortcut: PVP meta gems are excluded by name substring; upgrade to item-id
// filtering when the backend exposes gem ids.
const PVP_META_NAME_MATCH = /heliotrope/i;
export const visibleEnchants = enchants => enchants.filter(entry => entry.quality !== 2);
function appendWowheadLink(group, enhancement, name) {
  const wrapper = document.createElement('span');
  wrapper.innerHTML = createEnhancementWowheadLink(enhancement, name);
  if (wrapper.firstElementChild?.tagName === 'A') group.appendChild(wrapper.firstElementChild);
}
function sectionBody(group) {
  return document
    .querySelector(`#enhancement-options [data-enh-group="${group}"] .enh-body`);
}
function addFieldset(body, legend) {
  const group = document.createElement('fieldset');
  group.className = 'enhancement-group';
  const label = document.createElement('legend');
  label.textContent = legend;
  group.appendChild(label);
  body.appendChild(group);
  return group;
}
/* Selection state shows in the section summary (count), never as helper text. */
function wireSummaryLabel(section) {
  const summary = section.querySelector('summary');
  const title = section.dataset.enhGroup;
  const renderLabel = () => {
    const chips = section.querySelectorAll('.choice-chip[aria-pressed="true"]').length;
    const total = section.querySelectorAll('.choice-chip[aria-pressed]').length;
    summary.textContent = chips ? `${title} · ${chips} selected` : `${title} (${total})`;
  };
  renderLabel();
  if (!section.dataset.labelBound) {
    section.dataset.labelBound = '1';
    section.addEventListener('click', renderLabel);
  }
  return renderLabel;
}
export function renderEnhancements() {
  const trio = document.getElementById('enhancement-options');
  const bodies = {
    Gems: sectionBody('Gems'),
    Enchantments: sectionBody('Enchantments'),
    Augurnium: sectionBody('Augurnium'),
  };
  for (const body of Object.values(bodies)) body.innerHTML = '';

  // Enchantments: one fieldset per paper-doll slot that has a configured list.
  for (const [slot, enchants] of Object.entries(state.appConfig.enchantments || {})) {
    if (!enchants.length || !PAPER_DOLL_SLOTS.includes(slot)) continue;
    const group = addFieldset(bodies.Enchantments, slot.replace('_', ' '));
    for (const enchant of visibleEnchants(enchants)) {
      const id = String(typeof enchant === 'object' ? enchant.id : enchant);
      const name = typeof enchant === 'object' ? enchant.name : `Enchant ${id}`;
      const equipped = state.equippedEnchants[slot].has(id);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `choice-chip${state.selectedEnchants[slot].has(id) || equipped ? ' selected' : ''}`;
      button.setAttribute('aria-pressed', String(state.selectedEnchants[slot].has(id) || equipped));
      button.setAttribute('aria-label', `Select ${name}`);
      button.title = name;
      button.textContent = name;
      if (equipped) {
        const badge = document.createElement('span');
        badge.className = 'equipped-badge';
        badge.textContent = 'equipped';
        button.appendChild(badge);
      }
      button.addEventListener('click', () => {
        const selected = !button.classList.contains('selected');
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
        if (selected) state.selectedEnchants[slot].add(id);
        else state.selectedEnchants[slot].delete(id);
        selectionChanged();
      });
      group.appendChild(button);
      appendWowheadLink(group, enchant, name);
    }
  }

  const gems = (state.appConfig.gems?.standard || []).filter(gem =>
    !PVP_META_NAME_MATCH.test(String(gem.name || ''))
  );
  if (gems.length) {
    const group = addFieldset(bodies.Gems, 'Flawless gems');
    for (const gem of gems) {
      const id = String(typeof gem === 'object' ? gem.id : gem);
      const name = typeof gem === 'object' ? gem.name : `Gem ${id}`;
      const equipped = state.equippedGems.has(id);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `choice-chip${state.selectedGems.has(id) || equipped ? ' selected' : ''}`;
      button.setAttribute('aria-pressed', String(state.selectedGems.has(id) || equipped));
      button.setAttribute('aria-label', `Select ${name}`);
      button.title = name;
      button.textContent = name;
      if (equipped) {
        const badge = document.createElement('span');
        badge.className = 'equipped-badge';
        badge.textContent = 'equipped';
        button.appendChild(badge);
      }
      button.addEventListener('click', () => {
        const selected = !button.classList.contains('selected');
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
        if (selected) state.selectedGems.add(id);
        else state.selectedGems.delete(id);
        selectionChanged();
      });
      group.appendChild(button);
      appendWowheadLink(group, gem, name);
    }
  }

  const metaGems = state.appConfig.gems?.meta || [];
  if (metaGems.length) {
    const group = addFieldset(bodies.Gems, 'Meta gems');
    for (const gem of metaGems) {
      const id = String(typeof gem === 'object' ? gem.id : gem);
      const name = typeof gem === 'object' ? gem.name : `Meta gem ${id}`;
      const equipped = state.equippedGems.has(id);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `choice-chip${state.selectedMetaGems.has(id) || equipped ? ' selected' : ''}`;
      button.setAttribute('aria-pressed', String(state.selectedMetaGems.has(id) || equipped));
      button.setAttribute('aria-label', `Select ${name}`);
      button.title = name;
      button.textContent = name;
      if (equipped) {
        const badge = document.createElement('span');
        badge.className = 'equipped-badge';
        badge.textContent = 'equipped';
        button.appendChild(badge);
      }
      button.addEventListener('click', () => {
        const selected = !button.classList.contains('selected');
        state.selectedMetaGems.clear();
        if (selected) state.selectedMetaGems.add(id);
        for (const option of group.querySelectorAll('button.choice-chip')) {
          const pressed = state.selectedMetaGems.has(option.dataset.id);
          option.classList.toggle('selected', pressed);
          option.setAttribute('aria-pressed', String(pressed));
        }
        selectionChanged();
      });
      button.dataset.id = id;
      group.appendChild(button);
      appendWowheadLink(group, gem, name);
    }
  }

  // D-6 (design contract): the per-slot "extra socket" experiment checkbox
  // lived under each gear group before; enhancements are one panel now.
  if ((state.appConfig.gems?.standard || []).length && state.parsedData) {
    const group = addFieldset(bodies.Gems, 'Extra test sockets');
    for (const slot of Object.keys(state.parsedData.items_by_slot || {})) {
      const label = document.createElement('label');
      label.className = 'choice-chip';
      label.setAttribute('aria-label', `Test an extra socket on ${slot.replace('_', ' ')}`);
      label.innerHTML = `<input type="checkbox"${state.extraSockets[slot] ? ' checked' : ''}> ${slot.replace('_', ' ')}`;
      label.querySelector('input').addEventListener('change', event => {
        state.extraSockets[slot] = event.target.checked;
        selectionChanged();
      });
      group.appendChild(label);
    }
  }

  // t_76a0ceb9 directive 10: Augurnium is its own section.
  // shortcut: current-season config.json ships no augurnium entries, and
  // payload.js is frozen — the chips ride client state only. The section
  // renders when the backend ever ships `appConfig.augurnium` entries.
  const augurnium = state.appConfig.augurnium || [];
  if (augurnium.length) {
    const group = addFieldset(bodies.Augurnium, 'Augurnium');
    for (const entry of augurnium) {
      const id = String(typeof entry === 'object' ? entry.id : entry);
      const name = typeof entry === 'object' ? entry.name : `Augurnium ${id}`;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `choice-chip${state.selectedAugurnium.has(id) ? ' selected' : ''}`;
      button.setAttribute('aria-pressed', String(state.selectedAugurnium.has(id)));
      button.setAttribute('aria-label', `Select ${name}`);
      button.title = name;
      button.textContent = name;
      button.addEventListener('click', () => {
        const selected = !button.classList.contains('selected');
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
        if (selected) state.selectedAugurnium.add(id);
        else state.selectedAugurnium.delete(id);
        selectionChanged();
      });
      group.appendChild(button);
      appendWowheadLink(group, entry, name);
    }
  }

  for (const section of trio.querySelectorAll('.enh-section')) wireSummaryLabel(section);

  // Search narrows chips inside the always-open sections (t_76a0ceb9
  // directive 10 replaced the close-all + open-on-search dance).
  const search = document.getElementById('enh-search');
  search.value = '';
  search.oninput = () => {
    const needle = search.value.trim().toLowerCase();
    trio.querySelectorAll('.enh-section').forEach(section => {
      let visible = 0;
      section.querySelectorAll('.choice-chip').forEach(chip => {
        const hit = !needle || chip.textContent.toLowerCase().includes(needle);
        chip.hidden = !hit;
        if (hit) visible += 1;
      });
      section.querySelectorAll('fieldset').forEach(fieldset => {
        const hits = [...fieldset.querySelectorAll('.choice-chip')].filter(chip => !chip.hidden).length;
        fieldset.querySelectorAll('legend').forEach(legend => { legend.hidden = Boolean(needle) && !hits; });
        fieldset.hidden = Boolean(needle) && !hits;
      });
      section.hidden = Boolean(needle) && visible === 0;
    });
  };
  refreshWowheadLinks();
}
