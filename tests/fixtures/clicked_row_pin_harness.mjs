// Hermetic harness for the REAL clicked-row pin (js/setup/gear.js
// pinRow/keepPinnedRowVisible), t_2fa2e1fe: clicking a selected row past the
// 3-row fold budget toggles it off, foldChips hides it, and the row
// "disappears" — the user never sees it to re-click. The pin unhides the
// clicked row after the fold and decrements the +N chip. Real modules
// imported on node with a minimal section stub; prints one JSON object.
import { pinRow, keepPinnedRowVisible } from '../../src/web/static/js/setup/gear.js';

function row(item, { rank, vf, hidden = false } = {}) {
  const dataset = { item };
  if (rank != null) dataset.rank = String(rank);
  if (vf) dataset.vf = '1';
  return { dataset, hidden };
}
function chip(text) {
  return { textContent: text, removed: false, remove() { this.removed = true; } };
}
function section(key, rows, fold) {
  return {
    dataset: { section: key, slot: key },
    querySelectorAll: (sel) => (sel === '.rows .vrow' ? rows : []),
    querySelector: (sel) => (sel === '.rows .fold' ? fold : null),
  };
}

const out = {};

// post-fold section: rows 0-2 visible, row 3 hidden behind +1 — the row the
// user just clicked (the 4th, plain base row) must come back, chip +1 -> gone.
{
  const rows = [row('id=A'), row('id=B'), row('id=C'), row('id=D', { hidden: true })];
  const fold = chip('+1');
  pinRow('neck', 'id=D', null, false);
  keepPinnedRowVisible(section('neck', rows, fold));
  out.unhidesClicked = { hidden: rows.map(r => r.hidden), chip: fold.removed ? null : fold.textContent };
  // one-shot: a second call with the pin consumed changes nothing
  keepPinnedRowVisible(section('neck', rows, fold));
  out.oneShot = rows.map(r => r.hidden);
}

// +2 chip decrements to +1
{
  const rows = [row('id=A'), row('id=B'), row('id=C'),
    row('id=D', { hidden: true }), row('id=E', { hidden: true })];
  const fold = chip('+2');
  pinRow('neck', 'id=E', null, false);
  keepPinnedRowVisible(section('neck', rows, fold));
  out.chipDecrement = { hidden: rows.map(r => r.hidden), chip: fold.textContent };
}

// rank + voidforged identity: the pin must unhide exactly the clicked variant
{
  const rows = [row('id=A', { hidden: true }),
    row('id=A', { rank: 6, hidden: true }),
    row('id=A', { rank: 6, vf: true, hidden: true })];
  const fold = chip('+3');
  pinRow('feet', 'id=A', 6, true);
  keepPinnedRowVisible(section('feet', rows, fold));
  out.rankVfMatch = { hidden: rows.map(r => r.hidden), chip: fold.textContent };
}

// section key mismatch: untouched section keeps its fold, pin survives
{
  const rows = [row('id=D', { hidden: true })];
  const fold = chip('+1');
  pinRow('legs', 'id=D', null, false);
  keepPinnedRowVisible(section('neck', rows, fold));
  out.keyMismatch = { hidden: rows.map(r => r.hidden), chip: fold.textContent };
  // clean up the surviving pin (the legs render consumes it later)
  keepPinnedRowVisible(section('legs', rows, fold));
  out.keyMismatchConsumed = rows[0].hidden;
}

// clicked row already visible: chip untouched (no phantom decrement)
{
  const rows = [row('id=D'), row('id=E', { hidden: true })];
  const fold = chip('+1');
  pinRow('neck', 'id=D', null, false);
  keepPinnedRowVisible(section('neck', rows, fold));
  out.visibleNoop = { hidden: rows.map(r => r.hidden), chip: fold.textContent, removed: fold.removed };
}

console.log(JSON.stringify(out));
