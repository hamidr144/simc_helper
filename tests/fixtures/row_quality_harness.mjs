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

// --- draft restore orphan-drop ------------------------------------------------
state.selectedItems = { neck: new Set() };
state.addedItems = new Map();
applyDraftToState({
  selectedItems: { neck: [KNOWN, ORPHAN] },
  addedItems: [[KNOWN, 'neck'], [ORPHAN, 'neck']],
});
out.draftSelected = [...state.selectedItems.neck];
out.draftAdded = [...state.addedItems.keys()];

// --- results-apply orphan-drop (replaces, so orphans alone yield an empty set)
applyPayloadToState({ selected_items: { neck: [ORPHAN] } });
out.payloadSelected = [...state.selectedItems.neck];

console.log(JSON.stringify(out));
