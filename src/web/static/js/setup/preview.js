// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/preview)

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { isCraftedItem, itemLevelFromLabel, parseItemParams } from '../core/items.js';

import { season, seasonAscension, seasonTracks } from '../core/season.js';
import { apiFetch } from '../core/api.js';

const upgradePreviewCache = new Map();
const upgradePreviewTimers = new Map();
const UPGRADE_PREVIEW_DEBOUNCE_MS = 400;
export function targetUpgradeLevel(slot, item) {
  const upgrade = state.gearUpgrades[slot]?.[item];
  if (!upgrade) return null;
  const ascension = seasonAscension();
  if (state.voidforgedItems[slot]?.[item]) {
    // A crafted base ascends to the season's lower crafted_results ilvl
    // (mirror of backend apply_gear_upgrade); track items use results.
    const crafted = isCraftedItem(item) ? ascension.crafted_results?.[upgrade.track] : null;
    const target = crafted != null ? crafted : ascension.results?.[upgrade.track];
    if (target != null) return Number(target);
  }
  // Export-provided entries carry their own absolute ilvl.
  if (upgrade.source === 'export' && upgrade.item_level != null) {
    return Number(upgrade.item_level);
  }
  if (!upgrade.track) return null;
  const levels = seasonTracks()[upgrade.track] || [];
  return levels[upgrade.rank - 1] ?? null;
}

/* Crafted ascension (t_98470ac5): the backend resolves crafted_results from
   the upgrade track, so an ascended grade must land on state.gearUpgrades — but
   only while the Ascendant checkbox is checked, because crafted bases have
   no ladder upgrade of their own.  rank is the backend contract's needed
   placeholder; the ascended ilvl replaces it during generation. */
export function scheduleUpgradePreview(slot, item, card) {
  const key = `${slot}|${item}`;
  clearTimeout(upgradePreviewTimers.get(key));
  upgradePreviewTimers.set(key, setTimeout(() => {
    upgradePreviewTimers.delete(key);
    void fetchUpgradePreview(slot, item, card);
  }, UPGRADE_PREVIEW_DEBOUNCE_MS));
}
function renderUpgradePreview(host, data, target, current) {
  const preview = data.preview || {};
  const delta = data.delta || {};
  const resulting = preview.ilvl ?? target;
  const ilvlDelta = delta.ilvl ??
    (resulting != null && current != null ? resulting - current : null);
  const dot = preview.quality_color
    ? `<span class="upgrade-preview-dot" style="background:${escapeHtml(preview.quality_color)}"></span>`
    : '';
  let html = `${dot}<span class="upgrade-preview-ilvl">ilvl ${current ?? '?'} → <b>${resulting ?? '?'}</b>`;
  if (ilvlDelta) {
    html += ` <b class="upgrade-preview-delta ${ilvlDelta > 0 ? 'positive' : 'negative'}">` +
      `${ilvlDelta > 0 ? '+' : '−'}${Math.abs(ilvlDelta)}</b>`;
  }
  html += '</span>';
  const stats = (delta.stats || []).slice(0, 4);
  if (stats.length) {
    html += '<span class="upgrade-preview-stats">' + stats.map(stat =>
      `<span class="upgrade-preview-stat ${stat.delta > 0 ? 'positive' : 'negative'}">` +
      `${escapeHtml(stat.label)} ${stat.delta > 0 ? '+' : '−'}${Math.abs(stat.delta).toLocaleString()}</span>`
    ).join('') + '</span>';
  }
  host.className = 'upgrade-preview';
  host.innerHTML = html;
}
async function fetchUpgradePreview(slot, item, card) {
  const host = card.querySelector('.upgrade-preview');
  if (!host) return;
  const params = parseItemParams(item);
  const target = targetUpgradeLevel(slot, item);
  const current = Number(params.ilevel) ||
    itemLevelFromLabel(state.parsedData?.item_names?.[item]) || null;
  if (!params.id || !target || !current || target === current) {
    host.hidden = true;
    host.textContent = '';
    return;
  }
  const query = new URLSearchParams({ item: params.id, ilvl: String(target) });
  const bonusIds = String(params.bonus_id || '').split('/')
    .filter(value => /^\d+$/.test(value)).join(':');
  if (bonusIds) query.set('bonus', bonusIds);
  const url = `api/wowhead/tooltip?${query}`;
  host.hidden = false;
  host.className = 'upgrade-preview is-loading';
  host.textContent = 'Previewing upgrade…';
  try {
    let data = upgradePreviewCache.get(url);
    if (!data) {
      const response = await apiFetch(url);
      if (!response.ok) throw new Error(`status ${response.status}`);
      data = await response.json();
      upgradePreviewCache.set(url, data);
    }
    if (!card.isConnected) return;
    renderUpgradePreview(host, data, target, current);
  } catch (error) {
    if (!card.isConnected) return;
    host.className = 'upgrade-preview is-unavailable';
    host.textContent = 'preview unavailable';
    host.title = `Wowhead preview unavailable (${error.message})`;
  }
}

/* ---------- Per-slot sorting (ilvl / name / heuristic stat priority) ---------- */
