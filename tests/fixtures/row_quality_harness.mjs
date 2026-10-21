// Hermetic harness (t_e906dc02, fold_chips_harness.mjs pattern) for the REAL
// modules: resolveRowQuality precedence — Wowhead hydration ?? Armory payload
// item_qualities ?? quality= param ?? qualityOf's COMMON (leader ruling 3,
// contract §7 R-C3: grade resolves through qualityOf, never per item/slot) —
// and the draft/payload restore orphan-drop (leader ruling 4: stale
// localStorage entries absent from items_by_slot must not come back).
// Usage: node row_quality_harness.mjs — prints one JSON object.
import { state } from '../../src/web/static/js/core/state.js';
import { qualityOf, resolveRowQuality } from '../../src/web/static/js/core/items.js';
import { applyDraftToState, applyPayloadToState } from '../../src/web/static/js/setup/draft.js';

const KNOWN = 'id=268265,bonus_id=6652,ilevel=334';   // real Hamidriel neck (truncated bonuses)
const ORPHAN = 'id=273781,ilevel=332';                // the t_e906dc02 stale-candidate repro

state.parsedData = {
  char_name: 'Harness',
  items_by_slot: { neck: [KNOWN] },
  equipped_gear: {},
  item_names: { [KNOWN]: 'Aqirbane Reliquary (334)' },
  item_qualities: { [KNOWN]: 'epic' },
};

const out = {};

// --- resolver precedence ------------------------------------------------------
state.wowheadQualities = {};
out.armoryGrade = qualityOf(resolveRowQuality(KNOWN)).word;            // Epic (payload beats param)
state.wowheadQualities = { [KNOWN]: 3 };
out.hydrationWins = qualityOf(resolveRowQuality(KNOWN)).word;          // Rare (hydration beats payload)
delete state.parsedData.item_qualities[KNOWN];
out.paramFallback = qualityOf(resolveRowQuality('id=1,quality=2')).word; // Uncommon
out.commonFallback = qualityOf(resolveRowQuality('id=1')).word;        // Common (only true fallback)

// --- draft restore --------------------------------------------------------------
// Stale SELECTED-only strings are still orphan-dropped (ruling 4), but
// addedItems keys are authoritative and get re-inserted (t_65bd1b07 ruling).
const ADDED = 'id=271472';
state.parsedData.items_by_slot.shoulder = [',id=271463,ilevel=330'];
state.selectedItems = { neck: new Set(), shoulder: new Set() };
state.addedItems = new Map();
applyDraftToState({
  parsedData: {
    item_names: { [ADDED]: 'Blessed Batplate Spaulders (337)' },
    item_qualities: { [ADDED]: 4 },  // PR #47 committed shape
  },
  selectedItems: { neck: [KNOWN, ORPHAN], shoulder: [ADDED] },
  addedItems: [[KNOWN, 'neck'], [ADDED, 'shoulder']],
});
out.draftSelected = [...state.selectedItems.neck];        // ORPHAN (selected-only) dropped
out.draftAdded = [...state.addedItems.keys()];
out.addedReinserted = state.parsedData.items_by_slot.shoulder;
out.addedName = state.parsedData.item_names[ADDED];
out.addedQuality = qualityOf(resolveRowQuality(ADDED)).word;

// --- results-apply orphan-drop (replaces, so orphans alone yield an empty set)
applyPayloadToState({ selected_items: { neck: [ORPHAN] } });
out.payloadSelected = [...state.selectedItems.neck];

console.log(JSON.stringify(out));
