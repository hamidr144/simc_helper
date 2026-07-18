/** SimC Helper five-step workflow. */

const MIDNIGHT_UPGRADE_TRACKS = {
  adventurer: [220, 224, 227, 230, 233, 237],
  veteran: [233, 237, 240, 243, 246, 250],
  champion: [246, 250, 253, 256, 259, 263],
  hero: [259, 263, 266, 269, 272, 276],
  myth: [272, 276, 279, 282, 285, 289]
};
const VOIDFORGE_FINAL_ITEM_LEVELS = [285, 298];
const VOIDFORGE_BONUS_IDS = ['13653', '13654'];

let parsedData = null;
let appConfig = { enchantments: {}, gems: { meta: [], standard: [] } };
let selectedItems = {};
let selectedEnchants = {};
let selectedGems = new Set();
let gearUpgrades = {};
let voidforgedItems = {};
let extraSockets = {};
let generatedInput = null;

const addonInput = document.getElementById('addon-input');
const btnParseAddon = document.getElementById('btn-parse-addon');
const workflowContainer = document.getElementById('gear-workspace-container');

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
  return `<a href="https://www.wowhead.com/item=${safeId}${bonusQuery}" class="item-icon-link wowhead-item-link" data-wowhead="${tooltipData}" data-wh-rename="false" target="_blank"><img src="/api/item-icon/${safeId}" alt="" loading="lazy"></a>`;
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
  return ['main_hand', 'off_hand', 'trinket'].includes(slot);
}

function hasVoidforgeBonus(item) {
  const bonuses = (parseItemParams(item).bonus_id || '').split('/');
  return bonuses.some(bonus => VOIDFORGE_BONUS_IDS.includes(bonus));
}

function itemLevelFromLabel(label) {
  const match = String(label || '').match(/\((\d+)\)/);
  return match ? Number(match[1]) : null;
}

function inferMidnightUpgrade(slot, item, label) {
  if (isCraftedItem(item)) return null;
  let level = Number(parseItemParams(item).ilevel) || itemLevelFromLabel(label);
  if (!level) return null;
  if (isVoidforgeEligibleSlot(slot) && hasVoidforgeBonus(item)) level -= 9;
  for (const [track, levels] of Object.entries(MIDNIGHT_UPGRADE_TRACKS)) {
    const rank = levels.indexOf(level) + 1;
    if (rank > 0) return { track, rank, item_level: level };
  }
  return null;
}

function isAlreadyVoidforgedItem(slot, item, label = '') {
  return isVoidforgeEligibleSlot(slot) && (
    hasVoidforgeBonus(item) || String(label).toLowerCase().includes('voidforged')
  );
}

function initializeSelections() {
  selectedItems = {};
  selectedEnchants = {};
  selectedGems = new Set();
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
  }
}

function selectedItemCount() {
  return Object.values(selectedItems).reduce((total, items) => total + items.size, 0);
}

function estimateCombinations() {
  let total = 0;
  for (const [slot, items] of Object.entries(selectedItems)) {
    const enchantCount = selectedEnchants[slot]?.size || 0;
    for (const item of items) {
      const acceptsGem = item.includes('gem_id=') || extraSockets[slot];
      const gemCount = acceptsGem ? selectedGems.size : 0;
      total += Math.max(1, enchantCount) * Math.max(1, gemCount);
    }
  }
  return total;
}

function updateSummary() {
  const count = estimateCombinations();
  const countEl = document.getElementById('combo-count');
  const itemCountEl = document.getElementById('selected-item-count');
  const generateButton = document.getElementById('btn-generate');
  const runButton = document.getElementById('btn-run');
  if (countEl) countEl.textContent = count.toLocaleString();
  if (itemCountEl) itemCountEl.textContent = selectedItemCount().toLocaleString();
  if (generateButton) generateButton.disabled = count === 0;
  if (runButton) runButton.disabled = !generatedInput;
}

function renderTrackControls(slot, item) {
  if (isCraftedItem(item)) return '<span class="crafted-badge">Crafted · no grade</span>';
  const upgrade = gearUpgrades[slot]?.[item] || {};
  const trackOptions = ['none', ...Object.keys(MIDNIGHT_UPGRADE_TRACKS)]
    .map(track => `<option value="${track}" ${upgrade.track === track ? 'selected' : ''}>${track === 'none' ? 'No grade' : track[0].toUpperCase() + track.slice(1)}</option>`)
    .join('');
  const levels = MIDNIGHT_UPGRADE_TRACKS[upgrade.track] || [];
  const rankOptions = levels.map((level, index) =>
    `<option value="${index + 1}" ${upgrade.rank === index + 1 ? 'selected' : ''}>Rank ${index + 1} · ${level}</option>`
  ).join('');
  return `<select class="gear-track-select" aria-label="Track">${trackOptions}</select><select class="gear-rank-select" aria-label="Rank" ${levels.length ? '' : 'disabled'}>${rankOptions}</select>`;
}

function renderGear() {
  const grid = document.getElementById('gear-grid');
  if (!grid) return;
  grid.innerHTML = '';
  for (const [slot, items] of Object.entries(parsedData.items_by_slot)) {
    const group = document.createElement('section');
    group.className = 'slot-group';
    group.innerHTML = `<h3>${escapeHtml(slot.replace('_', ' '))}</h3><div class="slot-items"></div>`;
    const itemGrid = group.querySelector('.slot-items');
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
        ${isVoidforgeEligibleSlot(slot) ? `<label class="voidforge-field-container"><input type="checkbox" class="voidforge-input" ${voidforgedItems[slot][item] ? 'checked' : ''}> Ascendant Voidforged +9</label>` : ''}
      `;

      card.querySelector('.item-select-input').addEventListener('change', event => {
        if (event.target.checked) selectedItems[slot].add(item);
        else selectedItems[slot].delete(item);
        card.classList.toggle('is-selected', event.target.checked);
        generatedInput = null;
        updateSummary();
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
            rankSelect.innerHTML = MIDNIGHT_UPGRADE_TRACKS[track].map((level, index) =>
              `<option value="${index + 1}">Rank ${index + 1} · ${level}</option>`
            ).join('');
            rankSelect.disabled = false;
          }
          generatedInput = null;
          updateSummary();
        });
        rankSelect.addEventListener('change', () => {
          if (gearUpgrades[slot][item]) gearUpgrades[slot][item].rank = Number(rankSelect.value);
          generatedInput = null;
          updateSummary();
        });
      }

      const voidforgeInput = card.querySelector('.voidforge-input');
      if (voidforgeInput) {
        voidforgeInput.addEventListener('change', event => {
          voidforgedItems[slot][item] = event.target.checked;
          event.currentTarget.closest('.voidforge-field-container')?.classList.toggle('is-active', event.target.checked);
          generatedInput = null;
          updateSummary();
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
        generatedInput = null;
        updateSummary();
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
      label.querySelector('input').addEventListener('change', event => {
        if (event.target.checked) selectedEnchants[slot].add(id);
        else selectedEnchants[slot].delete(id);
        generatedInput = null;
        updateSummary();
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
      label.querySelector('input').addEventListener('change', event => {
        if (event.target.checked) selectedGems.add(id);
        else selectedGems.delete(id);
        generatedInput = null;
        updateSummary();
      });
      group.appendChild(label);
    }
    container.appendChild(group);
  }
  refreshWowheadLinks();
}

function renderWorkflow() {
  workflowContainer.innerHTML = `
    <section class="panel-card workflow-panel full-width" id="baseline-gear-panel"><div class="step-heading"><span>2</span><div><h2>Baseline Gear · select candidates for ${escapeHtml(parsedData.char_name)}</h2><small>Grades are inferred from the export and refined with Wowhead.</small></div></div><div id="gear-grid"></div></section>
    <section class="panel-card workflow-panel full-width"><div class="step-heading"><span>3</span><div><h2>Select gems and enchantments</h2><small>Only checked enhancements are included in generated variations.</small></div></div><div id="enhancement-options" class="enhancement-options"></div></section>
    <section class="panel-card workflow-panel run-panel full-width"><div class="step-heading"><span>4</span><div><h2>Generate and run</h2><small>The count updates as selections change.</small></div></div><div class="combo-summary"><strong id="combo-count">0</strong><span>combinations from <b id="selected-item-count">0</b> selected items</span></div><div class="run-actions"><button id="btn-generate">Generate SimC input</button><button id="btn-run" disabled>Run simulation</button></div><div id="workflow-status" class="workflow-status" aria-live="polite"></div><pre id="simulation-log" class="simulation-log" hidden></pre></section>
  `;
  renderGear();
  renderEnhancements();
  document.getElementById('btn-generate').addEventListener('click', generateInput);
  document.getElementById('btn-run').addEventListener('click', runSimulation);
  updateSummary();
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
    extra_sockets: extraSockets
  };
}

async function generateInput() {
  const button = document.getElementById('btn-generate');
  const status = document.getElementById('workflow-status');
  button.disabled = true;
  status.textContent = 'Generating SimulationCraft input…';
  try {
    const response = await fetch('/api/generate-simc', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildPayload())
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Generation failed');
    generatedInput = data;
    document.getElementById('combo-count').textContent = data.combinations.toLocaleString();
    status.innerHTML = `Generated <a href="${escapeHtml(data.input_url)}" target="_blank">${escapeHtml(data.input_id)}.simc</a> with ${data.combinations.toLocaleString()} combinations.`;
  } catch (error) {
    generatedInput = null;
    status.textContent = `Could not generate input: ${error.message}`;
  } finally {
    updateSummary();
  }
}

async function runSimulation() {
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
    const events = new EventSource(`/api/simulation/stream/${data.task_id}?worker_id=${encodeURIComponent(data.worker_id)}`);
    events.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === 'log') log.textContent += `${message.text}\n`;
      if (message.type === 'log_batch') log.textContent += `${message.lines.join('\n')}\n`;
      log.scrollTop = log.scrollHeight;
      if (message.type === 'done' || message.type === 'error') {
        status.textContent = message.text;
        events.close();
      }
    };
  } catch (error) {
    status.textContent = `Could not start simulation: ${error.message}`;
  }
}

btnParseAddon.addEventListener('click', async () => {
  const text = addonInput.value.trim();
  if (!text) return;
  btnParseAddon.disabled = true;
  btnParseAddon.textContent = 'Parsing…';
  try {
    const [parseResponse, configResponse] = await Promise.all([
      fetch('/api/parse-addon', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ addon_text: text }) }),
      fetch('/api/config')
    ]);
    if (!parseResponse.ok) throw new Error('The addon export could not be parsed');
    parsedData = await parseResponse.json();
    appConfig = configResponse.ok ? await configResponse.json() : appConfig;
    initializeSelections();
    renderWorkflow();
    hydrateWowheadUpgrades(parsedData.items_by_slot);
  } catch (error) {
    workflowContainer.innerHTML = `<div class="panel-card workflow-status error">${escapeHtml(error.message)}</div>`;
  } finally {
    btnParseAddon.disabled = false;
    btnParseAddon.textContent = 'Parse character';
  }
});

// Report helpers retained for the result views.
function gearSummary(item) {
  return `<strong>${escapeHtml(item.slot)}:</strong> ${item.itemLink}`;
}
