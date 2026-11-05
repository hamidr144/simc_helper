// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/realms)

import { armoryRealm } from './armory.js';
import { apiFetch } from '../core/api.js';

// "region/slug" -> { region, slug, name }.  Realms like Kel'thuzad exist in
// BOTH regions with different ids, so the key carries the region and entries
// are never deduped by name.
export const realmIndex = new Map();
const realmFilter = document.getElementById('realm-filter');
const REALM_FILTER_PLACEHOLDER = 'Filter realms…';

// t_1e22f4eb rank-3: type-to-filter over the ~500 realm options (ISO 9241-110
// suitability for the task — optimise the effort of finding a realm).  Same
// loop shape as history.js: case-insensitive substring, hide non-matches.
function filterRealmOptions() {
  const needle = realmFilter.value.trim().toLowerCase();
  let matches = 0;
  armoryRealm.querySelectorAll('optgroup').forEach(group => {
    let visible = 0;
    group.querySelectorAll('option').forEach(option => {
      const hit = !needle || option.textContent.toLowerCase().includes(needle);
      option.hidden = !hit;
      if (hit) visible += 1;
    });
    group.hidden = visible === 0;
    matches += visible;
  });
  // shortcut: the "Select realm…" option lives outside the optgroups and
  // stays visible while filtering, so clearing the selection stays one click.
  realmFilter.placeholder = needle
    ? `${matches} ${matches === 1 ? 'match' : 'matches'}`
    : REALM_FILTER_PLACEHOLDER;
}

function populateRealmSelect(data) {
  const groups = data && data.realms;
  if (!groups || !Array.isArray(groups.eu) || !Array.isArray(groups.us)) {
    throw new Error('unexpected realms.json shape');
  }
  const labels = { eu: 'EU', us: 'US' };
  for (const region of ['eu', 'us']) {
    if (!groups[region].length) continue;
    const group = document.createElement('optgroup');
    group.label = labels[region];
    for (const realm of groups[region]) {
      if (!realm || !realm.slug || !realm.name) continue;
      const option = document.createElement('option');
      option.value = `${region}/${realm.slug}`;
      option.textContent = realm.name;
      const details = [realm.type, realm.population, realm.timezone]
        .filter(Boolean).join(' · ');
      if (details) option.title = `${labels[region]} · ${details}`;
      group.appendChild(option);
      realmIndex.set(option.value, { region, slug: realm.slug, name: realm.name });
    }
    armoryRealm.appendChild(group);
  }
  armoryRealm.disabled = false;
  armoryRealm.hidden = false;
  if (realmFilter) realmFilter.hidden = false;
}
async function loadRealms() {
  if (!armoryRealm) return;
  try {
    const response = await apiFetch('static/realms.json');
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    populateRealmSelect(await response.json());
  } catch (error) {
    // Graceful degradation: the dropdown is an enhancement over the manual
    // Name-Realm typing flow.  If realms.json is missing, unreadable or
    // malformed we keep the select hidden+disabled (its initial state in the
    // markup) and stay silent to the user — typing still works exactly as
    // before.
    console.warn('Realm list unavailable:', error.message);
  }
}

export function wire() {
  if (realmFilter) realmFilter.addEventListener('input', filterRealmOptions);
  loadRealms();
}

