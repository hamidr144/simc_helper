// js/core/state.js — shared mutable state singleton (gui-rewrite §3.2)
import { exportRanksFor, inferMidnightUpgrade, isAlreadyVoidforgedItem, normalizedEquippedItems, PAPER_DOLL_SLOTS, parseItemParams } from './items.js';
export const state = {
  parsedData: null,
  appConfig: { enchantments: {}, gems: { meta: [], standard: [] } },
  selectedItems: {},
  selectedEnchants: {},
  selectedGems: new Set(),
  equippedEnchants: {},
  equippedGems: new Set(),
  gearUpgrades: {},
  voidforgedItems: {},
  extraSockets: {},
  slotSorts: {},
  statScores: {},
  slotLocks: {},            // RED-3 §3: client-only section locks; survives re-init, persists with draft
  addedItems: new Map(),
  twoHandedItems: new Set(),
  wowheadQualities: {},       // t_e906dc02: item string -> Wowhead quality number (conflict.js hydration)
  generatedInput: null,
  generationTimer: null,
  runTimer: null,
  runStartedAt: null,
  logLineCount: 0,
  simulationDone: false,
  logLines: [],
  logRenderQueued: false,
  currentTaskId: '',
  selectedMetaGems: new Set(),
  selectedAugurnium: new Set(),  // t_76a0ceb9: client-side only; payload.js is frozen
  gearTouchedByUser: new Map(),
};

// t_9040b457 (t_ca74bb9c): every per-character selection layer in one place.
// initializeSelections rebuilds on import; Start over must CLEAR, so the
// reset lives apart from the parse loops. slotLocks deliberately survives
// (RED-3 §3), drafts clear separately via clearDraftKeys.
export function resetCharacterState() {
  state.selectedItems = {};
  state.twoHandedItems = new Set();
  state.wowheadQualities = {};
  state.selectedEnchants = {};
  state.selectedGems = new Set();
  state.equippedEnchants = {};
  state.equippedGems = new Set();
  state.selectedMetaGems = new Set();
  state.selectedAugurnium = new Set();
  state.gearUpgrades = {};
  state.voidforgedItems = {};
  state.extraSockets = {};
  state.slotSorts = {};
  state.statScores = {};
  state.addedItems = new Map();
  state.gearTouchedByUser = new Map();
  state.generatedInput = null;
}

export function initializeSelections() {
  resetCharacterState();

  for (const [slot, items] of Object.entries(state.parsedData.items_by_slot)) {
    const equipped = new Set(normalizedEquippedItems(slot));
    state.selectedItems[slot] = new Set(items.filter(item => equipped.has(item)));
    state.gearUpgrades[slot] = {};
    state.voidforgedItems[slot] = {};
    for (const item of items) {
      const inferred = inferMidnightUpgrade(slot, item, state.parsedData.item_names[item]);
      if (inferred) state.gearUpgrades[slot][item] = inferred;
      const exportRanks = exportRanksFor(slot, item);
      if (exportRanks) {
        // Export-provided upgrade data wins: default to the item's current
        // rank with an absolute ilvl, bypassing the static ladder entirely.
        state.gearUpgrades[slot][item] = {
          ...(state.gearUpgrades[slot][item] || {}),
          source: 'export',
          rank: 0,
          item_level: exportRanks[0].level,
        };
      }
      state.voidforgedItems[slot][item] = isAlreadyVoidforgedItem(
        slot, item, state.parsedData.item_names[item]
      );
    }
  }
  // Armory payloads omit slots without an item; gear.js reads a Set for every
  // doll slot, so missing ones must still seed as empty (0/0 selected).
  for (const slot of PAPER_DOLL_SLOTS) {
    if (!(slot in state.selectedItems)) {
      state.selectedItems[slot] = new Set();
      state.gearUpgrades[slot] = {};
      state.voidforgedItems[slot] = {};
    }
  }
  for (const slot of Object.keys(state.appConfig.enchantments || {})) {
    state.equippedEnchants[slot] = new Set();
    const configuredIds = new Set((state.appConfig.enchantments[slot] || []).map(enchant =>
      String(typeof enchant === 'object' ? enchant.id : enchant)
    ));
    for (const item of normalizedEquippedItems(slot)) {
      const enchantId = parseItemParams(item).enchant_id;
      if (enchantId && configuredIds.has(String(enchantId))) {
        state.equippedEnchants[slot].add(String(enchantId));
      }
    }
    state.selectedEnchants[slot] = new Set(state.equippedEnchants[slot]);
  }

  const configuredGemIds = new Set((state.appConfig.gems?.standard || []).map(gem =>
    String(typeof gem === 'object' ? gem.id : gem)
  ));
  for (const item of Object.values(state.parsedData.equipped_gear || {})) {
    for (const gemId of String(parseItemParams(item).gem_id || '').split('/')) {
      if (configuredGemIds.has(gemId)) {
        state.equippedGems.add(gemId);
        state.selectedGems.add(gemId);
      }
    }
  }

  // MGE-2 §8.2: pre-check the equipped head's meta gem (single-select, <=1).
  const configuredMetaIds = new Set((state.appConfig.gems?.meta || []).map(gem =>
    String(typeof gem === 'object' ? gem.id : gem)
  ));
  const headMeta = (state.parsedData.equipped_gear || {}).head || '';
  for (const gemId of String(parseItemParams(headMeta).gem_id || '').split('/')) {
    if (configuredMetaIds.has(gemId) && !state.selectedMetaGems.size) {
      state.selectedMetaGems.add(gemId);
      state.equippedGems.add(gemId);
    }
  }
}
