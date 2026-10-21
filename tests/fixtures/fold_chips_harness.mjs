// Hermetic harness for the REAL foldChips (js/core/ui.js) on a minimal DOM
// stub. RED-S5F regression (t_45ab76c5, RED-S5 FAIL 2): the fold budget counts
// every row whatever its selection state, so clicking a visible row never
// reveals another one — visible set and +N count must be identical before and
// after selecting (contract §12 gate 4, "no layout jitter on selection
// change"). Selected/excluded rows past the fold stay visible (doc 4.2
// parity). Usage: node fold_chips_harness.mjs — prints one JSON object.
import { foldChips } from '../../src/web/static/js/core/ui.js';

class El {
  constructor(tag, classes = []) {
    this.tagName = tag;
    this.hidden = false;
    this.children = [];
    this._classes = new Set(classes);
    this._handlers = {};
    this._text = '';
  }
  get classList() {
    const set = this._classes;
    return { contains: (name) => set.has(name) };
  }
  set className(value) { this._classes = new Set(String(value).split(/\s+/).filter(Boolean)); }
  set textContent(value) { this._text = String(value); }
  get textContent() { return this._text; }
  setAttribute() {}
  addEventListener(name, cb) { (this._handlers[name] ||= []).push(cb); }
  appendChild(child) { this.children.push(child); return child; }
  remove() {}
  click() { (this._handlers.click || []).forEach((cb) => cb()); }
}
globalThis.document = { createElement: (tag) => new El(tag) };

// rows: array of extra class names ('' | 'sel' | 'ex') per candidate row.
function run(rows, max = 3) {
  const kids = rows.map((cls) => new El('button', cls ? [cls] : []));
  const host = new El('div');
  kids.forEach((row) => host.appendChild(row));
  foldChips(host, max);
  const chip = host.children.find((c) => c._classes.has('fold')) || null;
  return {
    vis: kids.map((row, i) => (!row.hidden ? i : -1)).filter((i) => i >= 0),
    chip: chip ? chip.textContent : null,
    kids,
  };
}

const out = {};
const plain6 = ['', '', '', '', '', ''];
const view = (r) => ({ vis: r.vis, chip: r.chip });

out.baseline6 = view(run(plain6));
out.sel1of6 = view(run(['', 'sel', '', '', '', '']));     // was +46px jitter: 4 rows revealed
out.baseline4 = view(run(['', '', '', '']));
out.sel1of4 = view(run(['', 'sel', '', '']));             // RED-S5 repro: was 4 rows + no chip (+15px)
out.selLastVisible4 = view(run(['', '', 'sel', '']));
out.selBeyondFold = view(run(['', '', '', '', 'sel']));   // doc 4.2: selected stays visible
out.exBeyondFold = view(run(['', '', '', '', '', 'ex']));
out.allBeyondFoldSelected = view(run(['', '', '', 'sel'])); // nothing left to fold → no chip

const expanded = (() => {
  const kids = plain6.map((cls) => new El('button', cls ? [cls] : []));
  const host = new El('div');
  kids.forEach((row) => host.appendChild(row));
  foldChips(host, 3);
  const c = host.children.find((el) => el._classes.has('fold'));
  c.click();  // +N expand: every folded row must come back (old behaviour kept)
  return kids.map((row, i) => (!row.hidden ? i : -1)).filter((i) => i >= 0);
})();
out.expandRevealsAll = expanded;

console.log(JSON.stringify(out));
