// js/setup/runbar.js — RED-3 status/run-line glue (contract §3 F-1). The rail
// stepper and the gear-card upgrade popover are deleted layers; the review
// popover keeps its Grade column via the inlined upgradeStateText below.
// Payload generation itself stays in payload.js (FROZEN); this module only
// owns the workflow-status band, the summary line and the review popover.
import { state } from '../core/state.js';

import { escapeHtml } from '../core/dom.js';

import { normalizedEquippedItems, isCraftedItem } from '../core/items.js';

import { season } from '../core/season.js';

import { targetUpgradeLevel } from './preview.js';

import { persistDraft } from './draft.js';

import { generateInput } from './payload.js';

// t_5c33fefb: single write path so the clamped (2-line) status line's title
// always carries the full message; textContent stays full for aria-live.
export function setWorkflowStatus(text) {
  const s = document.getElementById('workflow-status');
  if (!s) return;
  s.textContent = text;
  s.title = text;
}

/* RED-3: was gear-card.js's popover helper (module deleted with the tile era;
   decision D-2). Row-world grade string for the review popover. */
function upgradeStateText(slot, item) {
  const entry = state.gearUpgrades[slot]?.[item];
  const bits = [];
  if (entry?.user_selected) {
    const track = entry.track ? String(entry.track).replace(/_/g, ' ') : null;
    bits.push(track ? `${track} rank ${entry.rank || 1}` : `rank ${entry.rank || 1}`);
    const target = targetUpgradeLevel(slot, item);
    if (target) bits.push(`ilvl ${target}`);
  } else {
    const inferred = targetUpgradeLevel(slot, item);
    bits.push(inferred ? `upgrade \u21e5 ${inferred} (inferred)` : 'no upgrade');
  }
  if (state.voidforgedItems[slot]?.[item]) bits.push(season().ascension?.name || 'Ascendant');
  else if (isCraftedItem(item)) bits.push('Crafted');  // GSE-2: crafted has no track ladder
  return bits.join(' \u00b7 ');
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
  // t_9040b457 (t_ca74bb9c): no character loaded — the estimate's baseline
  // combo of 1 must not outlive Start over; the bar shows the empty state.
  const count = !state.parsedData ? 0 : (combosMode && !server ? null : (server ? server.combinations : estimateCombinations()));
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
}

export function selectionChanged() {
  state.generatedInput = null;
  updateSummary();
  clearTimeout(state.generationTimer);
  // t_4485565b: regenerate even at an estimated 0 combinations so the status
  // line reflects the honest baseline-only state instead of a stale count.
  setWorkflowStatus('Updating comparison…');
  // RED-3 §10: every selection mutation persists the per-character draft.
  persistDraft();
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

// t_9040b457 (t_6732b9de): main is the overflow scroller, and scroll-padding
// is per-scroll-container — html{scroll-padding-top} never reaches it. Keep
// main's scroll-padding synced with the sticky runbar's fluid height (it
// wraps on resize/status changes) so scrollIntoView/anchor targets land below
// the bar; the 12px floor clears the sticky #qj flush line at the widths
// where the bar is static and scrolls away.
// shortcut: node smoke harnesses and old browsers lack ResizeObserver/DOM —
// the CSS 12px floor is the graceful fallback; no re-polyfill needed until a
// supported browser lacks RO.
if (typeof document !== 'undefined' && typeof ResizeObserver !== 'undefined') {
  const mainScroller = document.querySelector('main');
  const stickyRunbar = mainScroller && mainScroller.querySelector('.runbar-top');
  if (mainScroller && stickyRunbar) {
    const syncScrollPadding = () => {
      const sticky = getComputedStyle(stickyRunbar).position === 'sticky';
      // measure the whole overlay stack (bar margin + fluid height) from
      // main's scrollport top; offsetHeight alone misses the sticky margin
      const stack = sticky
        ? stickyRunbar.getBoundingClientRect().bottom - mainScroller.getBoundingClientRect().top
        : 0;
      mainScroller.style.scrollPaddingTop = `${Math.ceil(stack) + 12}px`;
    };
    const ro = new ResizeObserver(syncScrollPadding);
    ro.observe(stickyRunbar);
    const qjStrip = document.querySelector('.qj');   // wraps -> main's top moves
    if (qjStrip) ro.observe(qjStrip);
    syncScrollPadding();
  }
}
