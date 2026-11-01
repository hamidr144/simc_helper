// Hermetic harness for the REAL Add-by-ID slot guard (js/setup/add-item.js),
// t_2fa2e1fe (user report: "1/2 Hand in Hand" / "Aspect of the Iron Leader"
// phantom gear rows): a preview WITHOUT a numeric Wowhead inventorySlot is
// not equipment and must be REJECTED — the old fail-open offered Add for
// set-bonus/aspect pseudo-items and the draft carried them into every load.
// The t_1699829f forward-compat fail-open stays for numeric invslots absent
// from the table. Real module import on node; prints one JSON object.
import { slotAddDecision } from '../../src/web/static/js/setup/add-item.js';

const d = (slot, preview) => {
  const out = slotAddDecision(slot, preview);
  return { offer: out.offer, showSlotName: Boolean(out.showSlotName) };
};

const out = {
  // pseudo-items: no equip slot on Wowhead (invslot 0, null, or absent)
  invslot0: d('neck', { invslot: 0, name: 'Sparkning Ore' }),
  invslotNull: d('neck', { invslot: null, name: '1/2 Hand in Hand' }),
  invslotAbsent: d('legs', { name: 'Aspect of the Iron Leader' }),
  // known equip slot that does not fit this section (pre-existing guard)
  wrongSlot: d('neck', { invslot: 3, invslot_name: 'Shoulder', name: 'Pauldrons' }),
  // t_1699829f: numeric invslot unknown to the table — future DBC id, stays open
  futureSlot: d('neck', { invslot: 18, invslot_name: 'Wand Offhand' }),
  rightSlot: d('neck', { invslot: 2, invslot_name: 'Neck', name: 'Medal' }),
};
console.log(JSON.stringify(out));
