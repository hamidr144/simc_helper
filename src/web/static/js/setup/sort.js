// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/sort)

import { state } from '../core/state.js';

import { itemLevelFromLabel, parseItemParams } from '../core/items.js';

import { setWorkflowStatus } from './runbar.js';
import { apiFetch } from '../core/api.js';

const STAT_SORT_BATCH = 40;
export function sortItemsForSlot(slot, items) {
  const mode = state.slotSorts[slot] || 'ilvl';
  const levelOf = item => itemLevelFromLabel(state.parsedData?.item_names?.[item]) ||
    Number(parseItemParams(item).ilevel) || 0;
  const nameOf = item => String(state.parsedData?.item_names?.[item] || '')
    .replace(/\s*\(\d+\)$/, '').toLowerCase();
  const sorted = [...items];
  if (mode === 'name') {
    sorted.sort((a, b) => nameOf(a).localeCompare(nameOf(b)) || levelOf(b) - levelOf(a));
  } else if (mode === 'priority') {
    // Failed lookups score -1 and sink to the bottom; ties fall back to ilvl.
    sorted.sort((a, b) => ((state.statScores[b] ?? -1) - (state.statScores[a] ?? -1)) ||
      levelOf(b) - levelOf(a));
  } else {
    sorted.sort((a, b) => levelOf(b) - levelOf(a));
  }
  return sorted;
}
export async function ensureStatScores(slot, items, selectEl) {
  const pending = items.filter(item => !(item in state.statScores) && parseItemParams(item).id);
  if (!pending.length) return;
  if (selectEl) { selectEl.disabled = true; selectEl.classList.add('is-scoring'); }
  try {
    for (let start = 0; start < pending.length; start += STAT_SORT_BATCH) {
      const chunk = pending.slice(start, start + STAT_SORT_BATCH);
      const response = await apiFetch('api/wowhead/tooltips/batch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          char_class: state.parsedData.char_class,
          items: chunk.map(item => {
            const params = parseItemParams(item);
            return { item: Number(params.id), bonus: params.bonus_id || null };
          })
        })
      });
      if (!response.ok) throw new Error(`status ${response.status}`);
      const data = await response.json();
      (data.results || []).forEach((result, position) => {
        const key = chunk[result.index ?? position];
        if (key) state.statScores[key] = result.ok ? (result.score ?? 0) : -1;
      });
    }
  } catch (error) {
    setWorkflowStatus(`Stat-priority sort unavailable (${error.message}) — sorted by ilvl instead.`);
    if (state.slotSorts[slot] === 'priority') state.slotSorts[slot] = 'ilvl';
  } finally {
    if (selectEl) { selectEl.disabled = false; selectEl.classList.remove('is-scoring'); }
  }
}

/* ---------- Add-an-item by Wowhead id (items owned but not exported) ---------- */
