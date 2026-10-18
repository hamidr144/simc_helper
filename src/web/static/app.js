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
    const response = await apiFetch('api/upgrade-data');
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

/* WoW class colors — identity accent only; the accent system stays --accent-*. */
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
/* Per-slot sort mode ('ilvl' default | 'name' | 'priority'), heuristic
   stat-priority scores keyed by item string, and items the user added by
   Wowhead id (item string -> slot) for badge + removal. */
let slotSorts = {};
let statScores = {};
let addedItems = new Map();
/* Item strings Wowhead resolves to a two-handed weapon (TG3-C slot-conflict
   hint; filled by hydrateWowheadUpgrades from the upgrades lookup). */
let twoHandedItems = new Set();
const STAT_SORT_BATCH = 40;
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
    `<span class="rail-step-num num-badge">${step.num}</span><span class="rail-step-label">${step.label}</span></button>`
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

let workerPollFailures = 0;

async function pollWorkerStatus() {
  const chip = document.getElementById('worker-status');
  const text = document.getElementById('worker-status-text');
  if (!chip || !text) return;
  try {
    const response = await apiFetch('api/state');
    // 401 = logged out: the banner explains it; the chip stays unknown ("—")
    // until a successful authenticated poll (A4 — never a misleading chip).
    if (response.status === 401) return;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    workerPollFailures = 0;
    const workers = data.workers || [];
    const idle = workers.filter(worker => /idle/i.test(worker.status || '')).length;
    const titles = workers.map(worker => `${worker.name}: ${worker.status}`).join('\n');
    if (!workers.length) {
      chip.className = 'status-chip status-err';
      text.textContent = 'No idle workers';
      chip.title = 'No SimC worker is connected to the master.';
    } else if (idle === 0) {
      // Busy is a queue state, not an error (doc 4.1).
      chip.className = 'status-chip status-warn';
      text.textContent = 'All workers busy \u00b7 waiting';
      chip.title = titles;
    } else {
      chip.className = 'status-chip status-ok';
      text.textContent = `${idle}/${workers.length} workers idle`;
      chip.title = titles;
    }
  } catch {
    // Only after 3 consecutive failures is "Server offline" honest.
    workerPollFailures += 1;
    if (workerPollFailures >= 3) {
      chip.className = 'status-chip status-err';
      text.textContent = 'Server offline';
      chip.title = 'The master server could not be reached.';
    }
  }
}

/* ---------- Character chip ---------- */

function renderCharChip() {
  const chip = document.getElementById('char-chip');
  if (!chip || !parsedData) return;
  const cls = String(parsedData.char_class || '').toLowerCase();
  const color = CLASS_COLORS[cls] || 'var(--accent-text)';
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
  clearParseWarning();
}

function showParseWarning(messages) {
  const panel = document.getElementById('parse-warning');
  if (!panel) return;
  panel.hidden = false;
  panel.textContent = messages.join(' ');
}

function clearParseWarning() {
  const panel = document.getElementById('parse-warning');
  if (panel) { panel.hidden = true; panel.textContent = ''; }
}

function collapsePastePanel() {
  document.getElementById('paste-guide').hidden = true;
  addonInput.hidden = true;
  btnParseAddon.hidden = true;
  const armoryCard = document.getElementById('armory-import');
  if (armoryCard) armoryCard.hidden = true;
  document.getElementById('btn-new-export').hidden = false;
  const counter = document.getElementById('addon-char-count');
  if (counter) counter.textContent = 'Character ready below.';
}

function resetPastePanel() {
  document.getElementById('paste-guide').hidden = false;
  addonInput.hidden = false;
  addonInput.value = '';
  addonInput.focus();
  btnParseAddon.hidden = false;
  const armoryCard = document.getElementById('armory-import');
  if (armoryCard) armoryCard.hidden = false;
  document.getElementById('btn-new-export').hidden = true;
  clearParseError();
  updateCharCount();
  updateArmoryState();
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
  logLines = [];
  lastProgressPct = 0;
  lastMetaAt = 0;
  const resultSlot = document.getElementById('run-result');
  if (resultSlot) { resultSlot.hidden = true; resultSlot.innerHTML = ''; }
  document.getElementById('run-progress').hidden = false;
  setRunProgress(0, 'Starting…');
  setRunStage('');
  document.getElementById('run-elapsed').textContent = '00:00';
  runTimer = setInterval(() => {
    document.getElementById('run-elapsed').textContent = formatElapsed(Date.now() - runStartedAt);
  }, 1000);
}

function stopRunProgress() {
  if (runTimer) { clearInterval(runTimer); runTimer = null; }
}

// Stage markers printed by src/cli/sim_helper.py (STAGE 1/2/3, BASELINE).
const RUN_STAGE_LABELS = {
  'STAGE 1': 'Stage 1 of 3 · Fast filtering',
  'STAGE 2': 'Stage 2 of 3 · Refinement',
  'STAGE 3': 'Stage 3 of 3 · Final selection',
  'BASELINE': 'Baseline only',
};

let lastProgressPct = 0;
let lastMetaAt = 0;

function updateRunProgressMeta(text) {
  const line = String(text).trim();
  if (!line) return;
  const progress = line.match(/Progress:\s*(\d+)%\s*\(([^)]+)\)/);
  if (progress) {
    setRunProgress(Number(progress[1]), `${progress[1]}% · ${progress[2]} profiles`);
    return;
  }
  for (const marker of Object.keys(RUN_STAGE_LABELS)) {
    if (line.includes(marker)) { setRunStage(RUN_STAGE_LABELS[marker]); return; }
  }
  setRunMeta(line.length > 90 ? `${line.slice(0, 90)}…` : line);
}

function setRunProgress(pct, meta) {
  lastProgressPct = Math.min(100, Math.max(0, pct));
  const fill = document.getElementById('run-progress-fill');
  if (fill) {
    fill.style.width = `${lastProgressPct}%`;
    fill.setAttribute('aria-valuenow', String(lastProgressPct));
  }
  setRunMeta(meta);
  updateRunEta();
}

function setRunStage(label) {
  const el = document.getElementById('run-stage');
  if (el) el.textContent = label;
}

// aria-live polite throttled to <=1 update/s (doc 4.2) so fast log lines
// never spam screen readers.
function setRunMeta(text) {
  const now = Date.now();
  if (now - lastMetaAt < 1000) return;
  lastMetaAt = now;
  const meta = document.getElementById('run-progress-meta');
  if (meta) meta.textContent = text;
}

// t_2ab8f3be: log rendering was O(n^2) (textContent += per line) and froze
// the tab on long runs. Full lines stay in logLines for the download button;
// the DOM shows only the last LOG_RENDER_CAP lines, repainted once per frame.
const LOG_RENDER_CAP = 2000;
let logLines = [];
let logRenderQueued = false;

function pushLogLines(lines) {
  logLines.push(...lines);
  logLineCount += lines.length;
  if (!logRenderQueued) {
    logRenderQueued = true;
    requestAnimationFrame(renderLogTail);
  }
}

function renderLogTail() {
  logRenderQueued = false;
  const log = document.getElementById('simulation-log');
  if (!log) return;
  log.textContent = logLines.slice(-LOG_RENDER_CAP).join('\n') + '\n';
  const follow = document.getElementById('log-follow');
  if (!follow || follow.checked) log.scrollTop = log.scrollHeight;
}

function downloadLog() {
  const blob = new Blob([logLines.join('\n')], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `simc-run-${currentTaskId || Date.now()}.log`;
  a.click();
  URL.revokeObjectURL(a.href);
}

let currentTaskId = '';

function updateRunEta() {
  const eta = document.getElementById('run-eta');
  if (!eta) return;
  // ETA only after 5% so the first noisy samples do not skew it (doc 4.2).
  if (lastProgressPct < 5 || !runStartedAt) { eta.hidden = true; return; }
  const remainSec = Math.round((Date.now() - runStartedAt) * (100 - lastProgressPct) / lastProgressPct / 1000);
  eta.hidden = false;
  eta.textContent = remainSec < 60 ? `~${remainSec}s left` : `~${Math.round(remainSec / 60)} min left`;
}

async function stopSimulation() {
  const status = document.getElementById('workflow-status');
  let token = window.localStorage.getItem('simc-admin-token') || '';
  const entered = window.prompt(
    'Stopping a simulation requires the master admin token (ADMIN_TOKEN):', token);
  if (entered === null) return;
  token = entered.trim();
  try {
    const response = await apiFetch('api/stop-simulation', {
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

// t_2ab8f3be: icon and name merged into ONE anchor (was 2 tab stops per card,
// 42+ per slot group). nameHtml must arrive pre-escaped.
function createWowheadIconLink(itemId, bonusIds = '', nameHtml = '') {
  const safeId = encodeURIComponent(itemId || '0');
  const safeBonus = String(bonusIds || '').split('/').filter(value => /^\d+$/.test(value)).join(':');
  const bonusQuery = safeBonus ? `?bonus=${encodeURIComponent(safeBonus)}` : '';
  const tooltipData = safeBonus ? `bonus=${safeBonus}&iconsize=large` : 'iconsize=large';
  return `<a href="https://www.wowhead.com/item=${safeId}${bonusQuery}" class="item-icon-link wowhead-item-link" data-wowhead="${tooltipData}" data-wh-rename="false" target="_blank"><img src="api/item-icon/${safeId}" alt="" loading="lazy" onerror="this.closest('.item-icon-link').classList.add('icon-missing')">${nameHtml}</a>`;
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

/* Upgrade ranks straight from the export's own `# upgrade_levels=` comment
   (authoritative for this character), preferred over the static season
   ladders whenever present.  The addon lists only levels other than the
   item's current one, with ilvl increments relative to the current ilvl,
   so rank 0 is "Current" and ranks 1..N are the export-provided upgrades. */
function exportRanksFor(slot, item) {
  const info = parsedData?.item_upgrades?.[item];
  const levels = Array.isArray(info?.levels) ? info.levels : null;
  if (!levels || !levels.length) return null;
  const current = Number(parseItemParams(item).ilevel) ||
    itemLevelFromLabel(parsedData?.item_names?.[item]);
  if (!current) return null;
  return [
    { rank: 0, level: current, label: 'Current' },
    ...levels.map((lvl, index) => ({
      rank: index + 1,
      level: current + (Number(lvl.ilvl_increment) || 0),
      label: `Upgrade ${lvl.upgrade_level}`
    })),
  ];
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
  twoHandedItems = new Set();
  selectedEnchants = {};
  selectedGems = new Set();
  equippedEnchants = {};
  equippedGems = new Set();
  gearUpgrades = {};
  voidforgedItems = {};
  extraSockets = {};
  slotSorts = {};
  statScores = {};
  addedItems = new Map();
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
      const exportRanks = exportRanksFor(slot, item);
      if (exportRanks) {
        // Export-provided upgrade data wins: default to the item's current
        // rank with an absolute ilvl, bypassing the static ladder entirely.
        gearUpgrades[slot][item] = {
          ...(gearUpgrades[slot][item] || {}),
          source: 'export',
          rank: 0,
          item_level: exportRanks[0].level,
        };
      }
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
      const hasVariation = !equipped.includes(item) || enchantCount > 0 || gemCount > 0 ||
        extraSockets[slot] || Boolean(gearUpgrades[slot]?.[item]?.user_selected);
      if (hasVariation) total += Math.max(1, enchantCount) * Math.max(1, gemCount);
    }
  }
  return total;
}

function updateSummary() {
  // t_8bf63ec6: in combinations mode the server count is authoritative —
  // show '…' until the first generate-simc response replaces the estimate.
  const combosMode = document.getElementById('compare-mode')?.value === 'combinations';
  const server = combosMode && generatedInput?.mode === 'combinations' ? generatedInput : null;
  const count = combosMode && !server ? null : (server ? server.combinations : estimateCombinations());
  const countEl = document.getElementById('combo-count');
  const itemCountEl = document.getElementById('selected-item-count');
  const runButton = document.getElementById('btn-run');
  if (countEl) countEl.textContent = count === null ? '…' : count.toLocaleString();
  if (itemCountEl) itemCountEl.textContent = selectedItemCount().toLocaleString();
  const comboWord = document.getElementById('combo-word');
  const itemWord = document.getElementById('item-word');
  if (comboWord) comboWord.textContent = count === 1 ? 'combination' : 'combinations';
  if (itemWord) itemWord.textContent = selectedItemCount() === 1 ? 'item' : 'items';
  const estimateEl = document.getElementById('work-estimate');
  if (estimateEl) estimateEl.textContent = server?.work_estimate_minutes != null && count > 0
    ? ` · ≈${server.work_estimate_minutes} min stage 1 (est.)`
    : '';
  // t_4485565b: once a character is loaded, Run is always meaningful — a
  // 0-candidate selection runs the baseline current-gear report.
  if (runButton) runButton.disabled = !(generatedInput || parsedData);
  updateRailState();
}

function selectionChanged() {
  generatedInput = null;
  updateSummary();
  syncEnhancementChips();
  clearTimeout(generationTimer);
  // t_4485565b: regenerate even at an estimated 0 combinations so the status
  // line reflects the honest baseline-only state instead of a stale count.
  const status = document.getElementById('workflow-status');
  if (status) status.textContent = 'Updating comparison…';
  renderSlotConflict();
  generationTimer = setTimeout(() => generateInput(true), 250);
}

function renderTrackControls(slot, item) {
  if (isCraftedItem(item)) return '';
  const upgrade = gearUpgrades[slot]?.[item] || {};
  const currentLevel = Number(parseItemParams(item).ilevel) ||
    itemLevelFromLabel(parsedData?.item_names?.[item]);
  const exportRanks = exportRanksFor(slot, item);
  if (!exportRanks && isElevatedLevel(currentLevel)) return '';
  const trackOptions = ['none', ...Object.keys(seasonTracks())]
    .map(track => `<option value="${track}" ${upgrade.track === track ? 'selected' : ''}>${track === 'none' ? 'No grade' : track[0].toUpperCase() + track.slice(1)}</option>`)
    .join('');
  const levels = exportRanks || seasonTracks()[upgrade.track] || [];
  const rankOptions = exportRanks
    ? exportRanks.map(rank => `<option value="${rank.rank}" ${upgrade.rank === rank.rank ? 'selected' : ''}>${escapeHtml(rank.label)} · ilvl ${rank.level}</option>`).join('')
    : levels.map((level, index) =>
        `<option value="${index + 1}" ${upgrade.rank === index + 1 ? 'selected' : ''}>Rank ${index + 1} · ${level}</option>`
      ).join('');
  return `<select class="gear-track-select" aria-label="Track">${trackOptions}</select><select class="gear-rank-select" aria-label="Rank" ${levels.length ? '' : 'disabled'}>${levels.length ? rankOptions : '<option value="">Rank</option>'}</select>`;
}

/* Grade-state badges get one slot on every card (.gear-card-badges) so
   their placement never varies between cards. */
function cardBadges(slot, item) {
  const badges = [];
  if (isCraftedItem(item)) {
    badges.push('<span class="crafted-badge">Crafted · no grade</span>');
  } else {
    const currentLevel = Number(parseItemParams(item).ilevel) ||
      itemLevelFromLabel(parsedData?.item_names?.[item]);
    if (!exportRanksFor(slot, item) && isElevatedLevel(currentLevel)) {
      badges.push('<span class="crafted-badge">Elevated · not upgradeable</span>');
    }
  }
  return `<div class="gear-card-badges">${badges.join('')}</div>`;
}

/* ---------- Live upgrade preview (Wowhead tooltip proxy) ---------- */

const upgradePreviewCache = new Map();
const upgradePreviewTimers = new Map();
const UPGRADE_PREVIEW_DEBOUNCE_MS = 400;

function targetUpgradeLevel(slot, item) {
  const upgrade = gearUpgrades[slot]?.[item];
  if (!upgrade) return null;
  const ascension = seasonAscension();
  if (voidforgedItems[slot]?.[item]) {
    // A crafted base ascends to the season's lower crafted_results ilvl
    // (mirror of backend apply_gear_upgrade); track items use results.
    const crafted = isCraftedItem(item) ? ascension.crafted_results?.[upgrade.track] : null;
    const target = crafted != null ? crafted : ascension.results?.[upgrade.track];
    if (target != null) return Number(target);
  }
  // Export-provided entries carry their own absolute ilvl.
  if (upgrade.source === 'export' && upgrade.item_level != null) {
    return Number(upgrade.item_level);
  }
  if (!upgrade.track) return null;
  const levels = seasonTracks()[upgrade.track] || [];
  return levels[upgrade.rank - 1] ?? null;
}

function scheduleUpgradePreview(slot, item, card) {
  const key = `${slot}|${item}`;
  clearTimeout(upgradePreviewTimers.get(key));
  upgradePreviewTimers.set(key, setTimeout(() => {
    upgradePreviewTimers.delete(key);
    void fetchUpgradePreview(slot, item, card);
  }, UPGRADE_PREVIEW_DEBOUNCE_MS));
}

function renderUpgradePreview(host, data, target, current) {
  const preview = data.preview || {};
  const delta = data.delta || {};
  const resulting = preview.ilvl ?? target;
  const ilvlDelta = delta.ilvl ??
    (resulting != null && current != null ? resulting - current : null);
  const dot = preview.quality_color
    ? `<span class="upgrade-preview-dot" style="background:${escapeHtml(preview.quality_color)}"></span>`
    : '';
  let html = `${dot}<span class="upgrade-preview-ilvl">ilvl ${current ?? '?'} → <b>${resulting ?? '?'}</b>`;
  if (ilvlDelta) {
    html += ` <b class="upgrade-preview-delta ${ilvlDelta > 0 ? 'positive' : 'negative'}">` +
      `${ilvlDelta > 0 ? '+' : '−'}${Math.abs(ilvlDelta)}</b>`;
  }
  html += '</span>';
  const stats = (delta.stats || []).slice(0, 4);
  if (stats.length) {
    html += '<span class="upgrade-preview-stats">' + stats.map(stat =>
      `<span class="upgrade-preview-stat ${stat.delta > 0 ? 'positive' : 'negative'}">` +
      `${escapeHtml(stat.label)} ${stat.delta > 0 ? '+' : '−'}${Math.abs(stat.delta).toLocaleString()}</span>`
    ).join('') + '</span>';
  }
  host.className = 'upgrade-preview';
  host.innerHTML = html;
}

async function fetchUpgradePreview(slot, item, card) {
  const host = card.querySelector('.upgrade-preview');
  if (!host) return;
  const params = parseItemParams(item);
  const target = targetUpgradeLevel(slot, item);
  const current = Number(params.ilevel) ||
    itemLevelFromLabel(parsedData?.item_names?.[item]) || null;
  if (!params.id || !target || !current || target === current) {
    host.hidden = true;
    host.textContent = '';
    return;
  }
  const query = new URLSearchParams({ item: params.id, ilvl: String(target) });
  const bonusIds = String(params.bonus_id || '').split('/')
    .filter(value => /^\d+$/.test(value)).join(':');
  if (bonusIds) query.set('bonus', bonusIds);
  const url = `api/wowhead/tooltip?${query}`;
  host.hidden = false;
  host.className = 'upgrade-preview is-loading';
  host.textContent = 'Previewing upgrade…';
  try {
    let data = upgradePreviewCache.get(url);
    if (!data) {
      const response = await apiFetch(url);
      if (!response.ok) throw new Error(`status ${response.status}`);
      data = await response.json();
      upgradePreviewCache.set(url, data);
    }
    if (!card.isConnected) return;
    renderUpgradePreview(host, data, target, current);
  } catch (error) {
    if (!card.isConnected) return;
    host.className = 'upgrade-preview is-unavailable';
    host.textContent = 'preview unavailable';
    host.title = `Wowhead preview unavailable (${error.message})`;
  }
}

/* ---------- Per-slot sorting (ilvl / name / heuristic stat priority) ---------- */

function sortItemsForSlot(slot, items) {
  const mode = slotSorts[slot] || 'ilvl';
  const levelOf = item => itemLevelFromLabel(parsedData?.item_names?.[item]) ||
    Number(parseItemParams(item).ilevel) || 0;
  const nameOf = item => String(parsedData?.item_names?.[item] || '')
    .replace(/\s*\(\d+\)$/, '').toLowerCase();
  const sorted = [...items];
  if (mode === 'name') {
    sorted.sort((a, b) => nameOf(a).localeCompare(nameOf(b)) || levelOf(b) - levelOf(a));
  } else if (mode === 'priority') {
    // Failed lookups score -1 and sink to the bottom; ties fall back to ilvl.
    sorted.sort((a, b) => ((statScores[b] ?? -1) - (statScores[a] ?? -1)) ||
      levelOf(b) - levelOf(a));
  } else {
    sorted.sort((a, b) => levelOf(b) - levelOf(a));
  }
  return sorted;
}

async function ensureStatScores(slot, items, selectEl) {
  const pending = items.filter(item => !(item in statScores) && parseItemParams(item).id);
  if (!pending.length) return;
  if (selectEl) { selectEl.disabled = true; selectEl.classList.add('is-scoring'); }
  const status = document.getElementById('workflow-status');
  try {
    for (let start = 0; start < pending.length; start += STAT_SORT_BATCH) {
      const chunk = pending.slice(start, start + STAT_SORT_BATCH);
      const response = await apiFetch('api/wowhead/tooltips/batch', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          char_class: parsedData.char_class,
          items: chunk.map(item => {
            const params = parseItemParams(item);
            return { item: Number(params.id), bonus: params.bonus_id || null };
          })
        })
      });
      if (!response.ok) throw new Error(`status ${response.status}`);
      const data = await response.json();
      (data.results || []).forEach((result, position) => {
        const key = chunk[result.index ?? position];
        if (key) statScores[key] = result.ok ? (result.score ?? 0) : -1;
      });
    }
  } catch (error) {
    if (status) {
      status.textContent =
        `Stat-priority sort unavailable (${error.message}) — sorted by ilvl instead.`;
    }
    if (slotSorts[slot] === 'priority') slotSorts[slot] = 'ilvl';
  } finally {
    if (selectEl) { selectEl.disabled = false; selectEl.classList.remove('is-scoring'); }
  }
}

/* ---------- Add-an-item by Wowhead id (items owned but not exported) ---------- */

function showSlotAddMessage(host, kind, message) {
  host.hidden = false;
  host.className = `slot-add-preview is-${kind}`;
  host.textContent = message;
}

function commitAddedItem(slot, itemId, preview) {
  const key = `id=${itemId}`;
  const items = parsedData.items_by_slot[slot] || (parsedData.items_by_slot[slot] = []);
  if (!items.includes(key)) {
    items.push(key);
    parsedData.item_names[key] = `${preview.name || `Item ${itemId}`} (${preview.ilvl || 0})`;
    gearUpgrades[slot] = gearUpgrades[slot] || {};
    voidforgedItems[slot] = voidforgedItems[slot] || {};
    const inferred = inferMidnightUpgrade(slot, key, parsedData.item_names[key]);
    if (inferred) gearUpgrades[slot][key] = inferred;
    voidforgedItems[slot][key] = false;
    addedItems.set(key, slot);
  }
  selectedItems[slot] = selectedItems[slot] || new Set();
  selectedItems[slot].add(key);
  renderGear();
  renderCharChip();
  updateSummary();
  selectionChanged();
}

function removeAddedItem(slot, item) {
  const items = parsedData.items_by_slot[slot];
  if (items) {
    const index = items.indexOf(item);
    if (index >= 0) items.splice(index, 1);
  }
  delete parsedData.item_names[item];
  selectedItems[slot]?.delete(item);
  delete gearUpgrades[slot]?.[item];
  delete voidforgedItems[slot]?.[item];
  delete statScores[item];
  addedItems.delete(item);
  renderGear();
  renderCharChip();
  selectionChanged();
}

function renderSlotAddPreview(slot, itemId, preview, host, addInput) {
  host.className = 'slot-add-preview';
  host.innerHTML =
    `<img src="api/item-icon/${itemId}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` +
    `<span class="slot-add-name"${preview.quality_color ? ` style="color:${escapeHtml(preview.quality_color)}"` : ''}>` +
      `${escapeHtml(preview.name || `Item ${itemId}`)}</span>` +
    `<span class="slot-add-meta">${preview.ilvl ? `ilvl ${preview.ilvl}` : 'ilvl unknown'}` +
      `${preview.upgrade_level ? ` · ${escapeHtml(preview.upgrade_level)}` : ''}</span>` +
    `<button type="button" class="slot-add-confirm">Add to ${escapeHtml(slot.replace('_', ' '))}</button>`;
  host.querySelector('.slot-add-confirm').addEventListener('click', () => {
    commitAddedItem(slot, itemId, preview);
    addInput.value = '';
    addInput.focus();
  });
}

function wireSlotAddForm(group, slot) {
  const addInput = group.querySelector('.slot-add-input');
  const addButton = group.querySelector('.slot-add-button');
  const addPreview = group.querySelector('.slot-add-preview');
  const previewAdd = async () => {
    const raw = addInput.value.trim();
    if (!/^\d{1,9}$/.test(raw)) {
      showSlotAddMessage(addPreview, 'error', 'Enter a numeric Wowhead item ID (see the item link, e.g. wowhead.com/item=276000).');
      return;
    }
    const itemId = Number(raw);
    showSlotAddMessage(addPreview, 'loading', `Resolving item ${itemId} on Wowhead…`);
    try {
      const response = await apiFetch(`api/wowhead/tooltip?item=${itemId}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `status ${response.status}`);
      renderSlotAddPreview(slot, itemId, data.preview || {}, addPreview, addInput);
    } catch (error) {
      showSlotAddMessage(addPreview, 'error',
        `Could not resolve item ${itemId} on Wowhead (${error.message}).`);
    }
  };
  addButton.addEventListener('click', previewAdd);
  addInput.addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); previewAdd(); }
  });
}

// TG2-A (design t_0fbfd0bd §3.1): enhancement state chips on the slot-group
// header — pure state echo of step-3 selections plus a jump-and-open shortcut.
// No new state: labels recompute from selectedEnchants/selectedGems live.
// TG2-F (t_61442157): worn items are pre-checked without entering the selected
// sets, so the chip counts the UNION with the equipped sets to match the
// step-3 panel's checked count by construction.
function enhancementChipLabel(kind, slot) {
  if (kind === 'enchants') {
    if (!(appConfig.enchantments?.[slot] || []).length) return null;
    const k = new Set([...(selectedEnchants[slot] || []), ...(equippedEnchants[slot] || [])]).size;
    const e = equippedEnchants[slot]?.size || 0;
    return `Enchants: ${k} selected` + (e > 0 && e < k ? ` · worn ${e}` : '');
  }
  if (!(appConfig.gems?.standard || []).length) return null;
  const k = new Set([...selectedGems, ...equippedGems]).size;
  return k ? `Gems: ${k} selected` : 'Gems: none';
}

function syncEnhancementChips() {
  document.querySelectorAll('.enh-chip').forEach(chip => {
    const label = enhancementChipLabel(chip.dataset.kind, chip.dataset.slot);
    if (label) chip.textContent = label;
  });
}

function jumpToEnhancement(kind, slot) {
  document.getElementById('step-enhance')?.scrollIntoView({ block: 'start' });
  // Mirror generate_input.py's off_hand -> main_hand enchant-list fallback.
  const titles = kind === 'gems'
    ? ['Flawless gems']
    : (slot === 'off_hand'
      ? [`${slot.replace('_', ' ')} enchants`, 'main hand enchants']
      : [`${slot.replace('_', ' ')} enchants`]);
  const sections = [...document.querySelectorAll('#enhancement-options .enh-section')];
  for (const title of titles) {
    const section = sections.find(s => s.dataset.enhTitle === title);
    if (section) {
      section.open = true;
      section.querySelector('summary')?.focus();
      return;
    }
  }
}

function renderGear() {
  const grid = document.getElementById('gear-grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (const [slot, items] of Object.entries(parsedData.items_by_slot)) {
    const group = document.createElement('section');
    group.className = 'slot-group';
    group.dataset.slot = slot;
    const chipDefs = [['enchants', 'Open enchantment controls in step 3'],
      ['gems', 'Open gem controls in step 3']];
    let chipsHtml = '';
    for (const [kind, hint] of chipDefs) {
      const chipLabel = enhancementChipLabel(kind, slot);
      if (chipLabel) {
        chipsHtml += `<button type="button" class="enh-chip" data-kind="${kind}" ` +
          `data-slot="${slot}" title="${hint}">${escapeHtml(chipLabel)}</button>`;
      }
    }
    group.innerHTML = `<div class="slot-group-header"><h3>${escapeHtml(slot.replace('_', ' '))}</h3>` +
      `<span class="slot-count"></span>${chipsHtml}` +
      `<select class="slot-sort-select" aria-label="Sort ${escapeHtml(slot)} candidates" ` +
      `title="Sort candidates. 'Stat priority' is a heuristic class weight order, not a sim result.">` +
      `<option value="ilvl">ilvl ↓</option><option value="name">Name</option>` +
      `<option value="priority">Stat priority*</option></select>` +
      `<button type="button" class="slot-toggle-all">Select none</button>` +
      `<button type="button" class="btn-ghost slot-add-toggle" aria-expanded="false">Add by ID</button></div>` +
      `<div class="slot-add-form">` +
      `<input type="text" class="slot-add-input" inputmode="numeric" autocomplete="off" ` +
      `placeholder="Own it but not in the export? Add by Wowhead item id…" ` +
      `aria-label="Wowhead item id to add to ${escapeHtml(slot)}">` +
      `<button type="button" class="slot-add-button">Preview</button></div>` +
      `<div class="slot-add-preview" hidden></div>` +
      `<div class="slot-items"></div>`;
    const itemGrid = group.querySelector('.slot-items');
    const slotCountEl = group.querySelector('.slot-count');
    const slotToggleAll = group.querySelector('.slot-toggle-all');
    const sortSelect = group.querySelector('.slot-sort-select');
    sortSelect.value = slotSorts[slot] || 'ilvl';
    sortSelect.addEventListener('change', () => {
      slotSorts[slot] = sortSelect.value;
      if (sortSelect.value === 'priority') {
        void ensureStatScores(slot, items, sortSelect).then(renderGear);
      } else {
        renderGear();
      }
    });
    wireSlotAddForm(group, slot);
    // t_2ab8f3be: add-by-id is a power feature — collapsed until asked for.
    const addToggle = group.querySelector('.slot-add-toggle');
    const addForm = group.querySelector('.slot-add-form');
    addForm.hidden = true;
    addToggle.addEventListener('click', () => {
      const open = addForm.hidden;
      addForm.hidden = !open;
      addToggle.setAttribute('aria-expanded', String(open));
      if (open) addForm.querySelector('.slot-add-input').focus();
    });
    const syncSlotHeader = () => {
      slotCountEl.textContent = `${selectedItems[slot].size}/${items.length} selected`;
      slotToggleAll.textContent = items.length && selectedItems[slot].size === items.length
        ? 'Select none' : 'Select all';
      // §3.3: chips ride the same listener so counts refresh on select-all
      // or any item toggle without new state.
      syncEnhancementChips();
    };
    syncSlotHeader();
    group.querySelectorAll('.enh-chip').forEach(chip => {
      chip.addEventListener('click', () => jumpToEnhancement(chip.dataset.kind, chip.dataset.slot));
    });
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
    for (const item of sortItemsForSlot(slot, items)) {
      const params = parseItemParams(item);
      const label = parsedData.item_names[item] || `${slot} ${params.id || ''}`;
      const level = itemLevelFromLabel(label) || Number(params.ilevel) || null;
      const card = document.createElement('article');
      card.className = `item-option gear-card ${selectedItems[slot].has(item) ? 'is-selected' : ''}`;
      card.dataset.slot = slot;
      card.dataset.item = item;
      card.innerHTML = `
        <label class="item-select-row">
          <input type="checkbox" class="item-select-input" ${selectedItems[slot].has(item) ? 'checked' : ''}>
          <span class="gear-card-info">${createWowheadIconLink(params.id, params.bonus_id, `<span class="item-option-name gear-card-name">${escapeHtml(label.replace(/\s*\(\d+\)/, ''))}</span>`)}${addedItems.has(item) ? '<span class="added-badge">Added</span>' : ''}<span class="gear-card-slot"><span>Item level</span><span class="gear-card-slot-ilvl">${level ? level : '—'}</span></span></span>
        </label>
        ${cardBadges(slot, item)}
        ${upgradePopoverMarkup(slot, item)}
        ${addedItems.has(item) ? `<button type="button" class="slot-remove-added" title="Remove this added item from the candidates"><span class="sr-only">Remove ${escapeHtml(label.replace(/\s*\(\d+\)/, ''))} from candidates</span>×</button>` : ''}
      `;

      const removeAddedButton = card.querySelector('.slot-remove-added');
      if (removeAddedButton) {
        removeAddedButton.addEventListener('click', () => removeAddedItem(slot, item));
      }

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
          if (exportRanksFor(slot, item)) {
            // Export-provided ranks stay; track only labels ascension context.
            const entry = gearUpgrades[slot][item] ||
              { source: 'export', rank: 0, item_level: exportRanksFor(slot, item)[0].level };
            if (track === 'none') delete entry.track;
            else entry.track = track;
            entry.user_selected = true;
            gearUpgrades[slot][item] = entry;
            rankSelect.disabled = false;
          } else if (track === 'none') {
            delete gearUpgrades[slot][item];
            rankSelect.innerHTML = '';
            rankSelect.disabled = true;
          } else {
            gearUpgrades[slot][item] = { track, rank: 1, user_selected: true };
            rankSelect.innerHTML = (seasonTracks()[track] || []).map((level, index) =>
              `<option value="${index + 1}">Rank ${index + 1} · ${level}</option>`
            ).join('');
            rankSelect.disabled = false;
          }
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
        rankSelect.addEventListener('change', () => {
          const entry = gearUpgrades[slot][item];
          if (entry) {
            entry.rank = Number(rankSelect.value);
            const exportRanks = exportRanksFor(slot, item);
            if (exportRanks) {
              const picked = exportRanks.find(rank => rank.rank === entry.rank);
              if (picked) entry.item_level = picked.level;
            } else {
              const levels = seasonTracks()[entry.track] || [];
              entry.item_level = levels[entry.rank - 1] ?? null;
            }
            // Export rank 0 is the item's current level again, so the entry
            // stops being a user-chosen upgrade; anything else is a choice
            // that belongs to the candidate copies only.
            if (entry.rank === 0) delete entry.user_selected;
            else entry.user_selected = true;
          }
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
      }

      const voidforgeInput = card.querySelector('.voidforge-input');
      if (voidforgeInput) {
        voidforgeInput.addEventListener('change', event => {
          voidforgedItems[slot][item] = event.target.checked;
          // Checking Ascension is a user choice: mark the grade entry so the
          // backend keeps it off the baseline (only meaningful when a grade
          // entry exists to carry the flag).
          if (event.target.checked && gearUpgrades[slot]?.[item]) {
            gearUpgrades[slot][item].user_selected = true;
          }
          event.currentTarget.closest('.voidforge-field-container')?.classList.toggle('is-active', event.target.checked);
          scheduleUpgradePreview(slot, item, card);
          selectionChanged();
        });
      }
      const upgradeTrigger = card.querySelector('.upgrade-trigger');
      if (upgradeTrigger) {
        const pop = card.querySelector('.popover');
        wirePopover(upgradeTrigger, pop);
        pop.addEventListener('change', () => {
          card.querySelector('.upgrade-state').textContent = upgradeStateText(slot, item);
        });
      }
      itemGrid.appendChild(card);
    }

    // t_2ab8f3be: slot collapse (doc 4.2) — selected + top 3 visible, rest
    // behind a toggle so 42-card slots stop dominating the tab order.
    const cards = [...itemGrid.children];
    let collapsedCount = 0;
    cards.forEach((card, index) => {
      if (index >= 3 && !card.classList.contains('is-selected')) {
        card.classList.add('is-collapsed');
        collapsedCount += 1;
      }
    });
    if (collapsedCount) {
      const showAll = document.createElement('button');
      showAll.type = 'button';
      showAll.className = 'btn-ghost slot-show-all';
      showAll.setAttribute('aria-expanded', 'false');
      const label = `Show all ${cards.length} items (${collapsedCount} hidden)`;
      showAll.textContent = label;
      showAll.addEventListener('click', () => {
        const open = itemGrid.classList.toggle('is-expanded');
        showAll.setAttribute('aria-expanded', String(open));
        showAll.textContent = open ? 'Show fewer' : label;
      });
      itemGrid.after(showAll);
    }

    if ((appConfig.gems?.standard || []).length) {
      const socketControl = document.createElement('label');
      socketControl.className = 'extra-socket-control';
      socketControl.innerHTML = `<input type="checkbox"> Add/test an extra socket on ${escapeHtml(slot.replace('_', ' '))}`;
      socketControl.querySelector('input').addEventListener('change', event => {
        extraSockets[slot] = event.target.checked;
        selectionChanged();
      });
      group.appendChild(socketControl);
    }
    grid.appendChild(group);
  }
  refreshWowheadLinks();
  renderSlotConflict();
}

// t_2ab8f3be: shared popover behavior (gear upgrade + pre-run diff, doc 5):
// aria-expanded, Esc, outside-click, focus return, Tab trap.
function wirePopover(trigger, popover, onOpen) {
  const focusables = () => [...popover.querySelectorAll('button, select, input, a[href]')]
    .filter(el => !el.disabled && el.offsetParent !== null);
  function onKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const els = focusables();
    if (!els.length) return;
    const first = els[0];
    const last = els[els.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  function onDoc(event) {
    if (!popover.contains(event.target) && event.target !== trigger) close(false);
  }
  function open() {
    popover.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    if (onOpen) onOpen();
    focusables()[0]?.focus();
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('click', onDoc, true);
  }
  function close(focusBack = true) {
    if (popover.hidden) return;
    popover.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('click', onDoc, true);
    if (focusBack) trigger.focus();
  }
  trigger.setAttribute('aria-expanded', 'false');
  trigger.addEventListener('click', () => { if (popover.hidden) open(); else close(); });
}

function upgradeStateText(slot, item) {
  const upgrade = gearUpgrades[slot]?.[item];
  const level = targetUpgradeLevel(slot, item);
  const bits = [];
  if (upgrade?.track) bits.push(upgrade.track[0].toUpperCase() + upgrade.track.slice(1) + (upgrade.rank ? ` ${upgrade.rank}` : ''));
  else if (upgrade?.source === 'export') bits.push('Export ladder');
  else bits.push('No grade');
  if (level != null) bits.push(`ilvl ${level}`);
  return bits.join(' \u00b7 ');
}

function upgradePopoverMarkup(slot, item) {
  const controls = renderTrackControls(slot, item);
  const voidforge = isVoidforgeEligibleSlot(slot)
    ? `<label class="voidforge-field-container"><input type="checkbox" class="voidforge-input" ${voidforgedItems[slot][item] ? 'checked' : ''}> ${seasonAscension().name || 'Ascendant'} \u00d7${seasonAscension().cost ?? ''}</label>`
    : '';
  if (!controls && !voidforge) return '';
  return `<div class="gear-card-controls popover-host">` +
    `<span class="upgrade-state">${escapeHtml(upgradeStateText(slot, item))}</span>` +
    `<button type="button" class="btn-ghost upgrade-trigger" aria-expanded="false" aria-haspopup="dialog">Upgrade\u2026</button>` +
    `<div class="popover" hidden>${controls}${voidforge}<div class="upgrade-preview" hidden></div></div></div>`;
}

// Pre-run diff (doc 5): client-side summary only; the server combo count in
// the run bar stays authoritative.
function renderReviewPopover() {
  const pop = document.getElementById('review-popover');
  if (!pop) return;
  const rows = [];
  for (const [slot, items] of Object.entries(selectedItems)) {
    for (const item of items) {
      const name = parsedData.item_names[item] || item;
      rows.push(`<tr><td>${escapeHtml(slot.replace('_', ' '))}</td><td>${escapeHtml(String(name).replace(/\s*\(\d+\)/, ''))}</td><td>${escapeHtml(upgradeStateText(slot, item))}</td></tr>`);
    }
  }
  pop.innerHTML = rows.length
    ? `<table class="diff-table"><thead><tr><th scope="col">Slot</th><th scope="col">Item</th><th scope="col">Grade</th></tr></thead><tbody>${rows.join('')}</tbody></table>`
    : '<small>No items selected yet.</small>';
}

// shortcut: PVP meta gems are excluded by name substring; upgrade to item-id
// filtering when the backend exposes gem ids.
const PVP_META_NAME_MATCH = /heliotrope/i;

function renderEnhancements() {
  const container = document.getElementById('enhancement-options');
  container.innerHTML = '';
  // t_2ab8f3be (doc 4.3): 68 flat checkboxes -> searchable, grouped <details>
  // sections. t_16e4f177 (leader ruling, supersedes doc 4.2 open-if-checked
  // clause): ALL groups start closed — the doc's clause forced every group
  // holding an equipped/checked candidate open, keeping 136 chip stops
  // permanently in the tab order. Selection state stays visible in the
  // summary label instead; the search input opens matches on demand.
  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'enh-search';
  search.placeholder = 'Search enchantments and gems\u2026';
  search.setAttribute('aria-label', 'Search enchantments and gems');
  container.appendChild(search);

  const addSection = (title, build) => {
    const section = document.createElement('details');
    section.className = 'enh-section';
    section.dataset.enhTitle = title; // chips open sections by stable title (§3.1)
    const summary = document.createElement('summary');
    const group = document.createElement('fieldset');
    group.className = 'enhancement-group';
    build(group);
    const total = group.querySelectorAll('input').length;
    const renderLabel = () => {
      const checked = group.querySelectorAll('input:checked').length;
      summary.textContent = checked
        ? `${title} \u00b7 ${checked} selected`
        : `${title} (${total})`;
    };
    renderLabel();
    group.addEventListener('change', renderLabel);
    section.append(summary, group);
    container.appendChild(section);
  };

  for (const [slot, enchants] of Object.entries(appConfig.enchantments || {})) {
    if (!enchants.length || !parsedData.items_by_slot[slot]) continue;
    addSection(`${slot.replace('_', ' ')} enchants`, group => {
      for (const enchant of enchants) {
        const id = String(typeof enchant === 'object' ? enchant.id : enchant);
        const name = typeof enchant === 'object' ? enchant.name : `Enchant ${id}`;
        const equipped = equippedEnchants[slot].has(id);
        const label = document.createElement('label');
        label.className = 'choice-chip';
        label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(enchant, name)}` +
          (equipped ? '<span class="equipped-badge">equipped</span>' : '');
        const input = label.querySelector('input');
        input.checked = selectedEnchants[slot].has(id) || equipped;
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
    });
  }

  const gems = (appConfig.gems?.standard || []).filter(gem =>
    !PVP_META_NAME_MATCH.test(String(gem.name || ''))
  );
  if (gems.length) {
    addSection('Flawless gems', group => {
      group.className = 'enhancement-group gems-group';
      for (const gem of gems) {
        const id = String(typeof gem === 'object' ? gem.id : gem);
        const name = typeof gem === 'object' ? gem.name : `Gem ${id}`;
        const equipped = equippedGems.has(id);
        const label = document.createElement('label');
        label.className = 'choice-chip';
        label.innerHTML = `<input type="checkbox">${createEnhancementWowheadLink(gem, name)}` +
          (equipped ? '<span class="equipped-badge">equipped</span>' : '');
        const input = label.querySelector('input');
        input.checked = selectedGems.has(id) || equipped;
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
    });
  }

  // NB4 (review t_89761608): remember which sections the SEARCH opened so
  // clearing the query re-closes exactly those, never user-opened ones.
  const searchOpened = new Set();
  search.addEventListener('input', () => {
    const needle = search.value.trim().toLowerCase();
    container.querySelectorAll('.enh-section').forEach(section => {
      let visible = 0;
      section.querySelectorAll('.choice-chip').forEach(chip => {
        const hit = !needle || chip.textContent.toLowerCase().includes(needle);
        chip.hidden = !hit;
        if (hit) visible += 1;
      });
      section.hidden = Boolean(needle) && visible === 0;
      if (needle && visible) {
        if (!section.open) searchOpened.add(section); // user-opened stays user-owned
        section.open = true;
      } else if (!needle && searchOpened.has(section)) {
        section.open = false;
        searchOpened.delete(section);
      }
    });
  });
  refreshWowheadLinks();
}

function renderWorkflow() {
  workflowContainer.innerHTML = `
    <section class="panel-card workflow-panel full-width baseline-gear-panel" id="baseline-gear-panel"><div class="step-heading"><span class="num-badge num-badge-lg">2</span><div><h2>Baseline Gear · select candidates for ${escapeHtml(parsedData.char_name)}</h2><small>Grades are inferred from the export and refined with Wowhead. Toggle whole slots with Select all/none.</small></div></div><div id="gear-grid"></div></section>
    <section class="panel-card workflow-panel full-width" id="step-enhance"><div class="step-heading"><span class="num-badge num-badge-lg">3</span><div><h2>Select gems and enchantments</h2><small>Checked enhancements are included in generated variations; the ones you already wear are pre-checked as the baseline. You can also jump here from the chips in each gear slot above.</small></div></div><div id="enhancement-options" class="enhancement-options"></div></section>
    <section class="panel-card workflow-panel run-panel full-width" id="step-run"><div class="step-heading"><span class="num-badge num-badge-lg">4</span><div><h2>Run comparison</h2><small>Combinations update automatically as you change gear. Start the run from the bar at the bottom.</small></div></div><div id="run-progress" hidden><div class="progress-card" aria-live="polite"><div class="progress-head"><span class="progress-elapsed" id="run-elapsed">00:00</span><span class="progress-stage" id="run-stage"></span><span class="progress-eta" id="run-eta" hidden></span><button type="button" id="btn-stop" class="btn-danger">Stop run</button></div><div class="progress-track"><div class="progress-fill" id="run-progress-fill" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Simulation progress"></div></div><span class="progress-meta" id="run-progress-meta">Starting…</span></div></div><div id="run-result" hidden></div><div class="log-toolbar" id="log-toolbar" hidden><label class="log-follow"><input type="checkbox" id="log-follow" checked> Follow log</label><span class="char-count" id="log-lines">0 lines</span><button type="button" id="btn-log-download" class="btn-ghost">Download full log</button></div><pre id="simulation-log" class="simulation-log" role="log" aria-live="off" hidden></pre></section>
  `;
  renderGear();
  renderEnhancements();
  renderCharChip();
  document.getElementById('run-bar').hidden = false;
  // t_16e4f177 (leader ruling): with the gear list rendered, the skip link
  // must move focus past it to the run controls in one activation.
  const skipLink = document.querySelector('.skip-link');
  if (skipLink) {
    skipLink.href = '#btn-run';
    skipLink.textContent = 'Skip to run controls';
  }
  document.getElementById('btn-run').addEventListener('click', runSimulation);
  document.getElementById('fight-style').addEventListener('change', selectionChanged);
  document.getElementById('compare-mode').addEventListener('change', selectionChanged);
  document.getElementById('btn-stop').addEventListener('click', stopSimulation);
  document.getElementById('btn-log-download').addEventListener('click', downloadLog);
  wirePopover(document.getElementById('btn-review'),
    document.getElementById('review-popover'), renderReviewPopover);
  observeWorkflowSteps();
  updateSummary();
  void generateInput(true);
}

async function hydrateWowheadUpgrades(itemsBySlot) {
  try {
    // Items whose upgrade path the export itself already provided never need
    // (and must not be overwritten by) the Wowhead lookup.
    const lookupItems = {};
    for (const [slot, items] of Object.entries(itemsBySlot || {})) {
      const rest = (items || []).filter(item => !parsedData?.item_upgrades?.[item]);
      if (rest.length) lookupItems[slot] = rest;
    }
    const response = await apiFetch('api/wowhead-upgrades', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items_by_slot: lookupItems })
    });
    if (!response.ok) return;
    const data = await response.json();
    for (const items of Object.values(data.two_handed || {})) {
      for (const item of items) twoHandedItems.add(item);
    }
    for (const [slot, itemUpgrades] of Object.entries(data.gear_upgrades || {})) {
      for (const [item, upgrade] of Object.entries(itemUpgrades)) {
        if (parsedData?.item_upgrades?.[item]) continue;
        // Never clobber a grade the user already picked while this lookup
        // was in flight.
        if (gearUpgrades[slot]?.[item]?.user_selected) continue;
        (gearUpgrades[slot] ||= {})[item] = upgrade;
      }
    }
    renderGear();
    updateSummary();
  } catch (error) {
    console.warn('Could not refine item grades from Wowhead', error);
  }
}

/* TG3-C slot conflict (design contract t_784b91c7 §3.4): inline role="alert"
   line under each conflicting weapon card (card grows only while shown) plus
   the aggregate line in #workflow-status. The authoritative rejection is the
   server-side 400 from generate-simc, which generateInput() surfaces here too;
   this is the pre-submit hint mirroring it — we never auto-remove selections. */
const SLOT_LABELS = { main_hand: 'Main Hand', off_hand: 'Off Hand' };

function twoHandedConflict() {
  const main = selectedItems.main_hand || new Set();
  const off = selectedItems.off_hand || new Set();
  if (!main.size || !off.size) return null;
  for (const item of main) if (twoHandedItems.has(item)) return { slot: 'main_hand', other: 'off_hand' };
  for (const item of off) if (twoHandedItems.has(item)) return { slot: 'off_hand', other: 'main_hand' };
  return null;
}

function renderSlotConflict() {
  document.querySelectorAll('.gear-conflict').forEach(el => el.remove());
  const conflict = twoHandedConflict();
  if (!conflict) return;
  const mark = (slot, text) => {
    for (const card of document.querySelectorAll(`.slot-group[data-slot="${slot}"] .gear-card.is-selected`)) {
      if (slot === conflict.slot && !twoHandedItems.has(card.dataset.item || '')) continue;
      const line = document.createElement('p');
      line.className = 'gear-conflict';
      line.setAttribute('role', 'alert');
      line.textContent = text;
      card.appendChild(line);
    }
  };
  mark(conflict.slot, `Two-handed weapon — cannot be combined with ${SLOT_LABELS[conflict.other]}.`);
  mark(conflict.other, `Conflicts with the two-handed weapon in ${SLOT_LABELS[conflict.slot]}.`);
  const status = document.getElementById('workflow-status');
  if (status) status.textContent =
    `Slot conflict: ${SLOT_LABELS[conflict.slot]} and ${SLOT_LABELS[conflict.other]} cannot be equipped together — a two-handed weapon occupies both weapon slots. Deselect one of the two slots.`;
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
    fight_style: document.getElementById('fight-style')?.value || 'single_boss',
    mode: document.getElementById('compare-mode')?.value || 'single_swap',
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
    const response = await apiFetch('api/generate-simc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload())
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Generation failed');
    generatedInput = data;
    document.getElementById('combo-count').textContent = data.combinations.toLocaleString();
    // t_4485565b: 0 candidates is a valid baseline run, not a doomed job.
    status.textContent = data.combinations === 0
      ? 'Ready to run a baseline current-gear report. Select gear changes, gems, or enchants to compare candidates.'
      : `Ready to run ${data.combinations.toLocaleString()} candidate ${data.combinations === 1 ? 'combination' : 'combinations'}.`;
  } catch (error) {
    generatedInput = null;
    status.textContent = `Could not generate input: ${error.message}`;
  } finally {
    updateSummary();
  }
}

async function runSimulation() {
  // t_4485565b: generate even when the client-side estimate is 0 — a
  // 0-candidate input is a valid baseline current-gear run.
  if (!generatedInput) await generateInput();
  if (!generatedInput) return;
  const status = document.getElementById('workflow-status');
  const log = document.getElementById('simulation-log');
  status.textContent = 'Looking for an idle worker…';
  try {
    const response = await apiFetch(`api/run-simulation?input_id=${encodeURIComponent(generatedInput.input_id)}`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Simulation could not start');
    status.textContent = `Simulation ${data.task_id} is running on worker ${data.worker_id}.`;
    currentTaskId = data.task_id;
    log.hidden = false;
    log.textContent = '';
    document.getElementById('log-toolbar').hidden = false;
    startRunProgress();
    updateRailState();
    const events = new EventSource(`api/simulation/stream/${data.task_id}?worker_id=${encodeURIComponent(data.worker_id)}`);
    events.onmessage = async event => {
      const message = JSON.parse(event.data);
      if (message.type === 'log') {
        pushLogLines([message.text]);
        updateRunProgressMeta(message.text);
      }
      if (message.type === 'log_batch') {
        pushLogLines(message.lines);
      }
      if (message.type === 'log' || message.type === 'log_batch') {
        const linesEl = document.getElementById('log-lines');
        if (linesEl) linesEl.textContent = `${logLineCount.toLocaleString()} lines`;
      }
      if (message.type === 'done' || message.type === 'error') {
        stopRunProgress();
        document.getElementById('run-progress').hidden = true;
        if (message.type === 'done') simulationDone = true;
        updateRailState();
        if (message.type === 'done' && message.report_file && message.task_id) {
          await showRunResultCard(message);
        } else {
          showRunFailureCard(message);
        }
        events.close();
      }
    };
    events.onerror = () => { events.close(); stopRunProgress(); };
  } catch (error) {
    status.textContent = `Could not start simulation: ${error.message}`;
  }
}

// t_2ab8f3be: the run ends on a card the user acts on — the old code yanked
// the browser to the results page mid-view (auto-redirect removed).
async function showRunResultCard(message) {
  const status = document.getElementById('workflow-status');
  const slot = document.getElementById('run-result');
  const baseline = parsedData?.char_name || '';
  const resultsHref = `results?task_id=${encodeURIComponent(message.task_id)}&baseline=${encodeURIComponent(baseline)}`;
  let reportHref = '';
  try {
    // t_c968bf8d: durable reports live under /reports/<user_id>/<task_id>/,
    // which only the master can resolve — ask it for the URL.
    const urlResp = await apiFetch(`api/report-url?task_id=${encodeURIComponent(message.task_id)}`);
    if (urlResp.ok) {
      const urlData = await urlResp.json();
      if (urlData.url) reportHref = urlData.url;
    }
  } catch (e) { /* report link is best-effort */ }
  let bestLine = message.text || 'Run complete.';
  try {
    const resp = await apiFetch(`api/get-results?task_id=${encodeURIComponent(message.task_id)}`);
    if (resp.ok) {
      const results = ((await resp.json()).results || []).filter(r => r && r.dps > 0);
      const base = results.find(r => r.name === baseline);
      const candidates = results.filter(r => r.name !== baseline).sort((a, b) => b.dps - a.dps);
      if (base && candidates.length) {
        const delta = candidates[0].dps - base.dps;
        bestLine = `Best: ${delta >= 0 ? '+' : ''}${Math.round(delta).toLocaleString()} DPS \u00b7 ${candidates[0].name}`;
      }
    }
  } catch (e) { /* best-line is best-effort */ }
  status.textContent = 'Run complete.';
  if (!slot) return;
  slot.hidden = false;
  slot.innerHTML = `<div class="success-card"><span class="success-icon" aria-hidden="true">\u2713</span><div><h3>Done in ${escapeHtml(formatElapsed(Date.now() - runStartedAt))}</h3><p>${escapeHtml(bestLine)}</p><div class="success-actions"><a class="btn" href="${resultsHref}">Open results</a>${reportHref ? ` <a class="btn-ghost" href="${escapeHtml(reportHref)}" target="_blank">Open full report</a>` : ''}<button type="button" data-back-gear class="btn-ghost">Back to gear</button></div></div></div>`;
  slot.querySelector('[data-back-gear]').addEventListener('click', backToGear);
}

function showRunFailureCard(message) {
  const status = document.getElementById('workflow-status');
  const slot = document.getElementById('run-result');
  status.textContent = message.text || 'The simulation stopped unexpectedly.';
  status.classList.add('error');
  if (!slot) return;
  const tail = logLines.slice(-12).join('\n');
  slot.hidden = false;
  slot.innerHTML = `<div class="success-card is-failed"><span class="success-icon" aria-hidden="true">\u2715</span><div><h3>Run failed</h3><p>${escapeHtml(message.text || 'The simulation stopped unexpectedly \u2014 see the log below.')}</p>${tail ? `<pre class="success-log-tail">${escapeHtml(tail)}</pre>` : ''}<div class="success-actions"><button type="button" data-open-log class="btn-ghost">Open log</button><button type="button" data-back-gear class="btn-ghost">Back to gear</button></div></div></div>`;
  slot.querySelector('[data-open-log]').addEventListener('click', () => document.getElementById('simulation-log')?.scrollIntoView({ block: 'start' }));
  slot.querySelector('[data-back-gear]').addEventListener('click', backToGear);
}

function backToGear() {
  document.getElementById('step-gear')?.scrollIntoView({ block: 'start' });
}

async function applyParsedCharacter(data) {
  parsedData = data;
  if (Array.isArray(parsedData.warnings) && parsedData.warnings.length) {
    showParseWarning(parsedData.warnings);
  } else {
    clearParseWarning();
  }
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
}

btnParseAddon.addEventListener('click', async () => {
  const text = addonInput.value.trim();
  if (!text) return;
  btnParseAddon.disabled = true;
  btnParseAddon.textContent = 'Parsing…';
  clearParseError();
  try {
    const [parseResponse, configResponse] = await Promise.all([
      apiFetch('api/parse-addon', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ addon_text: text }) }),
      apiFetch('api/config')
    ]);
    if (!parseResponse.ok) {
      const detail = await parseResponse.json().catch(() => ({}));
      throw new Error(detail.detail || 'The addon export could not be parsed. Make sure you copied the full text from the /simc export window.');
    }
    appConfig = configResponse.ok ? await configResponse.json() : appConfig;
    await applyParsedCharacter(await parseResponse.json());
  } catch (error) {
    showParseError(`Could not parse the export: ${error.message}`);
  } finally {
    btnParseAddon.disabled = false;
    btnParseAddon.textContent = 'Parse character';
  }
});

/* ---------- Armory load (Step 7: no addon needed) ---------- */

const armoryInput = document.getElementById('armory-input');
const armoryRegion = document.getElementById('armory-region');
const armoryRealm = document.getElementById('armory-realm');
const btnArmoryLoad = document.getElementById('btn-armory-load');

/* ---------- Realm dropdown (static realms.json, EU/US grouped) ---------- */

// "region/slug" -> { region, slug, name }.  Realms like Kel'thuzad exist in
// BOTH regions with different ids, so the key carries the region and entries
// are never deduped by name.
const realmIndex = new Map();

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

loadRealms();

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

function updateArmoryState() {
  if (!armoryInput || !btnArmoryLoad) return;
  btnArmoryLoad.disabled = !armoryInput.value.trim();
}

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
    appConfig = configResponse.ok ? await configResponse.json() : appConfig;
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

document.getElementById('btn-new-export').addEventListener('click', () => {
  parsedData = null;
  generatedInput = null;
  simulationDone = false;
  workflowContainer.innerHTML = '';
  document.getElementById('run-bar').hidden = true;
  document.getElementById('char-chip').hidden = true;
  // t_16e4f177: no gear list and no run bar anymore — restore the plain skip link.
  const skipLink = document.querySelector('.skip-link');
  if (skipLink) {
    skipLink.href = '#main';
    skipLink.textContent = 'Skip to content';
  }
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
