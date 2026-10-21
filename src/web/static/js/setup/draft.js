// js/setup/draft.js — RED-3 draft persistence + apply-back queue (design
// contract §10), frontend-only. Draft = the gear page's whole client state,
// debounce-persisted per character under simc-draft-v1:<char>; the results
// page writes simc-apply before navigating back. Freshness gate 30 days.
// shortcut: ~100–300 KB JSON against a 5 MB quota; server-side drafts would
// need a backend change (contract §11 R-7 — only via leader ruling).
import { state } from '../core/state.js';

const DRAFT_PREFIX = 'simc-draft-v1:';
const APPLY_KEY = '********';
const MAX_AGE_S = 30 * 24 * 3600;
let persistTimer = null;

export function persistDraft() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    if (!state.parsedData) return;
    try {
      localStorage.setItem(DRAFT_PREFIX + state.parsedData.char_name, JSON.stringify({
        savedAt: Math.floor(Date.now() / 1000),
        parsedData: state.parsedData,
        selectedItems: Object.fromEntries(Object.entries(state.selectedItems).map(([slot, items]) => [slot, [...items]])),
        selectedEnchants: Object.fromEntries(Object.entries(state.selectedEnchants).map(([slot, ids]) => [slot, [...ids]])),
        selectedGems: [...state.selectedGems],
        selectedMetaGems: [...state.selectedMetaGems],
        gearUpgrades: state.gearUpgrades,
        voidforgedItems: state.voidforgedItems,
        extraSockets: state.extraSockets,
        slotLocks: state.slotLocks,
        addedItems: [...state.addedItems],
        fightStyle: document.getElementById('fight-style')?.value || '',
        compareMode: document.getElementById('compare-mode')?.value || '',
      }));
    } catch { /* quota/private mode: draft is an enhancement, never an error */ }
  }, 800);
}

/* Fresh drafts across characters, newest first. Stale/corrupt keys are
   dropped on sight. Returns the raw drafts (boot needs savedAt fields). */
export function loadDrafts() {
  const out = [];
  try {
    for (let i = localStorage.length - 1; i >= 0; i -= 1) {
      const key = localStorage.key(i);
      if (!key?.startsWith(DRAFT_PREFIX)) continue;
      let draft = null;
      try { draft = JSON.parse(localStorage.getItem(key)); } catch { draft = null; }
      const fresh = draft?.parsedData?.char_name
        && Math.floor(Date.now() / 1000) - (draft.savedAt || 0) <= MAX_AGE_S;
      if (!fresh) { localStorage.removeItem(key); continue; }
      out.push(draft);
    }
  } catch { /* storage unavailable: behave as no draft */ }
  return out.sort((a, b) => b.savedAt - a.savedAt);
}

/* t_e906dc02 (leader ruling 4): stale simc-apply / simc-draft localStorage
   restores candidate state wholesale, so a prior session's item string can
   come back with no row in the current parse (no name, no ilvl, renders as
   'item <id>' and leaks into payloads).  Orphan-drop on restore; gear.js
   keeps the 'item <id>' literal as the last-resort render fallback. */
function knownCandidate(slot, item) {
  return (state.parsedData?.items_by_slot?.[slot] || []).includes(item);
}

/* Restore explicit user state on top of a re-initialized selection layer:
   equipped pre-checks run first (same path as a fresh import), then the
   user's stored picks overlay them. Restoration is user-explicit per §10 —
   the never-auto-select rule is not violated. */
export function applyDraftToState(draft) {
  state.slotLocks = { ...state.slotLocks, ...(draft.slotLocks || {}) };
  state.extraSockets = { ...state.extraSockets, ...(draft.extraSockets || {}) };
  for (const [key, slot] of draft.addedItems || []) {
    if (knownCandidate(slot, key)) state.addedItems.set(key, slot);
  }
  for (const [slot, ids] of Object.entries(draft.selectedEnchants || {})) {
    (state.selectedEnchants[slot] ||= new Set());
    for (const id of ids) state.selectedEnchants[slot].add(id);
  }
  for (const id of draft.selectedGems || []) state.selectedGems.add(id);
  if (draft.selectedMetaGems?.length) {
    // meta gems are single-select: only take the draft pick when equipped
    // pre-check left nothing selected.
    if (!state.selectedMetaGems.size) {
      for (const id of draft.selectedMetaGems) {
        state.selectedMetaGems.add(id);
        state.equippedGems.add(id);
      }
    }
  }
  for (const [slot, items] of Object.entries(draft.selectedItems || {})) {
    (state.selectedItems[slot] ||= new Set());
    for (const item of items) {
      if (knownCandidate(slot, item)) state.selectedItems[slot].add(item);
    }
  }
  for (const [slot, byItem] of Object.entries(draft.gearUpgrades || {})) {
    for (const [item, entry] of Object.entries(byItem)) {
      if (entry?.user_selected) (state.gearUpgrades[slot] ||= {})[item] = entry;
    }
  }
  for (const [slot, byItem] of Object.entries(draft.voidforgedItems || {})) {
    for (const [item, on] of Object.entries(byItem)) {
      if (on) (state.voidforgedItems[slot] ||= {})[item] = true;
    }
  }
}

/* results → gear apply queue: results writes the chosen combo's payload
   (the shape buildPayload() produced) right before navigating back. */
export function writeApply(payload, run) {
  try {
    localStorage.setItem(APPLY_KEY, JSON.stringify(
      { payload, run, at: Math.floor(Date.now() / 1000) }));
  } catch { /* drop */ }
}
export function consumeApply() {
  try {
    const raw = localStorage.getItem(APPLY_KEY);
    if (!raw) return null;
    localStorage.removeItem(APPLY_KEY);
    const data = JSON.parse(raw);
    const fresh = data?.payload?.char_name
      && Math.floor(Date.now() / 1000) - (data.at || 0) <= MAX_AGE_S;
    return fresh ? data : null;
  } catch { return null; }
}

/* Inverse of payload.js buildPayload() (payload.js stays FROZEN; this map
   lives here per contract §10). Explicit user action from the results page —
   replaces, never merges. */
export function applyPayloadToState(payload) {
  state.selectedItems = Object.fromEntries(Object.entries(payload.selected_items || {})
    .map(([slot, items]) => [slot, new Set(items.filter(item => knownCandidate(slot, item)))]));
  for (const [slot, ids] of Object.entries(payload.selected_enchants || {})) {
    state.selectedEnchants[slot] = new Set(ids);
  }
  state.selectedGems = new Set(payload.selected_gems || []);
  state.selectedMetaGems = new Set(payload.selected_meta_gems || []);
  state.gearUpgrades = { ...(payload.gear_upgrades || {}) };
  state.voidforgedItems = { ...(payload.voidforged_items || {}) };
  state.extraSockets = { ...(payload.extra_sockets || {}) };
  if (payload.fight_style) {
    const el = document.getElementById('fight-style');
    if (el && [...el.options].some(o => o.value === payload.fight_style)) el.value = payload.fight_style;
  }
  if (payload.mode) {
    const el = document.getElementById('compare-mode');
    if (el && [...el.options].some(o => o.value === payload.mode)) el.value = payload.mode;
  }
}

export function clearDraftKeys() {
  try {
    for (const key of [...Object.keys(localStorage)]) {
      if (key.startsWith(DRAFT_PREFIX) || key === APPLY_KEY) localStorage.removeItem(key);
    }
  } catch { /* nothing to clear */ }
}
