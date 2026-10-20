// js/results/model.js — results data model (t_94a15fe3 port of results.js):
// baseline pick, per-slot diff, human labels, A2 best-combination gear list.
import { PAPER_DOLL_SLOTS } from '../core/items.js';

function itemId(item) {
  return String(item || '').match(/(?:^|,)id=(\d+)/)?.[1] || '';
}

function itemBonus(item) {
  const match = String(item || '').match(/(?:^|,)bonus=([\d/]+)/);
  return match ? match[1] : '';
}

// TG3-D2 baseline pick: prefer the actor named in ?baseline (the real
// character with equipped gear). When the report has no such run, fall back
// to the HIGHEST-DPS healthy actor — never the name-sorted first row — and
// let the caller label the card honestly (no baseline run => say so).
export function pickBaseline(healthy, baselineName) {
  const equipped = healthy.find(result => result.name === baselineName);
  if (equipped) return { baseline: equipped, isEquipped: true };
  if (!healthy.length) return { baseline: null, isEquipped: false };
  const top = healthy.reduce((best, r) => (Number(r.dps) > Number(best.dps) ? r : best));
  return { baseline: top, isEquipped: false };
}

export function changesFromBaseline(candidate, baseline) {
  const changes = [];
  const slots = new Set([...Object.keys(baseline.gear || {}), ...Object.keys(candidate.gear || {})]);
  for (const slot of slots) {
    const baseItem = baseline.gear?.[slot] || '';
    const before = itemId(baseItem);
    const after = itemId(candidate.gear?.[slot]);
    if (after && after !== before) {
      // TG3-G gap 5: carry the replaced equipped item so the chip tooltip can
      // name it (peer pattern: candidate-shown-beside-equipped).
      changes.push({ slot: slot.replaceAll('_', ' '), id: after, bonus: itemBonus(candidate.gear[slot]), before, beforeBonus: itemBonus(baseItem) });
    }
  }
  return changes;
}

// TG3-G gap 4: human labels for engine copy names ("<char>_Combo_12" from
// cli/generate_input.py, "<char>_head_3" from generate-simc single_swap).
// The machine name stays in the row title tooltip; unknown names
// (user-embedded copies) fall back verbatim — never fabricate a label.
export function candidateLabel(name) {
  const text = String(name || '');
  const combo = text.match(/^.*_Combo_(\d+)(?:,|$)/);
  if (combo) return `Combination #${combo[1]}`;
  const swap = text.match(/^(?:.+)_(head|neck|shoulder|shoulders|back|chest|wrist|wrists|hands|waist|legs|feet|finger1?|finger2|trinket1?|trinket2|main_hand|off_hand)_(\d+)$/);
  if (swap) {
    const slot = swap[1].replace(/_/g, ' ').replace(/(\d)$/, ' $1').replace(/^./, (c) => c.toUpperCase());
    return `${slot} swap`;
  }
  return text;
}

// A2 (MGE-2 §2): best combination, slot-by-slot — doll slots in the MGE-2 §6
// order (finger1/2 and trinket1/2 inherit the finger/trinket group position),
// the BEST row's item where it changed a slot and the baseline's otherwise
// (unchanged slots included — "slot-by-slot" means all slots). Slots the
// report does not know render nothing; unknown report keys append after.
export function bestGearChanges(topRow, baseline) {
  const gear = { ...(baseline?.gear || {}), ...(topRow?.gear || {}) };
  const keys = [];
  for (const group of PAPER_DOLL_SLOTS) {
    for (const key of Object.keys(gear)
      .filter(k => k === group || k.startsWith(`${group}1`) || k.startsWith(`${group}2`))
      .sort()) keys.push(key);
  }
  for (const key of Object.keys(gear)) if (!keys.includes(key)) keys.push(key);
  const changes = [];
  for (const key of keys) {
    const id = itemId(gear[key]);
    if (!id) continue;
    changes.push({ slot: key.replaceAll('_', ' '), id, bonus: itemBonus(gear[key]), before: '', beforeBonus: '' });
  }
  return changes;
}
