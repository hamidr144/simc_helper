// Regression (t_65bd1b07, leader ruling vs t_e906dc02 ruling 4): draft.addedItems
// keys are AUTHORITATIVE at restore — an 'id=<n>' added-by-ID key never exists in
// a fresh export parse, so the knownCandidate orphan-guard used to drop every
// added item at restore and persistDraft then overwrote the draft (t_26c5ddef
// silent work loss; QA probe t_43477503: addedItems.size 0 -> 0). Real modules
// via node (fold_chips_harness.mjs pattern): apply a synthetic draft with 2
// added items onto a fresh parse, then persistDraft() and re-apply the
// persisted draft onto a SECOND fresh parse (reload + re-paste) — the added
// items, their names and their PR #47 item_qualities entries must survive both
// hops unchanged. Usage: node draft_added_restore_harness.mjs — prints JSON.
import { state } from '../../src/web/static/js/core/state.js';
import { applyDraftToState, persistDraft } from '../../src/web/static/js/setup/draft.js';

// persistDraft environment: localStorage + the fight-style/compare-mode
// selects it reads (absent -> '' in the real code path too).
const store = new Map();
globalThis.localStorage = {
  get length() { return store.size; },
  key: (i) => [...store.keys()][i] ?? null,
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => void store.set(k, String(v)),
  removeItem: (k) => void store.delete(k),
};
globalThis.document = { getElementById: () => null };

const EQUIPPED = ',id=271463,ilevel=330';   // shoulder row the export always carries
const ADDED_A = 'id=271472';                // the QA re-add-by-ID row
const ADDED_B = 'id=271444';
const NAME_A = 'Blessed Batplate Spaulders (337)';
const NAME_B = 'Stonearrow Pauldrons (324)';

// What the session had saved before the reload (QA card's draft shape).
const draft = {
  savedAt: Math.floor(Date.now() / 1000),
  parsedData: {
    char_name: 'Harness',
    item_names: { [ADDED_A]: NAME_A, [ADDED_B]: NAME_B },
    item_qualities: { [ADDED_A]: 4, [ADDED_B]: 3 },  // PR #47 committed shape
  },
  selectedItems: { shoulder: [ADDED_A, ADDED_B] },
  addedItems: [[ADDED_A, 'shoulder'], [ADDED_B, 'shoulder']],
};

function freshParse() {  // what re-pasting the same export produces
  state.parsedData = {
    char_name: 'Harness',
    items_by_slot: { shoulder: [EQUIPPED] },
    item_names: { [EQUIPPED]: 'Battered Batplate Spaulders (330)' },
    equipped_gear: { shoulder: [EQUIPPED] },
  };
  state.selectedItems = {};
  state.addedItems = new Map();
}

freshParse();
applyDraftToState(draft);
const restored = {
  added: [...state.addedItems.keys()],
  candidates: state.parsedData.items_by_slot.shoulder,
  selected: [...(state.selectedItems.shoulder || [])],
};

// persistDraft is the real function: 800 ms debounce, localStorage stub.
persistDraft();
await new Promise((resolve) => setTimeout(resolve, 900));
const persisted = JSON.parse(localStorage.getItem('simc-draft-v1:Harness'));

// Reload + re-paste, applied to the draft that just survived persistence.
freshParse();
applyDraftToState(persisted);
const roundTrip = {
  added: [...state.addedItems.keys()],
  candidates: state.parsedData.items_by_slot.shoulder,
  selected: [...(state.selectedItems.shoulder || [])],
  names: [state.parsedData.item_names[ADDED_A], state.parsedData.item_names[ADDED_B]],
  qualities: [state.parsedData.item_qualities[ADDED_A], state.parsedData.item_qualities[ADDED_B]],
};

console.log(JSON.stringify({
  restored,
  persistedAdded: persisted.addedItems,
  persistedCandidates: persisted.parsedData.items_by_slot.shoulder,
  roundTrip,
}));
