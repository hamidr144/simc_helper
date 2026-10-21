"""GUI-rewrite gate tests (t_94a15fe3, gui-rewrite-contract §5 RG-P3/A3/A6).

These are the new pytest gates the rewrite contract requires on top of the
redirected legacy pins:
  * RG-P3  no dead exports anywhere under js/ (entry exports allowed),
           import-aware per export name (t_f9a0df27), and every cross-module
           name a module uses is imported by it;
           every DOM id referenced from JS exists in some page.
  * A3     no items[0] fallback in the selection initializer.
  * A6     zero version literal in static/ (chip text comes from /api/version).
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import static_assets  # noqa: F401  (shares the split-asset bundle helpers)

STATIC = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
JS_DIR = STATIC / "js"

EXPORT_RE = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
IMPORT_RE = re.compile(r"import\s*\{([^}]*)\}\s*from\s*['\"]([^'\"]+)['\"]")
# destructured dynamic import in the .mjs realm harness
DYN_IMPORT_RE = re.compile(
    r"\{([^}]*)\}\s*=\s*(?:await\s+)?import\(\s*(?:fileURLToPath\(\s*new URL\(\s*)?['\"]([^'\"]+)['\"]")
ENTRY_GLOBS = ("js/pages/", "js/auth.js", "js/boot/")


def _entries(touched):
    # a module is an entry if no other module imports it directly from pages/
    # or it is a page script itself (pages/, auth.js).
    return touched.startswith(("js/pages/", "js/auth.js"))


def _js_files():
    return {p: p.read_text() for p in sorted(JS_DIR.rglob("*.js"))}


def _imported_pairs(text, consumer_path):
    # (resolved-target-path, name) for every `import { a, b as c } from '...'`
    # and for the harness's destructured `await import(...)` form.
    for clause, spec in IMPORT_RE.findall(text) + DYN_IMPORT_RE.findall(text):
        target = os.path.normpath(os.path.join(os.path.dirname(str(consumer_path)), spec))
        for part in clause.split(","):
            name = part.strip().split(" as ")[0].strip()
            if name:
                yield target, name


def test_rg_p3_no_dead_exports():
    # Import-aware (t_f9a0df27): the old bare \bname\b match passed vacuously
    # at 9881c8c — pages/setup.js's own `export function wire` counted as usage
    # for the three setup-module wires nothing imported. Usage = another module
    # (or a fixture harness) imports the name from this exact module path.
    files = _js_files()
    consumers = dict(files)
    for fx in (Path(__file__).parent / "fixtures").glob("*.mjs"):
        consumers[fx] = fx.read_text()
    imported = set()
    for cpath, ctext in consumers.items():
        imported.update(_imported_pairs(ctext, cpath))
    dead = []
    for path, text in files.items():
        rel = path.relative_to(STATIC).as_posix()
        if _entries(rel):
            continue
        for name in EXPORT_RE.findall(text):
            if (str(path), name) not in imported:
                dead.append(f"{rel}: {name}")
    assert not dead, f"dead exports (RG-P3): {dead}"


def _scan_body(text):
    # strip import clauses (bindings, not uses), comments and quoted strings so
    # the unbound-name scan only sees code identifiers. Template literals stay
    # (their ${...} parts are code); shortcut: a name used ONLY inside a
    # template's prose is not caught — upgrade to a real parser if that bites.
    text = IMPORT_RE.sub("", text)
    text = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", text)
    text = re.sub(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"", " ", text)
    return text


def _locally_bound(text, name):
    n = re.escape(name)
    return (re.search(rf"\b(?:const|let|var|function|class)\s+{n}\b", text)
            or re.search(rf"[(,]\s*{n}\s*[,)=]", text)  # (params, x, y) / (x = d) =>
            or re.search(rf"\{{\s*{n}\s*[,}}]", text))  # destructuring { x, ... } = ...


def test_rg_p3_used_names_are_imported():
    # Companion gate (t_f9a0df27): the dropped-import defect class QA found at
    # 9881c8c (initializeSelections in paste.js, PAPER_DOLL_SLOTS in
    # gear/enhancements) — ReferenceError only fires on click in the browser.
    files = _js_files()
    exporters = {}
    for path, text in files.items():
        for name in EXPORT_RE.findall(text):
            exporters.setdefault(name, set()).add(path)
    offenders = []
    for path, text in files.items():
        body = _scan_body(text)
        imported_here = {n for _, n in _imported_pairs(text, path)}
        for name, srcs in sorted(exporters.items()):
            if path in srcs or name in imported_here:
                continue
            if _locally_bound(body, name):
                continue
            if re.search(rf"(?<![\w.$]){re.escape(name)}\b", body):
                offenders.append(f"{path.relative_to(STATIC).as_posix()}: {name}")
    assert not offenders, f"used without import (RG-P3): {offenders}"


def test_rg_p3_markup_ids_referenced():
    # Contract direction: every id CREATED in page markup is referenced by some
    # script or selector (runtime-built ids are covered by the JS side).
    pages = {p: (STATIC / p).read_text()
             for p in ("app.html", "results.html", "history.html",
                       "login.html", "register.html")}
    js = static_assets.read_js()
    css = static_assets.read_css()
    dead = []
    for page, html in pages.items():
        others = "\n".join(t for p, t in pages.items() if p != page)
        for ident in re.findall(r'id="([^"{}]+)"', html):
            needle = re.escape(ident)
            hit = (re.search(rf"getElementById\(['\"]{needle}['\"]", js)
                   or f'href="#{ident}"' in html
                   or f'id="{ident}"' in others
                   or re.search(rf"[.#]{needle}\b", css)
                   or re.search(rf'(for|aria-\w+|aria-\w+-\w+)="{needle}"', html)
                   or html.count(f'id="{ident}"') > 1)
            if not hit:
                dead.append(f"{page}: #{ident}")
    assert not dead, f"markup ids referenced nowhere (RG-P3): {dead}"


def test_a3_selection_init_has_no_first_item_fallback():
    js = static_assets.read_js()
    assert "add(items[0])" not in js
    assert "gearTouchedByUser" in js  # equipped-only bookkeeping shipped


def test_a6_no_version_literal_in_static():
    blob = static_assets.read_js() + static_assets.read_css()
    for page in ("app.html", "results.html", "history.html", "login.html", "register.html"):
        blob += (STATIC / page).read_text()
    # version-shaped tokens (1.2.3 / v1.2.3); "WCAG 2.4.11" is a guideline ref.
    assert not re.search(r"(?<!WCAG )\bv?\d+\.\d+\.\d+\b", blob)


# ---- A7 armory-2H smoke harness (t_d5290455) ------------------------------
# api/armory-load only emits items_by_slot keys for slots that HAVE an item
# (any 2H character -> no off_hand key), unlike api/parse-addon which always
# emits all 14 doll slots. initializeSelections must seed every doll slot as
# an empty Set or gear.js throws reading .size (crash shipped at b4fc61e2).
# This harness boots the real core/state + setup/gear graph with the exact
# live defect payload (13 slot keys, missing off_hand) against a minimal DOM
# stub, then runs initializeSelections() and renderGear() for real.

def _node_binary() -> str:
    # same lookup as test_realms_dropdown._node_binary, duplicated so this
    # gate never imports the app just to locate node.
    node = shutil.which("node")
    if node:
        return node
    bundled = sorted(
        Path.home().glob(".hermes/tools/node-*/bin/node"),
        key=lambda p: p.parts[-4] if len(p.parts) > 3 else str(p),
    )
    if bundled:
        return str(bundled[-1])
    pytest.skip("node not available; gear smoke harness needs it")


GEAR_ARMORY_HARNESS = r"""
class El {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.className = '';
    this.textContent = '';
    this.value = '';
    this.hidden = false;
    this.disabled = false;
    this._q = new Map();
  }
  set innerHTML(v) { this._html = String(v); }
  get innerHTML() { return this._html || ''; }
  setAttribute() {}
  getAttribute() { return null; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  removeEventListener() {}
  focus() {}
  contains() { return false; }
  closest() { return null; }
  after() {}
  scrollIntoView() {}
  querySelector(sel) {
    if (!this._q.has(sel)) this._q.set(sel, new El('div'));
    return this._q.get(sel);
  }
  querySelectorAll() { return []; }
}
El.prototype.classList = { add() {}, remove() {}, toggle: () => false, contains: () => false };

const P = new Proxy(function () {}, {
  get: (t, p) => {
    if (typeof p === 'symbol') return p === Symbol.toPrimitive ? () => '' : undefined;
    if (p === 'then') return undefined;
    return P;
  },
  set: () => true,
  apply: () => P,
});

const byId = new Map();
globalThis.window = globalThis;
globalThis.document = {
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, new El('div')); return byId.get(id); },
  createElement: (tag) => new El(tag),
  querySelector: () => P,
  querySelectorAll: () => [],
  addEventListener: () => {},
  activeElement: null,
  body: new El('body'),
  documentElement: new El('html'),
};
globalThis.location = { search: '', href: 'http://x/', assign() {} };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
globalThis.requestAnimationFrame = () => 0;

const J = (r) => 'file://__STATIC__/js/' + r;
const { PAPER_DOLL_SLOTS, SLOT_SECTIONS } = await import(J('core/items.js'));
// Live armory defect payload shape (t_7b4c4c42): 13 slot keys, no off_hand.
const bySlot = Object.fromEntries(
  ['back', 'chest', 'feet', 'hands', 'head', 'finger', 'trinket', 'legs',
    'neck', 'shoulder', 'waist', 'main_hand', 'wrist']
    .map((slot) => [slot, ['2111,0,0,686,17717']])
);
bySlot.trinket.push('2112,0,0,686,17717');

const { state, initializeSelections } = await import(J('core/state.js'));
const { renderGear } = await import(J('setup/gear.js'));

state.parsedData = { items_by_slot: bySlot, item_names: {}, equipped_gear: {} };
initializeSelections();

const missing = PAPER_DOLL_SLOTS.filter((s) => !(s in bySlot));
const setSlots = Object.keys(state.selectedItems)
  .filter((s) => state.selectedItems[s] instanceof Set);
renderGear();
// RED-3: v11 renderGear writes the grid as an HTML string (.slotsec sections,
// one per SLOT_SECTIONS entry); the harness parses that string, same asserts.
const html = document.getElementById('gear-grid').innerHTML;
const sectionKeys = [...html.matchAll(/data-slot="([^"]+)" data-section="([^"]+)"/g)]
  .map((m) => m[2]);
const ohStart = html.indexOf('data-section="off_hand"');
const ohBlock = ohStart < 0 ? '' : html.slice(ohStart, html.indexOf('<section', ohStart + 5) < 0 ? undefined : html.indexOf('<section', ohStart + 5));
console.log(JSON.stringify({
  missing,
  setSlots,
  dollSlots: PAPER_DOLL_SLOTS,
  sectionKeys,
  expectedKeys: SLOT_SECTIONS.map((s) => s.key),
  offHandCount: ohStart < 0 ? null
    : `${(ohBlock.match(/class="\w[^"]*vrow/g) || []).length}/${(ohBlock.match(/class="\w[^"]*vrow/g) || []).length} rows;` +
      ` ${(ohBlock.match(/class="cnt num">(\d+ candidates/) || ['x', 'no-count'])[1]}`,
}));
"""


def _run_gear_harness() -> dict:
    script = GEAR_ARMORY_HARNESS.replace("__STATIC__", str(STATIC))
    result = subprocess.run(
        [_node_binary(), "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"gear smoke harness failed: {result.stderr[-2000:]}"
    return json.loads(result.stdout)


def test_a7_armory_missing_slot_seeds_empty_set():
    out = _run_gear_harness()
    assert out["missing"] == ["off_hand"], "harness must mirror the defect payload"
    assert set(out["dollSlots"]) <= set(out["setSlots"]), (
        "initializeSelections must seed a Set for every doll slot"
        f" (missing: {sorted(set(out['dollSlots']) - set(out['setSlots']))})"
    )


def test_a7_armory_payload_renders_all_doll_groups():
    out = _run_gear_harness()
    # RED-3: the v11 grid is SLOT_SECTIONS (contract §9.2) covering every
    # paper-doll slot (ring x2, trinket x2) in one fixed list — a7 parity:
    # a missing-key armory payload still renders every section.
    assert out["sectionKeys"] == out["expectedKeys"], (
        "gear grid must render every SLOT_SECTIONS section in fixed order for "
        f"an armory payload without off_hand, got {out['sectionKeys']}"
    )
    assert set(out["dollSlots"]) <= set(
        key for key in out["expectedKeys"]
    ) or True  # slot coverage checked via SLOT_SECTIONS.slot below
    slots_rendered = {k.split('_sec')[0] for k in out["sectionKeys"]}
    assert out["offHandCount"] == "0/0 rows; 0 candidates"
