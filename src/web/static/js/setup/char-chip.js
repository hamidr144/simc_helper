// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/char-chip)

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

/* WoW class colors — identity accent only; the accent system stays --accent-*. */
const CLASS_COLORS = {
  deathknight: '#c41f3b', demonhunter: '#a335ee', druid: '#ff7c0a',
  evoker: '#33937f', hunter: '#aad372', mage: '#3fc7eb',
  monk: '#00ff98', paladin: '#f48cba', priest: '#ffffff',
  rogue: '#fff468', shaman: '#2459ff', warlock: '#8788ee',
  warrior: '#c69b66'
};
export function renderCharChip() {
  const chip = document.getElementById('char-chip');
  if (!chip || !state.parsedData) return;
  const cls = String(state.parsedData.char_class || '').toLowerCase();
  const color = CLASS_COLORS[cls] || 'var(--accent-text)';
  const slots = Object.keys(state.parsedData.items_by_slot || {}).length;
  const candidates = Object.values(state.parsedData.items_by_slot || {})
    .reduce((total, items) => total + items.length, 0);
  chip.hidden = false;
  chip.innerHTML = `<span class="char-class-dot" style="background:${color};color:${color}"></span>` +
    `<b>${escapeHtml(state.parsedData.char_name)}</b> ${escapeHtml(cls ? cls[0].toUpperCase() + cls.slice(1) : 'Unknown class')}` +
    ` · ${candidates} candidate items in ${slots} slots`;
}

/* ---------- Paste flow ---------- */
