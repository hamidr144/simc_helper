// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: core/wowhead)

import { escapeHtml } from './dom.js';

// t_2ab8f3be: icon and name merged into ONE anchor (was 2 tab stops per card,
// 42+ per slot group). nameHtml must arrive pre-escaped.
export function createWowheadIconLink(itemId, bonusIds = '', nameHtml = '') {
  const safeId = encodeURIComponent(itemId || '0');
  const safeBonus = String(bonusIds || '').split('/').filter(value => /^\d+$/.test(value)).join(':');
  const bonusQuery = safeBonus ? `?bonus=${encodeURIComponent(safeBonus)}` : '';
  const tooltipData = safeBonus ? `bonus=${safeBonus}&iconsize=large` : 'iconsize=large';
  return `<a href="https://www.wowhead.com/item=${safeId}${bonusQuery}" class="item-icon-link wowhead-item-link" data-wowhead="${tooltipData}" data-wh-rename="false" target="_blank" rel="noopener"><img src="api/item-icon/${safeId}" alt="" loading="lazy" onerror="this.closest('.item-icon-link').classList.add('icon-missing')">${nameHtml}</a>`;
}
export function createEnhancementWowheadLink(enhancement, name) {
  const configuredUrl = typeof enhancement === 'object' ? enhancement.wowhead_url : '';
  const itemMatch = String(configuredUrl || '').match(/^https:\/\/(?:www\.)?wowhead\.com\/item=(\d+)/);
  const itemId = itemMatch?.[1];
  if (!itemId) return `<span>${escapeHtml(name)}</span>`;
  // t_76a0ceb9 directive 11: same tooltip pattern as the gear item icons
  // (createWowheadIconLink): icon anchor, data-wowhead, rich Wowhead tooltip.
  return `<a href="https://www.wowhead.com/item=${itemId}" class="enhancement-name-link wowhead-item-link" data-wowhead="iconsize=large" target="_blank" rel="noopener" aria-label="${escapeHtml(name)} on Wowhead"><img src="api/item-icon/${itemId}" alt="" loading="lazy" onerror="this.remove()"></a>`;
}
export function refreshWowheadLinks() {
  if (window.WH?.Tooltips?.refreshLinks) window.WH.Tooltips.refreshLinks();
}
