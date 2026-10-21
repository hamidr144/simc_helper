// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: items)

import { state } from './state.js';

import { isElevatedLevel, season, seasonAscension, seasonTracks } from './season.js';

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
/* GSE-2 t_0769a998: crafting_quality is the addon's raw craft tier (Blizzard
   GetItemCraftedQualityByItemInfo), a five-tier scale 0-5; out-of-range
   integers stay raw. Never infer a tier from crafted_stats or ilvl. */
export function craftedBadgeHtml(item) {
  const raw = parseItemParams(item).crafting_quality;
  if (/^\d+$/.test(raw || '')) {
    const n = Number(raw);
    const label = n <= 5 ? `Crafted · Quality ${n}/5` : `Crafted · Grade ${n}`;
    return `${label} (from the addon export)`;
  }
  return 'Crafted · no grade (the addon export did not include a crafting quality)';
}

function isVoidforgeEligibleSlot(slot) {
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
/* CRIT t_632eeef0: real addon exports and Armory loads never carry
   `# upgrade_levels=`, so exportRanksFor is null for every real character
   and the rank/ascension affordance was unreachable in production (t_6b3f65d6).
   Fallback: read the item's already-inferred grade — Wowhead hydration or
   ilvl inference lands in state.gearUpgrades as {track, rank} — and walk the
   season ladder from there. Flood guard (leader ruling comment 1885): only
   equipped / selected / added items expand; every other candidate keeps its
   single base row.
   shortcut: crafted items skip this — they are off-track (ascension resolves
   via crafted_results elsewhere) and the grade popover was deleted in the
   redesign. */
function seasonFallbackRanks(slot, item) {
  if (isCraftedItem(item)) return null;
  if (!normalizedEquippedItems(slot).includes(item)
    && !state.selectedItems[slot]?.has(item)
    && !state.addedItems.has(item)) return null;
  // onRowClick drops the gearUpgrades entry on deselect AND writes a bare
  // {source:'export',rank,item_level} on select — fall back to the same
  // ilvl→ladder inference state.js seeds with so rows never vanish.
  let info = state.gearUpgrades[slot]?.[item];
  if (!info?.track) info = inferMidnightUpgrade(slot, item, state.parsedData?.item_names?.[item]);
  const ladder = info?.track ? seasonTracks()[info.track] : null;
  const rank = Number(info?.rank) || 0;
  if (!ladder || !rank || rank > ladder.length) return null;
  const crest = `${season().cost_per_rank} ${season().crest_name}`;
  const trackName = info.track[0].toUpperCase() + info.track.slice(1);
  const rows = [];
  for (let r = rank + 1; r <= ladder.length; r++) {
    rows.push({ rank: r, track: info.track, ilvl: ladder[r - 1], voidforged: false,
      label: `${trackName} ${r}/${ladder.length} ×${crest}` });
  }
  const ascension = seasonAscension();
  const current = Number(parseItemParams(item).ilevel)
    || itemLevelFromLabel(state.parsedData?.item_names?.[item]) || null;
  if (rank === ladder.length && ascension.results?.[info.track] != null
    && isVoidforgeEligibleSlot(slot) && !isElevatedLevel(current)
    && !isAlreadyVoidforgedItem(slot, item, state.parsedData?.item_names?.[item])) {
    rows.push({ rank, track: info.track, ilvl: ascension.results[info.track], voidforged: true,
      label: `${ascension.name || 'Ascendant'} ×${ascension.cost}` });
  }
  return rows;
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

/* ---- RED-3 design model (contract §9.2): the ONE slot list. Order, labels,
   ring×2/trinket×2 expansion and the 2H off-hand hide live only here; render
   loops iterate SLOT_SECTIONS. `slot` = the payload-side key (payload.js
   frozen: finger/trinket pools and selectedItems keys unchanged); `equipKeys`
   = equipped_gear keys whose items render as equipped cards in the section. */
export const SLOT_SECTIONS = [
  { key: 'head', label: 'Head', slot: 'head', equipKeys: ['head'] },
  { key: 'neck', label: 'Neck', slot: 'neck', equipKeys: ['neck'] },
  { key: 'shoulder', label: 'Shoulders', slot: 'shoulder', equipKeys: ['shoulder'] },
  { key: 'back', label: 'Back', slot: 'back', equipKeys: ['back'] },
  { key: 'chest', label: 'Chest', slot: 'chest', equipKeys: ['chest'] },
  { key: 'wrist', label: 'Wrist', slot: 'wrist', equipKeys: ['wrist'] },
  { key: 'hands', label: 'Hands', slot: 'hands', equipKeys: ['hands'] },
  { key: 'waist', label: 'Waist', slot: 'waist', equipKeys: ['waist'] },
  { key: 'legs', label: 'Legs', slot: 'legs', equipKeys: ['legs'] },
  { key: 'feet', label: 'Feet', slot: 'feet', equipKeys: ['feet'] },
  { key: 'finger1', label: 'Ring 1', slot: 'finger', equipKeys: ['finger1'] },
  { key: 'finger2', label: 'Ring 2', slot: 'finger', equipKeys: ['finger2'] },
  { key: 'trinket', label: 'Trinkets', slot: 'trinket', equipKeys: ['trinket1', 'trinket2'] },
  { key: 'main_hand', label: 'Main Hand', slot: 'main_hand', equipKeys: ['main_hand'] },
  { key: 'off_hand', label: 'Off Hand', slot: 'off_hand', equipKeys: ['off_hand'],
    // data-driven §7: a two-handed main hand occupies both weapon slots.
    hideWhen: () => equippedTwoHanded() },
];

/* §7 R-C3: B.quality map — number (tooltip batch) or name fallback; class +
   grade word resolve through here, never per item/slot. */
const QUALITY = {
  common: { cls: 'common', word: 'Common' },
  uncommon: { cls: 'uncommon', word: 'Uncommon' },
  rare: { cls: 'rare', word: 'Rare' },
  epic: { cls: 'epic', word: 'Epic' },
  legendary: { cls: 'epic', word: 'Legendary' },
};
const QUALITY_BY_NUMBER = { 0: 'common', 1: 'common', 2: 'uncommon', 3: 'rare', 4: 'epic', 5: 'legendary', 6: 'epic', 7: 'artifact' };
export function qualityOf(quality) {
  const name = String(QUALITY_BY_NUMBER[quality] ?? quality ?? '').toLowerCase();
  return QUALITY[name] || { cls: 'common', word: name ? name[0].toUpperCase() + name.slice(1) : 'Common' };
}

/* t_e906dc02: the ONE row-grade resolver feeding qualityOf (§7 R-C3: class +
   grade word resolve through qualityOf, never per item/slot).  Precedence
   (leader ruling 3): Wowhead-hydration quality number
   (state.wowheadQualities, conflict.js) ?? Armory payload grade word
   (parsedData.item_qualities, /api/armory-load) ?? explicit quality= param.
   qualityOf's COMMON stays the only true fallback.  Keyed by item string —
   quality belongs to the item+bonus identity, not the slot. */
export function resolveRowQuality(item) {
  return state.wowheadQualities?.[item]
    ?? state.parsedData?.item_qualities?.[item]
    ?? parseItemParams(item).quality;
}

/* R-C3 rank/variant expansion (contract §3): base row per item, plus one row
   per export-ladder upgrade rank (upgrade_levels comment, authoritative and
   still preferred), plus the season-ladder fallback rows for real (comment
   -free) gear — see seasonFallbackRanks for that ladder, the flood guard and
   the crafted shortcut. Items neither source can grade keep their single
   inferred row (the old grade popover is deleted; expanding 6 ranks × every
   item would flood the list). */
export function ranksForItem(slot, item) {
  const rows = [{ rank: null, track: null, ilvl: null, voidforged: false }];
  const exportRanks = exportRanksFor(slot, item);
  if (!exportRanks) return rows.concat(seasonFallbackRanks(slot, item) || []);
  for (const rank of exportRanks.slice(1)) {
    rows.push({ rank: rank.rank, track: null, ilvl: rank.level, voidforged: false, label: rank.label });
  }
  const top = exportRanks[exportRanks.length - 1];
  const ascended = isAlreadyVoidforgedItem(slot, item, state.parsedData?.item_names?.[item]);
  if (!ascended && isVoidforgeEligibleSlot(slot) && !isElevatedLevel(Number(parseItemParams(item).ilevel) || null)) {
    rows.push({ rank: top.rank, track: null, ilvl: top.level, voidforged: true, label: `${seasonAscension().name || 'Ascendant'}` });
  }
  return rows;
}

/* §7: off-hand hides when the EQUIPPED main hand is two-handed (W.two_handed
   arrives async via hydrateWowheadUpgrades; renderGear re-runs after it). */
function equippedTwoHanded() {
  const main = (state.parsedData?.equipped_gear || {}).main_hand || '';
  return Boolean(main) && state.twoHandedItems.has(main);
}



export function twoHandedConflict() {
  const main = state.selectedItems.main_hand || new Set();
  const off = state.selectedItems.off_hand || new Set();
  if (!main.size || !off.size) return null;
  for (const item of main) if (state.twoHandedItems.has(item)) return { slot: 'main_hand', other: 'off_hand' };
  for (const item of off) if (state.twoHandedItems.has(item)) return { slot: 'off_hand', other: 'main_hand' };
  return null;
}
