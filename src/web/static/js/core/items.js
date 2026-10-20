// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: items)

import { state } from './state.js';

import { season, seasonAscension, seasonTracks } from './season.js';

export function parseItemParams(item) {
  return Object.fromEntries(
    String(item || '').split(',').filter(part => part.includes('='))
      .map(part => {
        const index = part.indexOf('=');
        return [part.slice(0, index).trim(), part.slice(index + 1).trim()];
      })
  );
}
export function normalizedEquippedItems(slot) {
  if (!state.parsedData) return [];
  if (slot === 'finger') {
    return [state.parsedData.equipped_gear.finger1, state.parsedData.equipped_gear.finger2].filter(Boolean);
  }
  if (slot === 'trinket') {
    return [state.parsedData.equipped_gear.trinket1, state.parsedData.equipped_gear.trinket2].filter(Boolean);
  }
  return [state.parsedData.equipped_gear[slot]].filter(Boolean);
}
export function isCraftedItem(item) {
  return item.includes('crafting_quality=') || item.includes('crafted_stats=');
}
export function isVoidforgeEligibleSlot(slot) {
  const base = String(slot || '').split('_')[0];
  const slots = new Set((seasonAscension().eligible_slots || []).map(s => String(s).split('_')[0]));
  return slots.has(base);
}
function hasVoidforgeBonus(item) {
  const ids = (seasonAscension().bonus_ids || []).map(String);
  const bonuses = (parseItemParams(item).bonus_id || '').split('/');
  return bonuses.some(bonus => ids.includes(bonus));
}
export function itemLevelFromLabel(label) {
  const match = String(label || '').match(/\((\d+)\)/);
  return match ? Number(match[1]) : null;
}
export function inferMidnightUpgrade(slot, item, label) {
  if (isCraftedItem(item)) return null;
  let level = Number(parseItemParams(item).ilevel) || itemLevelFromLabel(label);
  if (!level) return null;
  const ascension = seasonAscension();
  const alreadyAscended = isVoidforgeEligibleSlot(slot) && hasVoidforgeBonus(item);
  if (alreadyAscended) {
    // Ascended items sit above the ladder; map back to the track's top rank.
    for (const [track, ascended] of Object.entries(ascension.results || {})) {
      if (Number(ascended) === level && seasonTracks()[track]) {
        return { track, rank: seasonTracks()[track].length, item_level: level };
      }
    }
    const legacyDelta = ascension.legacy_bonus_ilvl;
    if (legacyDelta) level -= legacyDelta;
  }
  for (const [track, levels] of Object.entries(seasonTracks())) {
    const rank = levels.indexOf(level) + 1;
    if (rank > 0) return { track, rank, item_level: level };
  }
  return null;
}

/* Upgrade ranks straight from the export's own `# upgrade_levels=` comment
   (authoritative for this character), preferred over the static season
   ladders whenever present.  The addon lists only levels other than the
   item's current one, with ilvl increments relative to the current ilvl,
   so rank 0 is "Current" and ranks 1..N are the export-provided upgrades. */
export function exportRanksFor(slot, item) {
  const info = state.parsedData?.item_upgrades?.[item];
  const levels = Array.isArray(info?.levels) ? info.levels : null;
  if (!levels || !levels.length) return null;
  const current = Number(parseItemParams(item).ilevel) ||
    itemLevelFromLabel(state.parsedData?.item_names?.[item]);
  if (!current) return null;
  return [
    { rank: 0, level: current, label: 'Current' },
    ...levels.map((lvl, index) => ({
      rank: index + 1,
      level: current + (Number(lvl.ilvl_increment) || 0),
      label: `Upgrade ${lvl.upgrade_level}`
    })),
  ];
}
export function isAlreadyVoidforgedItem(slot, item, label = '') {
  const ascendedName = String(seasonAscension().name || '').toLowerCase().replace('ascendant ', '');
  return isVoidforgeEligibleSlot(slot) && (
    hasVoidforgeBonus(item) ||
    (ascendedName && String(label).toLowerCase().includes(ascendedName))
  );
}
export const SLOT_LABELS = { main_hand: 'Main Hand', off_hand: 'Off Hand' };
export const PAPER_DOLL_SLOTS = ['head', 'neck', 'shoulder', 'back', 'chest', 'wrist',
  'hands', 'waist', 'legs', 'feet', 'finger', 'trinket', 'main_hand', 'off_hand'];

export function twoHandedConflict() {
  const main = state.selectedItems.main_hand || new Set();
  const off = state.selectedItems.off_hand || new Set();
  if (!main.size || !off.size) return null;
  for (const item of main) if (state.twoHandedItems.has(item)) return { slot: 'main_hand', other: 'off_hand' };
  for (const item of off) if (state.twoHandedItems.has(item)) return { slot: 'off_hand', other: 'main_hand' };
  return null;
}
