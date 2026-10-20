// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/realms)

import { armoryRealm } from './armory.js';
import { apiFetch } from '../core/api.js';

// "region/slug" -> { region, slug, name }.  Realms like Kel'thuzad exist in
// BOTH regions with different ids, so the key carries the region and entries
// are never deduped by name.
export const realmIndex = new Map();
export function populateRealmSelect(data) {
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
}
export async function loadRealms() {
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
loadRealms();
}

