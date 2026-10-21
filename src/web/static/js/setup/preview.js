// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/preview)
// RED-3 (decision D-9, light): the in-card upgrade-preview DOM is gone —
// the same Wowhead tooltip delta now renders as the candidate row's native
// title (hover + focus, zero new surfaces). Delta logic and caching verbatim.
import { state } from '../core/state.js';

import { isCraftedItem, itemLevelFromLabel, parseItemParams } from '../core/items.js';

import { seasonAscension, seasonTracks } from '../core/season.js';
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

export function scheduleUpgradePreview(slot, item, row) {
  const key = `${slot}|${item}`;
  clearTimeout(upgradePreviewTimers.get(key));
  upgradePreviewTimers.set(key, setTimeout(() => {
    upgradePreviewTimers.delete(key);
    void fetchUpgradePreview(slot, item, row);
  }, UPGRADE_PREVIEW_DEBOUNCE_MS));
}

async function fetchUpgradePreview(slot, item, row) {
  const params = parseItemParams(item);
  const target = targetUpgradeLevel(slot, item);
  const current = Number(params.ilevel) ||
    itemLevelFromLabel(state.parsedData?.item_names?.[item]) || null;
  if (!params.id || !target || !current || target === current) return;
  const query = new URLSearchParams({ item: params.id, ilvl: String(target) });
  const bonusIds = String(params.bonus_id || '').split('/')
    .filter(value => /^\d+$/.test(value)).join(':');
  if (bonusIds) query.set('bonus', bonusIds);
  const url = `api/wowhead/tooltip?${query}`;
  try {
    let data = upgradePreviewCache.get(url);
    if (!data) {
      const response = await apiFetch(url);
      if (!response.ok) throw new Error(`status ${response.status}`);
      data = await response.json();
      upgradePreviewCache.set(url, data);
    }
    if (!row.isConnected) return;
    const preview = data.preview || {};
    const delta = data.delta || {};
    const resulting = preview.ilvl ?? target;
    const ilvlDelta = delta.ilvl ??
      (resulting != null && current != null ? resulting - current : null);
    let text = `ilvl ${current} → ${resulting ?? '?'}`;
    if (ilvlDelta) text += ` (${ilvlDelta > 0 ? '+' : '−'}${Math.abs(ilvlDelta)})`;
    for (const stat of (delta.stats || []).slice(0, 4)) {
      text += ` · ${stat.label} ${stat.delta > 0 ? '+' : '−'}${Math.abs(stat.delta).toLocaleString()}`;
    }
    row.title = text;
  } catch {
    // silent: the static row title (name + ilvl) already tells the truth;
    // shortcut: no visible failure state, upgrade to a toast if users ask.
  }
}
