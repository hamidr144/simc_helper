// js/results/chips.js — batch-resolved item chips (t_94a15fe3 port of
// results.js chip layer). One chunked batch request feeds every chip on the
// page: ranked-row diffs, their replaced items, and the A2 best-combination ids.
import { apiFetch } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { changesFromBaseline } from './model.js';

const chipInfo = new Map();

export async function resolveChips(ranked, reference, extraChanges = []) {
  const wanted = new Map();
  const collect = (change) => {
    if (change.id && !wanted.has(change.id)) wanted.set(change.id, change.bonus);
    // Gap 5: the replaced equipped items resolve through the SAME batch path
    // (their ids join one chunked request) — no new endpoint.
    if (change.before && !wanted.has(change.before)) wanted.set(change.before, change.beforeBonus);
  };
  for (const result of ranked) {
    for (const change of changesFromBaseline(result, reference)) collect(change);
  }
  extraChanges.forEach(collect); // A2: best-combination ids, same endpoint, one request
  if (!wanted.size) return;
  const ids = [...wanted.keys()];
  const chunks = [];
  for (let i = 0; i < ids.length; i += 40) chunks.push(ids.slice(i, i + 40));
  await Promise.all(chunks.map(async (chunk) => {
    try {
      const response = await apiFetch('api/wowhead/tooltips/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          char_class: null,
          items: chunk.map(id => ({ item: Number(id), bonus: wanted.get(id) || null })),
        }),
      });
      if (!response.ok) return;
      const data = await response.json();
      for (const entry of data.results || []) {
        if (entry.ok) chipInfo.set(String(entry.item), entry);
      }
    } catch { /* chips fall back to bare ids */ }
  }));
}

export function chipHtml(change) {
  const info = chipInfo.get(change.id);
  const bonusQuery = change.bonus ? `?bonus=${encodeURIComponent(change.bonus.replaceAll('/', ':'))}` : '';
  const href = `https://www.wowhead.com/item=${encodeURIComponent(change.id)}${bonusQuery}`;
  if (!info) {
    return `<span class="chip-pending">${escapeHtml(change.slot)} #${escapeHtml(change.id)}</span>`;
  }
  // Gap 5: replaces-context in the tooltip, resolved via the same batch path.
  const base = change.before ? chipInfo.get(change.before) : null;
  const replaces = base ? ` replaces ${base.name} (ilvl ${base.ilvl ?? '?'})` : '';
  const color = info.quality_color ? ` style="color:${escapeHtml(info.quality_color)}"` : '';
  return `<a class="item-chip" href="${href}" target="_blank" rel="noopener" title="${escapeHtml(`${info.name} (ilvl ${info.ilvl ?? '?'})${replaces}`)}">` +
    `<img src="api/item-icon/${encodeURIComponent(change.id)}" alt="" loading="lazy">` +
    `<span${color}>${escapeHtml(info.name)}</span><span class="item-chip-slot">${escapeHtml(change.slot)}</span></a>`;
}
