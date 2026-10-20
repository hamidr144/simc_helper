// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: season)

import { itemLevelFromLabel, parseItemParams } from './items.js';
import { apiFetch } from '../core/api.js';

const FALLBACK_SEASON = {
  id: 'midnight-s1-offline',
  name: 'Midnight Season 1 (offline data)',
  crest_name: 'Dawncrest',
  cost_per_rank: 20,
  tracks: {
    adventurer: [220, 224, 227, 230, 233, 237],
    veteran: [233, 237, 240, 243, 246, 250],
    champion: [246, 250, 253, 256, 259, 263],
    hero: [259, 263, 266, 269, 272, 276],
    myth: [272, 276, 279, 282, 285, 289]
  },
  elevated_ilvls: [],
  ascension: {
    name: 'Ascendant Voidforged',
    cost: 5,
    bonus_ids: ['13653', '13654'],
    eligible_slots: ['main_hand', 'off_hand', 'trinket', 'trinket1', 'trinket2'],
    results: { hero: 285, myth: 298 },
    legacy_bonus_ilvl: 9,
    legacy_final_ilvls: [285, 298]
  }
};
export let upgradeData = null;
let activeSeason = null;
export function season() { return activeSeason || FALLBACK_SEASON; }
export function seasonTracks() { return season().tracks || {}; }
export function seasonAscension() { return season().ascension || {}; }
export function isElevatedLevel(level) {
  return level != null && (season().elevated_ilvls || []).includes(Number(level));
}
export async function loadUpgradeData() {
  try {
    const response = await apiFetch('api/upgrade-data');
    if (!response.ok) return;
    upgradeData = await response.json();
    activeSeason = (upgradeData.seasons || [])
      .find(item => item.id === upgradeData.active_season) || null;
    renderSeasonChip();
  } catch (error) {
    console.warn('Upgrade data endpoint unavailable, using offline ladder', error);
  }
}
export function renderSeasonChip() {
  const chip = document.getElementById('season-chip');
  if (chip) chip.textContent = season().name || '';
}
export function detectSeasonFromExport(data) {
  // Mirror the server rule: live-first, older seasons for archived exports.
  if (!upgradeData) return;
  const levels = [];
  for (const items of Object.values(data.items_by_slot || {})) {
    for (const item of items) {
      const level = Number(parseItemParams(item).ilevel) ||
        itemLevelFromLabel((data.item_names || {})[item]);
      if (level) levels.push(level);
    }
  }
  if (!levels.length) return;
  const top = Math.max(...levels);
  const seasons = upgradeData.seasons || [];
  const inBand = s => s.ilvl_band && top >= s.ilvl_band[0] && top <= s.ilvl_band[1];
  const active = seasons.find(s => s.id === upgradeData.active_season);
  if (active && inBand(active)) { activeSeason = active; return; }
  const matches = seasons.filter(inBand);
  if (matches.length) activeSeason = matches.reduce((a, b) => b.ilvl_band[1] > a.ilvl_band[1] ? b : a);
}
