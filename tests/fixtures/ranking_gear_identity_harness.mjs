// Hermetic harness (t_7679cb1e, fold_chips/row_quality harness pattern) for
// the REAL results model: changesFromBaseline must compare the FULL parsed
// gear identity (id, enchant, gems, bonus, ilvl), not just the item id.
// Repro data: prod run 302ab428 — Hamidriel_shoulder_0 (shoulder ilvl
// 321 -> 334, same item/enchant/bonus) beat the baseline by +69 DPS yet the
// id-only diff classified it "no gear difference", quarantined it, and the
// page ranked 0 candidates. The gem case is the e4c3035c fixture's
// Hamidriel_back_12 (same id, gem-only swap).
// Usage: node ranking_gear_identity_harness.mjs — prints one JSON object.
import { changesFromBaseline } from '../../src/web/static/js/results/model.js';

const baseGear = {
  shoulder: 'id=271463,enchant_id=8001,bonus_id=6652/13440/13694/13697/12846,ilevel=321',
  neck: 'id=268265,bonus_id=6652/13668/13334/13987/12856,ilevel=341',
};
const base = { name: 'Hamidriel', dps: 18278, gear: baseGear };
const cand = (name, dps, gear) => ({ name, dps, gear });

const out = {};
// The live repro: ilvl-only swap.
out.ilvlOnly = changesFromBaseline(
  cand('Hamidriel_shoulder_0', 18347, { ...baseGear, shoulder: baseGear.shoulder.replace('ilevel=321', 'ilevel=334') }),
  base);
// Pre-fix parser shape (ilvl dropped): byte-identical gear must stay
// quarantined — this pins why the report parser keeps ilvl.
out.legacyNoIlvl = changesFromBaseline(
  cand('c', 1, { shoulder: 'id=271463,enchant_id=8001,bonus_id=6652/13440/13694/13697/12846' }),
  { name: 'b', dps: 1, gear: { shoulder: 'id=271463,enchant_id=8001,bonus_id=6652/13440/13694/13697/12846' } });
out.enchantOnly = changesFromBaseline(
  cand('c', 1, { shoulder: baseGear.shoulder.replace('enchant_id=8001', 'enchant_id=8002') }), base);
out.gemOnly = changesFromBaseline(
  cand('Hamidriel_back_12', 19872, { back: 'id=271460,gem_id=240896,bonus_id=6652/12846/13440,ilevel=321' }),
  { name: 'b', dps: 18820, gear: { back: 'id=271460,bonus_id=6652/12846/13440,ilevel=321' } });
out.bonusOnly = changesFromBaseline(
  cand('c', 1, { shoulder: baseGear.shoulder.replace('13440', '13441') }), base);
out.identical = changesFromBaseline(cand('c', 1, { ...baseGear }), base);

const fails = [];
const check = (name, cond) => { if (!cond) fails.push(name); };
check('ilvlOnly', out.ilvlOnly.length === 1 && out.ilvlOnly[0].slot === 'shoulder'
  && out.ilvlOnly[0].id === '271463' && out.ilvlOnly[0].before === '271463');
check('legacyNoIlvl', out.legacyNoIlvl.length === 0);
check('enchantOnly', out.enchantOnly.length === 1);
check('gemOnly', out.gemOnly.length === 1);
check('bonusOnly', out.bonusOnly.length === 1);
check('identical', out.identical.length === 0);
console.log(JSON.stringify({ ...out, fails }));
process.exit(fails.length ? 1 : 0);
