// Hermetic harness for the realm dropdown: extracts the REAL
// populateRealmSelect/loadRealms functions from src/web/static/app.js and runs
// them against a minimal DOM stub and a realms.json passed on argv.
// Usage: node realms_dropdown_harness.mjs <realms.json> [--fail-fetch] [--bad-shape]
// Prints one JSON result object on stdout; exits non-zero on harness bugs.
import { readFileSync } from 'node:fs';

const appJs = readFileSync(new URL('../../src/web/static/app.js', import.meta.url), 'utf8');

function extract(name) {
  const start = appJs.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found in app.js`);
  // Keep a leading `async ` modifier if present (loadRealms is async).
  const asyncStart = appJs.lastIndexOf('async ', start);
  const from = asyncStart >= 0 && start - asyncStart <= 6 ? asyncStart : start;
  let depth = 0;
  for (let i = appJs.indexOf('{', start); i < appJs.length; i++) {
    if (appJs[i] === '{') depth++;
    else if (appJs[i] === '}') {
      depth--;
      if (depth === 0) return appJs.slice(from, i + 1);
    }
  }
  throw new Error(`unbalanced braces extracting ${name}`);
}

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
  }
  appendChild(child) { this.children.push(child); return child; }
  options() { return this.children.filter((c) => c.tagName === 'option'); }
  optgroups() { return this.children.filter((c) => c.tagName === 'optgroup'); }
}

const armoryRealm = new El('select');
const realmIndex = new Map();
const document = { createElement: (tag) => new El(tag) };

const data = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const flags = process.argv.slice(3);
const globalThisFetch = flags.includes('--bad-shape')
  ? async () => ({ ok: true, json: async () => ({ nope: true }) })
  : flags.includes('--fail-fetch')
    ? async () => { throw new Error('network down'); }
    : async () => ({ ok: true, json: async () => data });

const body = `
  ${extract('populateRealmSelect')}
  ${extract('loadRealms')}
  return { populateRealmSelect, loadRealms };
`;
const fns = new Function('document', 'armoryRealm', 'realmIndex', 'fetch', body)(
  document, armoryRealm, realmIndex, globalThisFetch,
);

if (flags.includes('--fail-fetch') || flags.includes('--bad-shape')) {
  await fns.loadRealms(); // must swallow the error, not throw
  console.log(JSON.stringify({
    degraded: true,
    disabled: armoryRealm.disabled,
    hidden: armoryRealm.hidden,
    childCount: armoryRealm.children.length,
  }));
} else {
  fns.populateRealmSelect(data);
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
