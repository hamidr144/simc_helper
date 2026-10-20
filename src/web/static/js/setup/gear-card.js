// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/gear-card)

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { exportRanksFor, isCraftedItem, isVoidforgeEligibleSlot, itemLevelFromLabel, parseItemParams } from '../core/items.js';

import { isElevatedLevel, season, seasonAscension, seasonTracks } from '../core/season.js';

import { targetUpgradeLevel } from './preview.js';

function renderTrackControls(slot, item) {
  if (isCraftedItem(item)) return '';
  const upgrade = state.gearUpgrades[slot]?.[item] || {};
  const currentLevel = Number(parseItemParams(item).ilevel) ||
    itemLevelFromLabel(state.parsedData?.item_names?.[item]);
  const exportRanks = exportRanksFor(slot, item);
  if (!exportRanks && isElevatedLevel(currentLevel)) return '';
  const trackOptions = ['none', ...Object.keys(seasonTracks())]
    .map(track => `<option value="${track}" ${upgrade.track === track ? 'selected' : ''}>${track === 'none' ? 'No grade' : track[0].toUpperCase() + track.slice(1)}</option>`)
    .join('');
  const levels = exportRanks || seasonTracks()[upgrade.track] || [];
  const rankOptions = exportRanks
    ? exportRanks.map(rank => `<option value="${rank.rank}" ${upgrade.rank === rank.rank ? 'selected' : ''}>${escapeHtml(rank.label)} · ilvl ${rank.level}</option>`).join('')
    : levels.map((level, index) =>
        `<option value="${index + 1}" ${upgrade.rank === index + 1 ? 'selected' : ''}>Rank ${index + 1} · ${level}</option>`
      ).join('');
  return `<select class="gear-track-select" aria-label="Track">${trackOptions}</select><select class="gear-rank-select" aria-label="Rank" ${levels.length ? '' : 'disabled'}>${levels.length ? rankOptions : '<option value="">Rank</option>'}</select>`;
}

/* Grade-state badges get one slot on every card (.gear-card-badges) so
   their placement never varies between cards. */
/* GSE-2 t_0769a998: crafting_quality is the addon's raw craft tier (Blizzard
   GetItemCraftedQualityByItemInfo), a five-tier scale 0-5; out-of-range
   integers stay raw. Never infer a tier from crafted_stats or ilvl. */
function craftedBadgeHtml(item) {
  const raw = parseItemParams(item).crafting_quality;
  if (/^\d+$/.test(raw || '')) {
    const n = Number(raw);
    const label = n <= 5 ? `Crafted · Quality ${n}/5` : `Crafted · Grade ${n}`;
    const quality = n <= 5 ? `${n}/5` : `${n}`;
    return `<span class="crafted-badge" title="Crafting quality ${quality} from the addon export">${label}</span>`;
  }
  return '<span class="crafted-badge" title="The addon export did not include a crafting quality">Crafted · no grade</span>';
}
export function cardBadges(slot, item) {
  const badges = [];
  if (isCraftedItem(item)) {
    badges.push(craftedBadgeHtml(item));
  } else {
    const currentLevel = Number(parseItemParams(item).ilevel) ||
      itemLevelFromLabel(state.parsedData?.item_names?.[item]);
    if (!exportRanksFor(slot, item) && isElevatedLevel(currentLevel)) {
      badges.push('<span class="crafted-badge">Elevated · not upgradeable</span>');
    }
  }
  return `<div class="gear-card-badges">${badges.join('')}</div>`;
}

/* ---------- Live upgrade preview (Wowhead tooltip proxy) ---------- */
export function syncCraftedAscensionEntry(slot, item, value) {
  delete state.gearUpgrades[slot][item];
  if (value && value !== 'none' && state.voidforgedItems[slot]?.[item]) {
    state.gearUpgrades[slot][item] = { track: value, rank: 1, user_selected: true };
  }
}
export function upgradeStateText(slot, item) {
  const upgrade = state.gearUpgrades[slot]?.[item];
  const level = targetUpgradeLevel(slot, item);
  const bits = [];
  if (upgrade?.track) bits.push(upgrade.track[0].toUpperCase() + upgrade.track.slice(1) + (upgrade.rank ? ` ${upgrade.rank}` : ''));
  else if (upgrade?.source === 'export') bits.push('Export ladder');
  else if (isCraftedItem(item)) bits.push('Crafted');  // GSE-2: crafted has no track ladder
  else bits.push('No grade');
  if (level != null) bits.push(`ilvl ${level}`);
  return bits.join(' \u00b7 ');
}
export function upgradePopoverMarkup(slot, item) {
  const controls = renderTrackControls(slot, item);
  const currentLevel = Number(parseItemParams(item).ilevel) ||
    itemLevelFromLabel(state.parsedData?.item_names?.[item]);
  // t_60c19e5d: Elevated Myth gear (344) is not Ascendant-eligible.
  const ascensionEligible = isVoidforgeEligibleSlot(slot) && !isElevatedLevel(currentLevel);
  // t_98470ac5: a crafted base has no season ladder to infer a grade from
  // (crafted ilvls live off-track), so the ascended grade is picked by hand.
  const craftedTracks = ascensionEligible && isCraftedItem(item)
    ? Object.keys(seasonAscension().crafted_results || {}) : [];
  const craftedGrade = craftedTracks.length
    ? `<select class="crafted-grade-select" aria-label="Ascended grade" ${state.voidforgedItems[slot][item] ? '' : 'disabled'}>${['none', ...craftedTracks]
        .map(track => `<option value="${track}" ${state.gearUpgrades[slot]?.[item]?.track === track ? 'selected' : ''}>${track === 'none' ? 'Ascended grade\u2026' : track[0].toUpperCase() + track.slice(1)}</option>`)
        .join('')}</select>`
    : '';
  const voidforge = ascensionEligible
    ? `<label class="voidforge-field-container"><input type="checkbox" class="voidforge-input" ${state.voidforgedItems[slot][item] ? 'checked' : ''}> ${seasonAscension().name || 'Ascendant'} \u00d7${seasonAscension().cost ?? ''}</label>`
    : '';
  if (!controls && !voidforge) return '';
  return `<div class="gear-card-controls popover-host">` +
    `<span class="upgrade-state">${escapeHtml(upgradeStateText(slot, item))}</span>` +
    `<button type="button" class="btn-ghost upgrade-trigger" aria-expanded="false" aria-haspopup="dialog">Upgrade\u2026</button>` +
    `<div class="popover" hidden>${controls}${craftedGrade}${voidforge}<div class="upgrade-preview" hidden></div></div></div>`;
}
