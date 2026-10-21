// t_1321a4a7 (A4/t_4149ba6b + t_77ea4b76 family): added-by-id grade
// resolution — a bare-id key gets its {track, rank, item_level} from a same-id
// sibling in the slot (hydrated grade or ladder inference on its bonus string)
// or from the preview's "Upgrade Level" line, and the seeded grade drives the
// rank/VF row walk. Real modules under node (offline fallback season: myth top
// 289, Ascendant Voidforged result 298, trinket eligible).
// Usage: node added_grade_harness.mjs — prints one JSON object.
import { state } from '../../src/web/static/js/core/state.js';
import { ranksForItem, resolveAddedGrade } from '../../src/web/static/js/core/items.js';

const out = {};
const EQ = 'id=170001,bonus_id=6652/13987,ilevel=289';   // myth 6/6 shape
const ADDED = 'id=170001';
state.parsedData = {
  items_by_slot: { trinket: [EQ, ADDED] },
  item_names: { [EQ]: 'Mock Trinket (289)', [ADDED]: 'Mock Trinket (300)' },
  equipped_gear: {},
};
state.addedItems = new Map([[ADDED, 'trinket']]);
state.selectedItems = { trinket: new Set([ADDED]) };
state.gearUpgrades = { trinket: { [EQ]: { track: 'myth', rank: 6, item_level: 289 } } };

// Pre-fix: resolveAddedGrade did not exist (import error -> red harness) and
// the bare key rendered ZERO rank/VF rows (grade null, off-ladder label).
out.reuse = resolveAddedGrade('trinket', 170001, { ilvl: 300 });
out.rowsBeforeSeed = ranksForItem('trinket', ADDED).filter(v => v.rank !== null).length;
state.gearUpgrades.trinket[ADDED] = out.reuse;
out.vfRow = ranksForItem('trinket', ADDED)
  .filter(v => v.rank !== null && v.voidforged).map(v => `${v.rank}:${v.ilvl}`);

// Preview "Upgrade Level" seeds when no same-id grade exists; an item with
// neither source resolves to nothing (base row only, PR #47's Current row).
out.previewOnly = resolveAddedGrade('trinket', 170002, { ilvl: 285, upgrade_level: 'Myth 5/6' });
out.nothing = resolveAddedGrade('trinket', 170003, { ilvl: 300 });

console.log(JSON.stringify(out));
