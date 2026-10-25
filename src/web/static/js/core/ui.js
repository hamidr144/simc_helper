// js/core/ui.js — RED-3 shared render atoms + the ONE item-row component
// (design contract §9.3). Ported from the mock's data.js helpers (verbatim
// semantics, data-fed); gear and results pages share every piece here so a
// future visual change never needs to touch two renderers.
import { escapeHtml as esc } from './dom.js';
import { createWowheadIconLink } from './wowhead.js';
import { qualityOf } from './items.js';

/* formatters (data.js port): thousand separators everywhere, signed deltas  */
export const fmt = n => (n == null || Number.isNaN(Number(n)))
  ? '?' : Number(n).toLocaleString('en-US');

/* mock-only fallback, kept for img onerror only (real item icons ship) */
function initials(name) {
  return String(name || '').replace(/[^A-Za-zÀ-ž' ]/g, '')
    .split(/[ ’]+/).filter(Boolean).slice(0, 2)
    .map(word => word[0]).join('').toUpperCase() || '?';
}

/* real item icon (icon policy): img over the initials monogram — if the icon
   proxy fails, the img removes itself and the monogram shows through. */
function iconHtml(d) {
  const q = qualityOf(d.quality);
  const cls = q.cls === 'epic' ? ' epic' : q.cls === 'rare' ? ' rare' : '';
  const size = d.size ? ` ${d.size}` : '';
  // link:true = equipped/result cards: one anchor (icon+tooltip, t_2ab8f3be
  // merged-link rule). vrow candidates stay plain img: no nesting interactive
  // elements inside the native row button (keyboard contract).
  const img = !d.id ? ''
    : d.link ? createWowheadIconLink(d.id, d.bonus ?? '', '')
    : `<img src="api/item-icon/${encodeURIComponent(d.id)}" alt="" loading="lazy" onerror="this.remove()">`;
  return `<span class="ic${cls}${size}" aria-hidden="true">${img}${esc(initials(d.name))}</span>`;
}

function modsHtml(ench, gem) {
  const mods = (ench ? `<span class="mod ench" title="Enchant: ${esc(ench)}">⚡ ${esc(ench)}</span>` : '')
    + (gem ? `<span class="mod gem" title="Gem: ${esc(gem)}">◆ ${esc(gem)}</span>` : '');
  return mods ? `<span class="mods">${mods}</span>` : '';
}

function stateTag(d) {
  if (d.ex) return '<span class="tag ex">excluded</span> ';
  if (d.sel) return '<span class="tag sel">selected</span> ';
  return '';
}

/* pre-run delta pill — CONTRACT OVERRIDE §7/R-6: ilvl only, % never exists
   before a run. delta == 0 renders the zip's `base` chip. */
export function ilvlDeltaHtml(delta) {
  if (!delta) return '<span class="d eq">base</span>';
  return `<span class="d il-d ${delta > 0 ? 'up' : 'dn'} num">${delta > 0 ? '+' : '−'}${Math.abs(delta)} ilvl</span>`;
}

/* ONE component, four grid variants (contract §9.3): the same six cells in
   different skins — page CSS only re-skins (setup.css .eqc/.vrow, results.css
   .candup/.setcard). d = {id,name,quality,ilvl,ench,gem,sel,ex,deltaHtml,
   slotLabel,slotTag,aria,size} */
export function itemRow(variant, d) {
  const q = qualityOf(d.quality);
  const icon = iconHtml(d);
  const delta = d.deltaHtml ?? '<span class="d eq">base</span>';
  if (variant === 'eqc') {
    const aria = d.aria ?? `Equipped ${d.slotLabel || ''}${d.slotTag ? ' ' + d.slotTag : ''}: ${d.name}, item level ${d.ilvl ?? '?'}, ${q.word}${d.ench ? ', enchanted ' + d.ench : ''}${d.gem ? ', socketed ' + d.gem : ''}. Click a candidate below to swap.`;
    return `<div class="st eqc" role="img" aria-label="${esc(aria)}">
      ${iconHtml({ ...d, size: 'big' })}
      <span class="eqx"><span class="nm q-${q.cls}" title="${esc(d.name)}">${esc(d.name)}</span>
        ${modsHtml(d.ench, d.gem)}</span>
      <span class="il num">${d.ilvl ?? '—'}</span><span class="grd ${q.cls}">${q.word}</span>
      <span class="d eq">base</span></div>`;
  }
  if (variant === 'vrow') {
    return `<button type="button" class="cand vrow${d.sel ? ' sel' : ''}${d.ex ? ' ex' : ''}"
      ${d.ex || d.disabled ? 'disabled' : ''} aria-pressed="${Boolean(d.sel)}"
      title="${esc(d.title ?? d.name)}"
      data-item="${esc(d.item ?? '')}"${d.rank ? ` data-rank="${esc(String(d.rank))}"` : ''}${d.voidforged ? ' data-vf="1"' : ''}>
      ${icon}
      <span class="name q-${q.cls}" title="${esc(d.name)}">${stateTag(d)}${esc(d.name)}${d.ench ? '<span class="modi" title="enchant / modifier">⚡</span>' : ''}</span>
      <span class="il num">${d.ilvl ?? '—'}</span>
      <span class="grd ${q.cls}">${q.word}</span>${delta}
    </button>`;
  }
  // results variants: the caller wraps (button/rowfoot state lives there)
  return `${icon}
    <span class="name q-${q.cls}" title="${esc(d.name)}">${stateTag(d)}${esc(d.name)}${d.ench ? '<span class="modi" title="enchant / modifier">⚡</span>' : ''}</span>
    <span class="il num">${d.ilvl ?? '—'}</span>
    <span class="grd ${q.cls}">${q.word}</span>${delta}`;
}

/* chip/row overflow folds to +N (zip foldChips port; DOM post-pass).
   RED-3 doc 4.2 parity: selected/excluded rows never fold away.
   RED-S5F (contract §12 gate 4, RED-S5 FAIL 2): the fold budget counts every
   row, selected or not — a selection must never reveal an extra row, so the
   section geometry stays fixed when a visible row is toggled. */
export function foldChips(host, max) {
  const kids = [...host.children].filter(el => !el.classList.contains('fold'));
  if (kids.length <= max) return;
  const fold = kids.slice(max).filter(el => !el.classList.contains('sel') && !el.classList.contains('ex'));
  fold.forEach(el => { el.hidden = true; });
  if (!fold.length) return;
  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'fold chip';
  more.textContent = `+${fold.length}`;
  more.setAttribute('aria-expanded', 'false');
  more.addEventListener('click', () => {
    fold.forEach(el => { el.hidden = false; });
    more.remove();
  });
  host.appendChild(more);
}
// shortcut: rows that fold away on DE-select (a parity-selected row beyond the
// budget) or re-fold after a +N expand still move layout; upgrade only if that
// flow ever persists the expanded state across renders.

export { esc };

/* Contract §toast: shared transient status pill (results apply flow reuses
   .toast from tokens.css). role=status, auto-dismiss after 5 s. */
export function toast(text) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.setAttribute('role', 'status');
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}
