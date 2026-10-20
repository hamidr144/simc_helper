// Hermetic harness for the realm dropdown: imports the REAL
// populateRealmSelect/loadRealms modules (js/setup/realms.js since the MGE2
// split t_94a15fe3; formerly extracted text from app.js) and runs them against
// a minimal DOM stub and a realms.json passed on argv.
// Usage: node realms_dropdown_harness.mjs <realms.json> [--fail-fetch] [--bad-shape]
// Prints one JSON result object on stdout; exits non-zero on harness bugs.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'url';

class El {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.label = '';
    this.value = '';
    this.textContent = '';
    this.title = '';
    this.disabled = true;
    this.hidden = true;
    // app boot (pages/setup self-wire) tags rail sections with dataset step ids.
    this.dataset = {};
  }
  setAttribute() {}
  appendChild(child) { this.children.push(child); return child; }
  addEventListener() {}
  removeEventListener() {}
  setAttribute() {}
  focus() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  options() { return this.children.filter((c) => c.tagName === 'option'); }
  optgroups() { return this.children.filter((c) => c.tagName === 'optgroup'); }
}

// P: permissive stub for every element the module graph touches at import.
const P = new Proxy(function () {}, {
  get: (t, p) => {
    if (p === Symbol.toPrimitive || p === 'valueOf') return () => '';
    if (typeof p === 'symbol') return undefined;
    if (p === 'then') return undefined;
    if (p === 'size' || p === 'length') return 0;
    return P;
  },
  set: () => true,
  apply: () => P,
});

const armoryRealm = new El('select');
const byId = new Map([['armory-realm', armoryRealm]]);
globalThis.window = globalThis;
globalThis.document = new Proxy({
  getElementById: (id) => {
    if (!byId.has(id)) byId.set(id, new El(id === 'armory-region' ? 'select' : 'div'));
    return byId.get(id);
  },
  createElement: (tag) => new El(tag),
  querySelector: () => P,
  querySelectorAll: () => [],
  addEventListener: () => {},
}, { get: (t, p) => (p in t ? t[p] : P) });
globalThis.location = { search: '', href: 'http://x/', assign() {} };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
globalThis.requestAnimationFrame = () => 0;
// wire() arms poll/debounce intervals; keep the harness one-shot and quiet.
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.alert = () => {};
globalThis.confirm = () => true;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
try { globalThis.navigator = { clipboard: { writeText: () => Promise.resolve() } }; }
catch { try { Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: () => Promise.resolve() } }, configurable: true }); } catch {} }

const data = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const flags = process.argv.slice(3);
globalThis.fetch = flags.includes('--bad-shape')
  ? async () => ({ ok: true, json: async () => ({ nope: true }) })
  : flags.includes('--fail-fetch')
    ? async () => { throw new Error('network down'); }
    : async () => ({ ok: true, json: async () => data });

const { populateRealmSelect, loadRealms, realmIndex } = await import(
  fileURLToPath(new URL('../../src/web/static/js/setup/realms.js', import.meta.url))
);

if (flags.includes('--fail-fetch') || flags.includes('--bad-shape')) {
  await loadRealms(); // must swallow the error, not throw
  console.log(JSON.stringify({
    degraded: true,
    disabled: armoryRealm.disabled,
    hidden: armoryRealm.hidden,
    childCount: armoryRealm.children.length,
  }));
} else {
  populateRealmSelect(data);
  const groups = armoryRealm.optgroups().map((g) => ({
    label: g.label,
    options: g.options().map((o) => ({ value: o.value, text: o.textContent, title: o.title })),
  }));
  console.log(JSON.stringify({
    groups,
    disabled: armoryRealm.disabled,
    hidden: armoryRealm.hidden,
    indexKeys: [...realmIndex.keys()],
    indexSample: Object.fromEntries(
      ['eu/kelthuzad', 'us/kelthuzad', 'eu/pozzo-delleternit\u00e0', 'us/area-52']
        .map((k) => [k, realmIndex.get(k) || null]),
    ),
  }));
}
