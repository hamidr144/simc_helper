// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/armory)

import { state } from '../core/state.js';

import { applyParsedCharacter, clearParseError, showParseError } from './paste.js';

import { realmIndex } from './realms.js';
import { apiFetch } from '../core/api.js';

const armoryInput = document.getElementById('armory-input');
const armoryRegion = document.getElementById('armory-region');
export const armoryRealm = document.getElementById('armory-realm');
const btnArmoryLoad = document.getElementById('btn-armory-load');

/* ---------- Realm dropdown (static realms.json, EU/US grouped) ---------- */
function buildArmoryPayload(value) {
  // A pasted Armory link wins over the selectors (the link carries its own
  // region/realm); plain Name-Realm / Name text uses them.
  if (/^https?:\/\//i.test(value)) return { url: value };
  const payload = { name: value, region: armoryRegion?.value || 'eu' };
  const picked = realmIndex.get(armoryRealm?.value || '');
  // A realm typed into the input ("Name-Realm", "Name, Realm") wins over the
  // dropdown pick; the dropdown only supplies the realm for a bare name.
  if (picked && !/[,-]/.test(value)) {
    payload.realm = picked.slug;
    payload.region = picked.region;
  }
  return payload;
}
export function updateArmoryState() {
  if (!armoryInput || !btnArmoryLoad) return;
  btnArmoryLoad.disabled = !armoryInput.value.trim();
}

export function wire() {
armoryRealm?.addEventListener('change', () => {
  const picked = realmIndex.get(armoryRealm.value);
  if (picked && armoryRegion) armoryRegion.value = picked.region;
});

armoryRegion?.addEventListener('change', () => {
  // A manual region switch (e.g. to KR/TW) must not leave a stale realm from
  // another region attached to the request.
  const picked = realmIndex.get(armoryRealm?.value || '');
  if (picked && picked.region !== armoryRegion.value) armoryRealm.value = '';
});

btnArmoryLoad?.addEventListener('click', async () => {
  const value = armoryInput.value.trim();
  if (!value) return;
  btnArmoryLoad.disabled = true;
  btnArmoryLoad.textContent = 'Loading…';
  clearParseError();
  try {
    const payload = buildArmoryPayload(value);
    const [armoryResponse, configResponse] = await Promise.all([
      apiFetch('api/armory-load', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }),
      apiFetch('api/config')
    ]);
    if (!armoryResponse.ok) {
      const detail = await armoryResponse.json().catch(() => ({}));
      throw new Error(detail.detail || 'The Armory could not load this character.');
    }
    state.appConfig = configResponse.ok ? await configResponse.json() : state.appConfig;
    await applyParsedCharacter(await armoryResponse.json());
  } catch (error) {
    showParseError(`Could not load from the Armory: ${error.message}`);
  } finally {
    btnArmoryLoad.textContent = 'Load from Armory';
    updateArmoryState();
  }
});

armoryInput?.addEventListener('input', updateArmoryState);
armoryInput?.addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    btnArmoryLoad?.click();
  }
});
}

