/** SimC Helper five-step workflow. */

/* Upgrade ladders are fetched from /api/upgrade-data (per-season data file);
   this fallback only applies if the endpoint is unreachable. */
const FALLBACK_SEASON = {
  id: 'midnight-s1-offline',
  name: 'Midnight Season 1 (offline data)',
  crest_name: 'Dawncrest',
  cost_per_rank: 20,
  tracks: {
    adventurer: [220, 224, 227, 230, 233, 237],
    veteran: [233, 237, 240, 243, 246, 250],
    champion: [246, 250, 253, 256, 259, 263],
    hero: [259, 263, 266, 269, 272, 276],
    myth: [272, 276, 279, 282, 285, 289]
  },
  elevated_ilvls: [],
  ascension: {
    name: 'Ascendant Voidforged',
    cost: 5,
    bonus_ids: ['13653', '13654'],
    eligible_slots: ['main_hand', 'off_hand', 'trinket', 'trinket1', 'trinket2'],
    results: { hero: 285, myth: 298 },
    legacy_bonus_ilvl: 9,
    legacy_final_ilvls: [285, 298]
  }
};
let upgradeData = null;
let activeSeason = null;
function season() { return activeSeason || FALLBACK_SEASON; }
function seasonTracks() { return season().tracks || {}; }
function seasonAscension() { return season().ascension || {}; }
function isElevatedLevel(level) {
  return level != null && (season().elevated_ilvls || []).includes(Number(level));
}
async function loadUpgradeData() {
  try {
    const response = await fetch('/api/upgrade-data');
    if (!response.ok) return;
    upgradeData = await response.json();
    activeSeason = (upgradeData.seasons || [])
      .find(item => item.id === upgradeData.active_season) || null;
    renderSeasonChip();
  } catch (error) {
    console.warn('Upgrade data endpoint unavailable, using offline ladder', error);
  }
}
function renderSeasonChip() {
  const chip = document.getElementById('season-chip');
  if (chip) chip.textContent = season().name || '';
}
function detectSeasonFromExport(data) {
  // Mirror the server rule: live-first, older seasons for archived exports.
  if (!upgradeData) return;
  const levels = [];
  for (const items of Object.values(data.items_by_slot || {})) {
    for (const item of items) {
      const level = Number(parseItemParams(item).ilevel) ||
        itemLevelFromLabel((data.item_names || {})[item]);
      if (level) levels.push(level);
    }
  }
  if (!levels.length) return;
  const top = Math.max(...levels);
  const seasons = upgradeData.seasons || [];
  const inBand = s => s.ilvl_band && top >= s.ilvl_band[0] && top <= s.ilvl_band[1];
  const active = seasons.find(s => s.id === upgradeData.active_season);
  if (active && inBand(active)) { activeSeason = active; return; }
  const matches = seasons.filter(inBand);
  if (matches.length) activeSeason = matches.reduce((a, b) => b.ilvl_band[1] > a.ilvl_band[1] ? b : a);
}

/* WoW class colors — identity accent only; the accent system stays --accent-color. */
const CLASS_COLORS = {
  deathknight: '#c41f3b', demonhunter: '#a335ee', druid: '#ff7c0a',
  evoker: '#33937f', hunter: '#aad372', mage: '#3fc7eb',
  monk: '#00ff98', paladin: '#f48cba', priest: '#ffffff',
  rogue: '#fff468', shaman: '#2459ff', warlock: '#8788ee',
  warrior: '#c69b66'
};

const RAIL_STEPS = [
  { id: 'step-export', num: 1, label: 'Export' },
  { id: 'step-gear', num: 2, label: 'Gear' },
  { id: 'step-enhance', num: 3, label: 'Enhancements' },
  { id: 'step-run', num: 4, label: 'Run' }
];

let parsedData = null;
let appConfig = { enchantments: {}, gems: { meta: [], standard: [] } };
let selectedItems = {};
let selectedEnchants = {};
let selectedGems = new Set();
let equippedEnchants = {};
let equippedGems = new Set();
let gearUpgrades = {};
let voidforgedItems = {};
let extraSockets = {};
let generatedInput = null;
let generationTimer = null;
let railObserver = null;
let runTimer = null;
let runStartedAt = null;
let logLineCount = 0;
let simulationDone = false;

const addonInput = document.getElementById('addon-input');
const btnParseAddon = document.getElementById('btn-parse-addon');
const workflowContainer = document.getElementById('gear-workspace-container');

/* ---------- Rail stepper ---------- */

const RAIL_TARGETS = {
  'step-export': 'addon-input-card',
  'step-gear': 'baseline-gear-panel',
  'step-enhance': 'step-enhance',
  'step-run': 'step-run'
};

function renderRail() {
  const nav = document.getElementById('rail-steps');
  if (!nav || nav.childElementCount) return;
  nav.innerHTML = RAIL_STEPS.map(step =>
    `<button type="button" class="rail-step" data-step="${step.id}">` +
    `<span class="rail-step-num">${step.num}</span><span class="rail-step-label">${step.label}</span></button>`
  ).join('');
  nav.querySelectorAll('.rail-step').forEach(button =>
    button.addEventListener('click', () => {
      document.getElementById(RAIL_TARGETS[button.dataset.step] || button.dataset.step)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  updateRailState();
}

function updateRailState() {
  const stepDone = {
    'step-export': Boolean(parsedData),
    'step-gear': Boolean(generatedInput),
    'step-enhance': simulationDone,
    'step-run': simulationDone
  };
  document.querySelectorAll('.rail-step').forEach(button => {
    const id = button.dataset.step;
    const step = RAIL_STEPS.find(item => item.id === id);
    const done = Boolean(stepDone[id]);
    button.classList.toggle('is-done', done);
    button.disabled = !(id === 'step-export' || parsedData);
    button.querySelector('.rail-step-num').textContent = done ? '✓' : step.num;
  });
}

function observeWorkflowSteps() {
  if (railObserver) railObserver.disconnect();
  railObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    document.querySelectorAll('.rail-step').forEach(button =>
      button.classList.toggle('is-active', button.dataset.step === visible.target.dataset.stepId));
  }, { rootMargin: '-15% 0px -55% 0px', threshold: [0.05, 0.25] });
  const sections = {
    'step-export': document.getElementById('addon-input-card'),
    'step-gear': document.getElementById('baseline-gear-panel'),
    'step-enhance': document.getElementById('step-enhance'),
    'step-run': document.getElementById('step-run')
  };
  for (const [id, element] of Object.entries(sections)) {
    if (element) { element.dataset.stepId = id; railObserver.observe(element); }
  }
}

/* ---------- Worker status ---------- */

async function pollWorkerStatus() {
  const chip = document.getElementById('worker-status');
  const text = document.getElementById('worker-status-text');
  if (!chip || !text) return;
  try {
    const response = await fetch('/api/state');
    const data = await response.json();
    const workers = data.workers || [];
    const idle = workers.filter(worker => /idle/i.test(worker.status || '')).length;
    if (!workers.length) {
      chip.className = 'status-chip status-err';
      text.textContent = 'No workers';
      chip.title = 'No SimC worker is connected to the master.';
    } else {
      chip.className = 'status-chip status-ok';
      text.textContent = `${idle}/${workers.length} workers idle`;
      chip.title = workers.map(worker => `${worker.name}: ${worker.status}`).join('\n');
    }
  } catch {
    chip.className = 'status-chip status-err';
    text.textContent = 'Server offline';
    chip.title = 'The master server could not be reached.';
  }
}

/* ---------- Character chip ---------- */

function renderCharChip() {
  const chip = document.getElementById('char-chip');
  if (!chip || !parsedData) return;
  const cls = String(parsedData.char_class || '').toLowerCase();
  const color = CLASS_COLORS[cls] || 'var(--accent-color)';
  const slots = Object.keys(parsedData.items_by_slot || {}).length;
  const candidates = Object.values(parsedData.items_by_slot || {})
    .reduce((total, items) => total + items.length, 0);
  chip.hidden = false;
  chip.innerHTML = `<span class="char-class-dot" style="background:${color};color:${color}"></span>` +
    `<b>${escapeHtml(parsedData.char_name)}</b> ${escapeHtml(cls ? cls[0].toUpperCase() + cls.slice(1) : 'Unknown class')}` +
    ` · ${candidates} candidate items in ${slots} slots`;
}

/* ---------- Paste flow ---------- */

function updateCharCount() {
  const counter = document.getElementById('addon-char-count');
  const length = addonInput.value.trim().length;
  if (counter) counter.textContent = length
    ? `${length.toLocaleString()} characters pasted`
    : 'Nothing pasted yet';
  btnParseAddon.disabled = !length;
}

function showParseError(message) {
  const panel = document.getElementById('parse-error');
  if (!panel) return;
  panel.hidden = false;
  panel.textContent = message;
}

function clearParseError() {
  const panel = document.getElementById('parse-error');
  if (panel) { panel.hidden = true; panel.textContent = ''; }
}

function collapsePastePanel() {
  document.getElementById('paste-guide').hidden = true;
  addonInput.hidden = true;
  btnParseAddon.hidden = true;
  document.getElementById('btn-new-export').hidden = false;
  const counter = document.getElementById('addon-char-count');
  if (counter) counter.textContent = 'Export parsed and ready below.';
}

function resetPastePanel() {
  document.getElementById('paste-guide').hidden = false;
  addonInput.hidden = false;
  addonInput.value = '';
  addonInput.focus();
  btnParseAddon.hidden = false;
  document.getElementById('btn-new-export').hidden = true;
  clearParseError();
  updateCharCount();
}

/* ---------- Run progress ---------- */

function formatElapsed(ms) {
  const secs = Math.floor(ms / 1000);
  return `${String(Math.floor(secs / 60)).padStart(2, '0')}:${String(secs % 60).padStart(2, '0')}`;
}

function startRunProgress() {
  stopRunProgress();
  simulationDone = false;
  runStartedAt = Date.now();
  logLineCount = 0;
  document.getElementById('run-progress').hidden = false;
  document.getElementById('run-progress-meta').textContent = 'Starting…';
  document.getElementById('run-elapsed').textContent = '00:00';
  runTimer = setInterval(() => {
    document.getElementById('run-elapsed').textContent = formatElapsed(Date.now() - runStartedAt);
  }, 1000);
}

function stopRunProgress() {
  if (runTimer) { clearInterval(runTimer); runTimer = null; }
}

function updateRunProgressMeta(text) {
  const meta = document.getElementById('run-progress-meta');
  if (!meta) return;
  const progress = String(text).match(/Progress:\s*(\d+)%\s*\(([^)]+)\)/);
  if (progress) {
    meta.textContent = `${progress[1]}% · ${progress[2]} profiles`;
    return;
  }
  const line = String(text).trim();
  if (line) meta.textContent = line.length > 90 ? `${line.slice(0, 90)}…` : line;
}

async function stopSimulation() {
  const status = document.getElementById('workflow-status');
  let token = window.localStorage.getItem('simc-admin-token') || '';
  const entered = window.prompt(
    'Stopping a simulation requires the master admin token (ADMIN_TOKEN):', token);
  if (entered === null) return;
  token = entered.trim();
  try {
    const response = await fetch('/api/stop-simulation', {
      method: 'POST', headers: { 'X-Admin-Token': token }
    });
    if (response.status === 403) {
      status.textContent = 'The admin token was rejected.';
      window.localStorage.removeItem('simc-admin-token');
      return;
    }
    const data = await response.json();
    window.localStorage.setItem('simc-admin-token', token);
    status.textContent = data.message || 'Stop requested.';
  } catch (error) {
    status.textContent = `Could not stop simulation: ${error.message}`;
  }
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function parseItemParams(item) {
  return Object.fromEntries(
    String(item || '').split(',').filter(part => part.includes('='))
      .map(part => {
        const index = part.indexOf('=');
        return [part.slice(0, index).trim(), part.slice(index + 1).trim()];
      })
  );
}

function createWowheadIconLink(itemId, bonusIds = '') {
  const safeId = encodeURIComponent(itemId || '0');
  const safeBonus = String(bonusIds || '').split('/').filter(value => /^\d+$/.test(value)).join(':');
  const bonusQuery = safeBonus ? `?bonus=${encodeURIComponent(safeBonus)}` : '';
  const tooltipData = safeBonus ? `bonus=${safeBonus}&iconsize=large` : 'iconsize=large';
  return `<a href="https://www.wowhead.com/item=${safeId}${bonusQuery}" class="item-icon-link wowhead-item-link" data-wowhead="${tooltipData}" data-wh-rename="false" target="_blank"><img src="/api/item-icon/${safeId}" alt="" loading="lazy" onerror="this.closest('.item-icon-link').classList.add('icon-missing')"></a>`;
}

function createEnhancementWowheadLink(enhancement, name) {
  const configuredUrl = typeof enhancement === 'object' ? enhancement.wowhead_url : '';
  const itemMatch = String(configuredUrl || '').match(/^https:\/\/(?:www\.)?wowhead\.com\/item=(\d+)/);
  const itemId = itemMatch?.[1];
  if (!itemId) return `<span>${escapeHtml(name)}</span>`;
  return `<a href="https://www.wowhead.com/item=${itemId}" class="enhancement-name-link wowhead-item-link" data-wowhead="" target="_blank">${escapeHtml(name)}</a>`;
}

function refreshWowheadLinks() {
  if (window.WH?.Tooltips?.refreshLinks) window.WH.Tooltips.refreshLinks();
}

function normalizedEquippedItems(slot) {
  if (!parsedData) return [];
  if (slot === 'finger') {
    return [parsedData.equipped_gear.finger1, parsedData.equipped_gear.finger2].filter(Boolean);
  }
  if (slot === 'trinket') {
    return [parsedData.equipped_gear.trinket1, parsedData.equipped_gear.trinket2].filter(Boolean);
  }
  return [parsedData.equipped_gear[slot]].filter(Boolean);
}

function isCraftedItem(item) {
  return item.includes('crafting_quality=') || item.includes('crafted_stats=');
}

function isVoidforgeEligibleSlot(slot) {
  const base = String(slot || '').split('_')[0];
  const slots = new Set((seasonAscension().eligible_slots || []).map(s => String(s).split('_')[0]));
  return slots.has(base);
}

function hasVoidforgeBonus(item) {
  const ids = (seasonAscension().bonus_ids || []).map(String);
  const bonuses = (parseItemParams(item).bonus_id || '').split('/');
  return bonuses.some(bonus => ids.includes(bonus));
}

function itemLevelFromLabel(label) {
  const match = String(label || '').match(/\((\d+)\)/);
  return match ? Number(match[1]) : null;
}

function inferMidnightUpgrade(slot, item, label) {
  if (isCraftedItem(item)) return null;
  let level = Number(parseItemParams(item).ilevel) || itemLevelFromLabel(label);
  if (!level) return null;
  const ascension = seasonAscension();
  const alreadyAscended = isVoidforgeEligibleSlot(slot) && hasVoidforgeBonus(item);
  if (alreadyAscended) {
    // Ascended items sit above the ladder; map back to the track's top rank.
    for (const [track, ascended] of Object.entries(ascension.results || {})) {
      if (Number(ascended) === level && seasonTracks()[track]) {
        return { track, rank: seasonTracks()[track].length, item_level: level };
      }
    }
    const legacyDelta = ascension.legacy_bonus_ilvl;
    if (legacyDelta) level -= legacyDelta;
  }
  for (const [track, levels] of Object.entries(seasonTracks())) {
    const rank = levels.indexOf(level) + 1;
    if (rank > 0) return { track, rank, item_level: level };
  }
  return null;
}

function isAlreadyVoidforgedItem(slot, item, label = '') {
  const ascendedName = String(seasonAscension().name || '').toLowerCase().replace('ascendant ', '');
  return isVoidforgeEligibleSlot(slot) && (
    hasVoidforgeBonus(item) ||
    (ascendedName && String(label).toLowerCase().includes(ascendedName))
  );
}

function initializeSelections() {
  selectedItems = {};
  selectedEnchants = {};
  selectedGems = new Set();
  equippedEnchants = {};
  equippedGems = new Set();
  gearUpgrades = {};
  voidforgedItems = {};
  extraSockets = {};
  generatedInput = null;

  for (const [slot, items] of Object.entries(parsedData.items_by_slot)) {
    const equipped = new Set(normalizedEquippedItems(slot));
    selectedItems[slot] = new Set(items.filter(item => equipped.has(item)));
    if (!selectedItems[slot].size && items.length) selectedItems[slot].add(items[0]);
    gearUpgrades[slot] = {};
    voidforgedItems[slot] = {};
    for (const item of items) {
      const inferred = inferMidnightUpgrade(slot, item, parsedData.item_names[item]);
      if (inferred) gearUpgrades[slot][item] = inferred;
      voidforgedItems[slot][item] = isAlreadyVoidforgedItem(
        slot, item, parsedData.item_names[item]
      );
    }
  }
  for (const slot of Object.keys(appConfig.enchantments || {})) {
    selectedEnchants[slot] = new Set();
    equippedEnchants[slot] = new Set();
    const configuredIds = new Set((appConfig.enchantments[slot] || []).map(enchant =>
      String(typeof enchant === 'object' ? enchant.id : enchant)
    ));
    for (const item of normalizedEquippedItems(slot)) {
      const enchantId = parseItemParams(item).enchant_id;
      if (enchantId && configuredIds.has(String(enchantId))) {
        equippedEnchants[slot].add(String(enchantId));
      }
    }
  }

  const configuredGemIds = new Set((appConfig.gems?.standard || []).map(gem =>
    String(typeof gem === 'object' ? gem.id : gem)
  ));
  for (const item of Object.values(parsedData.equipped_gear || {})) {
    for (const gemId of String(parseItemParams(item).gem_id || '').split('/')) {
      if (configuredGemIds.has(gemId)) equippedGems.add(gemId);
    }
  }
}

function selectedItemCount() {
  return Object.values(selectedItems).reduce((total, items) => total + items.size, 0);
}

function estimateCombinations() {
  let total = 1;
  for (const [slot, items] of Object.entries(selectedItems)) {
    const enchantCount = selectedEnchants[slot]?.size || 0;
    for (const item of items) {
      const equipped = normalizedEquippedItems(slot);
      const acceptsGem = item.includes('gem_id=') || extraSockets[slot];
      const gemCount = acceptsGem ? selectedGems.size : 0;
      const hasVariation = !equipped.includes(item) || enchantCount > 0 || gemCount > 0 || extraSockets[slot];
      if (hasVariation) total += Math.max(1, enchantCount) * Math.max(1, gemCount);
    }
  }
  return total;
}

function updateSummary() {
  const count = estimateCombinations();
  const countEl = document.getElementById('combo-count');
  const itemCountEl = document.getElementById('selected-item-count');
  const runButton = document.getElementById('btn-run');
  if (countEl) countEl.textContent = count.toLocaleString();
  if (itemCountEl) itemCountEl.textContent = selectedItemCount().toLocaleString();
  const comboWord = document.getElementById('combo-word');
  const itemWord = document.getElementById('item-word');
  if (comboWord) comboWord.textContent = count === 1 ? 'combination' : 'combinations';
  if (itemWord) itemWord.textContent = selectedItemCount() === 1 ? 'item' : 'items';
  if (runButton) runButton.disabled = !generatedInput;
  updateRailState();
}

function selectionChanged() {
  generatedInput = null;
  updateSummary();
  clearTimeout(generationTimer);
  if (!estimateCombinations()) return;
  const status = document.getElementById('workflow-status');
  if (status) status.textContent = 'Updating comparison…';
  generationTimer = setTimeout(() => generateInput(true), 250);
}

function renderTrackControls(slot, item) {
  if (isCraftedItem(item)) return '<span class="crafted-badge">Crafted · no grade</span>';
  const upgrade = gearUpgrades[slot]?.[item] || {};
  const currentLevel = Number(parseItemParams(item).ilevel) ||
    itemLevelFromLabel(parsedData?.item_names?.[item]);
  if (isElevatedLevel(currentLevel)) {
    return '<div class="gear-controls-container"><span class="crafted-badge">Elevated · not upgradeable</span></div>';
  }
  const trackOptions = ['none', ...Object.keys(seasonTracks())]
    .map(track => `<option value="${track}" ${upgrade.track === track ? 'selected' : ''}>${track === 'none' ? 'No grade' : track[0].toUpperCase() + track.slice(1)}</option>`)
    .join('');
  const levels = seasonTracks()[upgrade.track] || [];
  const rankOptions = levels.map((level, index) =>
    `<option value="${index + 1}" ${upgrade.rank === index + 1 ? 'selected' : ''}>Rank ${index + 1} · ${level}</option>`
  ).join('');
  return `<select class="gear-track-select" aria-label="Track">${trackOptions}</select><select class="gear-rank-select" aria-label="Rank" ${levels.length ? '' : 'disabled'}>${levels.length ? rankOptions : '<option value="">Rank</option>'}</select>`;
}

function renderGear() {
  const grid = document.getElementById('gear-grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (const [slot, items] of Object.entries(parsedData.items_by_slot)) {
    const group = document.createElement('section');
    group.className = 'slot-group';
    group.innerHTML = `<div class="slot-group-header"><h3>${escapeHtml(slot.replace('_', ' '))}</h3>` +
      `<span class="slot-count"></span>` +
      `<button type="button" class="slot-toggle-all">Select none</button></div><div class="slot-items"></div>`;
    const itemGrid = group.querySelector('.slot-items');
    const slotCountEl = group.querySelector('.slot-count');
    const slotToggleAll = group.querySelector('.slot-toggle-all');
    const syncSlotHeader = () => {
      slotCountEl.textContent = `${selectedItems[slot].size}/${items.length} selected`;
      slotToggleAll.textContent = items.length && selectedItems[slot].size === items.length
        ? 'Select none' : 'Select all';
    };
    syncSlotHeader();
    slotToggleAll.addEventListener('click', () => {
      const selectAll = !(items.length && selectedItems[slot].size === items.length);
      selectedItems[slot] = new Set(selectAll ? items : []);
      itemGrid.querySelectorAll('.item-select-input').forEach(input => {
        input.checked = selectAll;
        input.closest('.gear-card')?.classList.toggle('is-selected', selectAll);
      });
      syncSlotHeader();
      selectionChanged();
    });
    for (const item of items) {
      const params = parseItemParams(item);
      const label = parsedData.item_names[item] || `${slot} ${params.id || ''}`;
      const level = itemLevelFromLabel(label) || Number(params.ilevel) || null;
      const card = document.createElement('article');
      card.className = `item-option gear-card ${selectedItems[slot].has(item) ? 'is-selected' : ''}`;
      card.innerHTML = `
        <label class="item-select-row">
          <input type="checkbox" class="item-select-input" ${selectedItems[slot].has(item) ? 'checked' : ''}>
          ${createWowheadIconLink(params.id, params.bonus_id)}
          <span class="gear-card-info"><a href="https://www.wowhead.com/item=${encodeURIComponent(params.id || '0')}${params.bonus_id ? `?bonus=${encodeURIComponent(params.bonus_id.replace(/\//g, ':'))}` : ''}" class="item-option-name gear-card-name wowhead-item-link" data-wowhead="${params.bonus_id ? `bonus=${escapeHtml(params.bonus_id.replace(/\//g, ':'))}` : ''}" target="_blank">${escapeHtml(label.replace(/\s*\(\d+\)/, ''))}</a><span class="gear-card-slot">${level ? `Item level ${level}` : 'Item level unknown'}</span></span>
        </label>
        <div class="gear-card-controls">${renderTrackControls(slot, item)}</div>
        ${isVoidforgeEligibleSlot(slot) ? `<label class="voidforge-field-container"><input type="checkbox" class="voidforge-input" ${voidforgedItems[slot][item] ? 'checked' : ''}> ${seasonAscension().name || 'Ascendant'} ×${seasonAscension().cost ?? ''}</label>` : ''}
      `;

      card.querySelector('.item-select-input').addEventListener('change', event => {
        if (event.target.checked) selectedItems[slot].add(item);
        else selectedItems[slot].delete(item);
        card.classList.toggle('is-selected', event.target.checked);
        syncSlotHeader();
        selectionChanged();
      });

      const trackSelect = card.querySelector('.gear-track-select');
      const rankSelect = card.querySelector('.gear-rank-select');
      if (trackSelect) {
        trackSelect.addEventListener('change', () => {
          const track = trackSelect.value;
          if (track === 'none') {
            delete gearUpgrades[slot][item];
            rankSelect.innerHTML = '';
            rankSelect.disabled = true;
          } else {
            gearUpgrades[slot][item] = { track, rank: 1 };
            rankSelect.innerHTML = (seasonTracks()[track] || []).map((level, index) =>
              `<option value="${index + 1}">Rank ${index + 1} · ${level}</option>`
            ).join('');
            rankSelect.disabled = false;
          }
          selectionChanged();
        });
        rankSelect.addEventListener('change', () => {
          if (gearUpgrades[slot][item]) gearUpgrades[slot][item].rank = Number(rankSelect.value);
          selectionChanged();
        });
      }

      const voidforgeInput = card.querySelector('.voidforge-input');
      if (voidforgeInput) {
        voidforgeInput.addEventListener('change', event => {
          voidforgedItems[slot][item] = event.target.checked;
          event.currentTarget.closest('.voidforge-field-container')?.classList.toggle('is-active', event.target.checked);
          selectionChanged();
        });
      }
      itemGrid.appendChild(card);
    }

    if ((appConfig.gems?.standard || []).length) {
      const socketControl = document.createElement('label');
      socketControl.className = 'extra-socket-control';
      socketControl.innerHTML = `<input type="checkbox"> Add/test an extra socket on ${escapeHtml(slot)}`;
      socketControl.querySelector('input').addEventListener('change', event => {
        extraSockets[slot] = event.target.checked;
        selectionChanged();
      });
      group.appendChild(socketControl);
    }
    grid.appendChild(group);
  }
  refreshWowheadLinks();
}

function renderEnhancements() {
  const container = document.getElementById('enhancement-options');
  container.innerHTML = '';
  for (const [slot, enchants] of Object.entries(appConfig.enchantments || {})) {
    if (!enchants.length || !parsedData.items_by_slot[slot]) continue;
    const group = document.createElement('fieldset');
    group.className = 'enhancement-group';
    group.innerHTML = `<legend>${escapeHtml(slot.replace('_', ' '))} enchants</legend>`;
    for (const enchant of enchants) {
      const id = String(typeof enchant === 'object' ? enchant.id : enchant);
      const name = typeof enchant === 'object' ? enchant.name : `Enchant ${id}`;
      const label = document.createElement('label');
      label.className = 'choice-chip';
      label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(enchant, name)}`;
      const input = label.querySelector('input');
      input.checked = selectedEnchants[slot].has(id) || equippedEnchants[slot].has(id);
      input.addEventListener('change', event => {
        if (event.target.checked) selectedEnchants[slot].add(id);
        else {
          selectedEnchants[slot].delete(id);
          equippedEnchants[slot].delete(id);
        }
        selectionChanged();
      });
      group.appendChild(label);
    }
    container.appendChild(group);
  }

  const gems = (appConfig.gems?.standard || []).filter(gem =>
    !String(gem.name || '').toLowerCase().includes('heliotrope')
  );
  if (gems.length) {
    const group = document.createElement('fieldset');
    group.className = 'enhancement-group gems-group';
    group.innerHTML = '<legend>Flawless gems</legend>';
    for (const gem of gems) {
      const id = String(typeof gem === 'object' ? gem.id : gem);
      const name = typeof gem === 'object' ? gem.name : `Gem ${id}`;
      const label = document.createElement('label');
      label.className = 'choice-chip';
      label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(gem, name)}`;
      const input = label.querySelector('input');
      input.checked = selectedGems.has(id) || equippedGems.has(id);
      input.addEventListener('change', event => {
        if (event.target.checked) selectedGems.add(id);
        else {
          selectedGems.delete(id);
          equippedGems.delete(id);
        }
        selectionChanged();
      });
      group.appendChild(label);
    }
    container.appendChild(group);
  }
  refreshWowheadLinks();
}

function renderWorkflow() {
  workflowContainer.innerHTML = `
    <section class="panel-card workflow-panel full-width baseline-gear-panel" id="baseline-gear-panel"><div class="step-heading"><span>2</span><div><h2>Baseline Gear · select candidates for ${escapeHtml(parsedData.char_name)}</h2><small>Grades are inferred from the export and refined with Wowhead. Toggle whole slots with Select all/none.</small></div></div><div id="gear-grid"></div></section>
    <section class="panel-card workflow-panel full-width" id="step-enhance"><div class="step-heading"><span>3</span><div><h2>Select gems and enchantments</h2><small>Checked enhancements are included in generated variations; the ones you already wear are pre-checked as the baseline.</small></div></div><div id="enhancement-options" class="enhancement-options"></div></section>
    <section class="panel-card workflow-panel run-panel full-width" id="step-run"><div class="step-heading"><span>4</span><div><h2>Run comparison</h2><small>Combinations update automatically as you change gear. Start the run from the bar at the bottom.</small></div></div><div id="run-progress" hidden><div class="progress-card"><span class="progress-dot" aria-hidden="true"></span><span class="progress-elapsed" id="run-elapsed">00:00</span><span class="progress-meta" id="run-progress-meta">Starting…</span><button type="button" id="btn-stop" class="btn-danger">Stop run</button></div></div><div class="log-toolbar" id="log-toolbar" hidden><label class="log-follow"><input type="checkbox" id="log-follow" checked> Follow log</label><span class="char-count" id="log-lines">0 lines</span></div><pre id="simulation-log" class="simulation-log" hidden></pre></section>
  `;
  renderGear();
  renderEnhancements();
  renderCharChip();
  document.getElementById('run-bar').hidden = false;
  document.getElementById('btn-run').addEventListener('click', runSimulation);
  document.getElementById('btn-stop').addEventListener('click', stopSimulation);
  observeWorkflowSteps();
  updateSummary();
  void generateInput(true);
}

async function hydrateWowheadUpgrades(itemsBySlot) {
  try {
    const response = await fetch('/api/wowhead-upgrades', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items_by_slot: itemsBySlot })
    });
    if (!response.ok) return;
    const data = await response.json();
    for (const [slot, itemUpgrades] of Object.entries(data.gear_upgrades || {})) {
      gearUpgrades[slot] = { ...(gearUpgrades[slot] || {}), ...itemUpgrades };
    }
    renderGear();
    updateSummary();
  } catch (error) {
    console.warn('Could not refine item grades from Wowhead', error);
  }
}

function buildPayload() {
  const enchantPayload = {};
  for (const slot of Object.keys(appConfig.enchantments || {})) {
    enchantPayload[slot] = Array.from(selectedEnchants[slot] || []).map(Number);
  }
  return {
    char_class: parsedData.char_class,
    char_name: parsedData.char_name,
    base_profile: parsedData.base_profile,
    equipped_gear: parsedData.equipped_gear,
    selected_items: Object.fromEntries(Object.entries(selectedItems).map(([slot, items]) => [slot, Array.from(items)])),
    selected_enchants: enchantPayload,
    selected_gems: Array.from(selectedGems).map(Number),
    selected_meta_gems: [],
    item_levels: {},
    gear_upgrades: gearUpgrades,
    voidforged_items: voidforgedItems,
    extra_sockets: extraSockets,
    upgrade_season: season().id
  };
}

async function generateInput(quiet = false) {
  const status = document.getElementById('workflow-status');
  if (!quiet) status.textContent = 'Preparing comparison…';
  try {
    const response = await fetch('/api/generate-simc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload())
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Generation failed');
    generatedInput = data;
    document.getElementById('combo-count').textContent = data.combinations.toLocaleString();
    status.textContent = `Ready to run ${data.combinations.toLocaleString()} candidate ${data.combinations === 1 ? 'combination' : 'combinations'}.`;
  } catch (error) {
    generatedInput = null;
    status.textContent = `Could not generate input: ${error.message}`;
  } finally {
    updateSummary();
  }
}

async function runSimulation() {
  if (!generatedInput && estimateCombinations()) await generateInput();
  if (!generatedInput) return;
  const status = document.getElementById('workflow-status');
  const log = document.getElementById('simulation-log');
  status.textContent = 'Looking for an idle worker…';
  try {
    const response = await fetch(`/api/run-simulation?input_id=${encodeURIComponent(generatedInput.input_id)}`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Simulation could not start');
    status.textContent = `Simulation ${data.task_id} is running on worker ${data.worker_id}.`;
    log.hidden = false;
    log.textContent = '';
    document.getElementById('log-toolbar').hidden = false;
    startRunProgress();
    updateRailState();
    const events = new EventSource(`/api/simulation/stream/${data.task_id}?worker_id=${encodeURIComponent(data.worker_id)}`);
    events.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === 'log') {
        log.textContent += `${message.text}\n`;
        logLineCount += 1;
        updateRunProgressMeta(message.text);
      }
      if (message.type === 'log_batch') {
        log.textContent += `${message.lines.join('\n')}\n`;
        logLineCount += message.lines.length;
      }
      if (message.type === 'log' || message.type === 'log_batch') {
        const linesEl = document.getElementById('log-lines');
        if (linesEl) linesEl.textContent = `${logLineCount.toLocaleString()} lines`;
        const follow = document.getElementById('log-follow');
        if (!follow || follow.checked) log.scrollTop = log.scrollHeight;
      }
      if (message.type === 'done' || message.type === 'error') {
        stopRunProgress();
        document.getElementById('run-progress').hidden = true;
        if (message.type === 'done') simulationDone = true;
        updateRailState();
        if (message.type === 'done' && message.report_file && message.task_id) {
          const reportUrl = `/reports/${encodeURIComponent(message.task_id)}/${encodeURIComponent(message.report_file)}`;
          status.innerHTML = `${escapeHtml(message.text)} <a href="${reportUrl}" target="_blank">Open report</a>`;
          const baseline = parsedData?.char_name || '';
          window.location.assign(`/results?task_id=${encodeURIComponent(message.task_id)}&baseline=${encodeURIComponent(baseline)}`);
        } else {
          status.textContent = message.text || 'The simulation stopped unexpectedly — see the log above.';
          status.classList.add('error');
        }
        events.close();
      }
    };
    events.onerror = () => { events.close(); stopRunProgress(); };
  } catch (error) {
    status.textContent = `Could not start simulation: ${error.message}`;
  }
}

btnParseAddon.addEventListener('click', async () => {
  const text = addonInput.value.trim();
  if (!text) return;
  btnParseAddon.disabled = true;
  btnParseAddon.textContent = 'Parsing…';
  clearParseError();
  try {
    const [parseResponse, configResponse] = await Promise.all([
      fetch('/api/parse-addon', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ addon_text: text }) }),
      fetch('/api/config')
    ]);
    if (!parseResponse.ok) {
      const detail = await parseResponse.json().catch(() => ({}));
      throw new Error(detail.detail || 'The addon export could not be parsed. Make sure you copied the full text from the /simc export window.');
    }
    parsedData = await parseResponse.json();
    appConfig = configResponse.ok ? await configResponse.json() : appConfig;
    if (!upgradeData) await loadUpgradeData();
    detectSeasonFromExport(parsedData);
    renderSeasonChip();
    simulationDone = false;
    initializeSelections();
    renderRail();
    renderWorkflow();
    collapsePastePanel();
    hydrateWowheadUpgrades(parsedData.items_by_slot);
    document.getElementById('baseline-gear-panel')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    showParseError(`Could not parse the export: ${error.message}`);
  } finally {
    btnParseAddon.disabled = false;
    btnParseAddon.textContent = 'Parse character';
  }
});

document.getElementById('btn-new-export').addEventListener('click', () => {
  parsedData = null;
  generatedInput = null;
  simulationDone = false;
  workflowContainer.innerHTML = '';
  document.getElementById('run-bar').hidden = true;
  document.getElementById('char-chip').hidden = true;
  resetPastePanel();
  updateRailState();
  observeWorkflowSteps();
});

addonInput.addEventListener('input', updateCharCount);

renderRail();
observeWorkflowSteps();
updateCharCount();
pollWorkerStatus();
setInterval(pollWorkerStatus, 15000);
loadUpgradeData().then(renderSeasonChip);
renderSeasonChip();

// Report helpers retained for the result views.
function gearSummary(item) {
  return `<strong>${escapeHtml(item.slot)}:</strong> ${item.itemLink}`;
}
