// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: setup/runbar)

import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { normalizedEquippedItems } from '../core/items.js';

import { updateRailState } from '../core/rail.js';

import { renderSlotConflict } from './conflict.js';

import { syncEnhancementChips } from './enhancements.js';

import { upgradeStateText } from './gear-card.js';

import { generateInput } from './payload.js';

// t_5c33fefb: single write path so the clamped (2-line) status line's title
// always carries the full message; textContent stays full for aria-live.
export function setWorkflowStatus(text) {
  const s = document.getElementById('workflow-status');
  if (!s) return;
  s.textContent = text;
  s.title = text;
}
function selectedItemCount() {
  return Object.values(state.selectedItems).reduce((total, items) => total + items.size, 0);
}
function estimateCombinations() {
  let total = 1;
  for (const [slot, items] of Object.entries(state.selectedItems)) {
    const enchantCount = state.selectedEnchants[slot]?.size || 0;
    for (const item of items) {
      const equipped = normalizedEquippedItems(slot);
      const acceptsGem = item.includes('gem_id=') || state.extraSockets[slot];
      const gemCount = acceptsGem ? state.selectedGems.size + state.selectedMetaGems.size : 0;
      const hasVariation = !equipped.includes(item) || enchantCount > 0 || gemCount > 0 ||
        state.extraSockets[slot] || Boolean(state.gearUpgrades[slot]?.[item]?.user_selected);
      if (hasVariation) total += Math.max(1, enchantCount) * Math.max(1, gemCount);
    }
  }
  return total;
}
export function updateSummary() {
  // t_8bf63ec6: in combinations mode the server count is authoritative —
  // show '…' until the first generate-simc response replaces the estimate.
  const combosMode = document.getElementById('compare-mode')?.value === 'combinations';
  const server = combosMode && state.generatedInput?.mode === 'combinations' ? state.generatedInput : null;
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
  if (runButton) runButton.disabled = !(state.generatedInput || state.parsedData);
  updateRailState();
}
export function selectionChanged() {
  state.generatedInput = null;
  updateSummary();
  syncEnhancementChips();
  clearTimeout(state.generationTimer);
  // t_4485565b: regenerate even at an estimated 0 combinations so the status
  // line reflects the honest baseline-only state instead of a stale count.
  setWorkflowStatus('Updating comparison…');
  renderSlotConflict();
  state.generationTimer = setTimeout(() => generateInput(true), 250);
}
// Pre-run diff (doc 5): client-side summary only; the server combo count in
// the run bar stays authoritative.
export function renderReviewPopover() {
  const pop = document.getElementById('review-popover');
  if (!pop) return;
  const rows = [];
  for (const [slot, items] of Object.entries(state.selectedItems)) {
    for (const item of items) {
      const name = state.parsedData.item_names[item] || item;
      rows.push(`<tr><td>${escapeHtml(slot.replace('_', ' '))}</td><td>${escapeHtml(String(name).replace(/\s*\(\d+\)/, ''))}</td><td>${escapeHtml(upgradeStateText(slot, item))}</td></tr>`);
    }
  }
  pop.innerHTML = rows.length
    ? `<table class="diff-table"><thead><tr><th scope="col">Slot</th><th scope="col">Item</th><th scope="col">Grade</th></tr></thead><tbody>${rows.join('')}</tbody></table>`
    : '<small>No items selected yet.</small>';
}
