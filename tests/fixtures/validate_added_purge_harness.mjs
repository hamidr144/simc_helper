// Hermetic harness for the REAL boot-purge (js/setup/add-item.js
// validateAddedItems), t_2fa2e1fe review round 1 (reviewer blocker): the
// server fail-softs fetch_wowhead_item_slot to (None, None) on a transient
// wowhead.com XML failure, which reaches the client as invslot null. That
// outcome must KEEP the user's real added gear — dropping it would
// permanently delete added gear from the draft on a flaky lookup
// (work-loss precedent t_26c5ddef). Drop ONLY on confirmed invslot === 0.
// Node stubs globalThis.fetch for every outcome; prints one JSON object.
import { state } from '../../src/web/static/js/core/state.js';
import { validateAddedItems } from '../../src/web/static/js/setup/add-item.js';

globalThis.window = { scrollTo: () => {}, scrollY: 0 };
// Every element lookup misses: renderGear/renderCharChip early-return,
// runbar refs are all if(el)-guarded.
globalThis.document = { getElementById: () => null, body: { prepend() {} } };

const store = new Map();
let writes = 0;
globalThis.localStorage = {
  length: 0, key: () => null,
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { writes += 1; store.set(k, v); },
  removeItem: (k) => store.delete(k),
};
// Run persistDraft's 800 ms debounce synchronously.
globalThis.setTimeout = (fn) => { fn(); return 0; };
globalThis.clearTimeout = () => {};

const okJson = (preview) => ({
  ok: true, status: 200, json: async () => ({ preview }),
});

// Three added keys: P (the purge candidate), Q (adjacent added gear that
// must survive whatever happens to P), L (added gear in another slot).
async function run(fetchImpl) {
  state.parsedData = {
    char_name: 'Testchar',
    items_by_slot: { neck: ['id=401', 'id=402'], legs: ['id=403'] },
    item_names: { 'id=401': '1/2 Hand in Hand (341)', 'id=402': 'Warstory Medal (341)', 'id=403': 'Talonshoes (334)' },
    item_qualities: {},
  };
  state.addedItems = new Map([['id=401', 'neck'], ['id=402', 'neck'], ['id=403', 'legs']]);
  state.selectedItems = {};
  state.gearUpgrades = {};
  state.voidforgedItems = {};
  state.statScores = {};
  store.clear();
  writes = 0;
  globalThis.fetch = fetchImpl;
  await validateAddedItems();
  return {
    added: [...state.addedItems.keys()],
    neck: state.parsedData.items_by_slot.neck,
    legs: state.parsedData.items_by_slot.legs,
    writes,
  };
}

const idOf = (url) => /[?&]item=(\d+)/.exec(url)[1];
const perItem = (table) => async (url) => {
  const handler = table[idOf(url)];
  return handler(url);
};

const out = {};

// 1. CONFIRMED non-equip (invslot 0) on every key: all rows drop, draft
//    re-persists exactly once with the purged state.
out.confirmedZero = await run(async () => okJson({ name: 'Sparkning Ore', invslot: 0 }));
out.confirmedZeroDraft = (() => {
  const raw = store.get('simc-draft-v1:Testchar');
  if (!raw) return null;
  const d = JSON.parse(raw);
  return { added: d.addedItems.map(([k]) => k), neck: d.parsedData.items_by_slot.neck };
})();

// 2. The reviewer's core scenario: P confirmed 0, Q's lookup FAILS
//    (invslot null — server (None, None) fail-soft). P drops, Q and L keep.
out.mixedConfirmedAndFlaky = await run(perItem({
  401: () => okJson({ name: '1/2 Hand in Hand', invslot: 0 }),
  402: () => okJson({ name: null, invslot: null, invslot_name: null }),
  403: () => okJson({ name: 'Talonshoes', invslot: 8 }),
}));

out.mixedDraft = JSON.parse(store.get('simc-draft-v1:Testchar'))
  .addedItems.map(([k]) => k); // re-persisted draft must not contain 401

// 3. All lookups fail soft (invslot null): NOTHING drops, NO persist —
//    pre-fix every added item was deleted here.
out.allNull = await run(async () => okJson({ invslot: null }));

// 4. invslot absent from the payload entirely (malformed/older shape): kept.
out.absent = await run(async () => okJson({ name: 'No slot node' }));

// 5. Network rejection: kept, no persist.
out.fetchRejects = await run(async () => { throw new TypeError('network down'); });

// 6. Server non-OK (502 "Wowhead tooltip unavailable"): kept, no persist.
out.nonOk = await run(async () => ({
  ok: false, status: 502, json: async () => ({ detail: 'Wowhead tooltip unavailable' }),
}));

// 7. Fetch OK, body not JSON (json() rejects → .catch(()=>({}) → no invslot):
//    kept, no persist.
out.badJson = await run(async () => ({
  ok: true, status: 200, json: async () => { throw new SyntaxError('not json'); },
}));

console.log(JSON.stringify(out));
