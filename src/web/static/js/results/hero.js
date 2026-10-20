// js/results/hero.js — run-id line and full-report link in the results hero
// (t_94a15fe3 port of results.js renderHeroExtras).
import { apiFetch } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';

export async function renderHeroExtras(taskId) {
  const hero = document.querySelector('.results-hero')
    || document.getElementById('results-subtitle').parentElement;
  const line = document.createElement('div');
  line.className = 'run-id-line';
  const short = String(taskId || '').slice(0, 8);
  line.innerHTML = `<span>Run <code>${escapeHtml(short)}</code></span>`;
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'run-copy';
  copy.setAttribute('aria-label', 'Copy full run id');
  copy.textContent = '⧉';
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(taskId); copy.textContent = '✓'; }
    catch { copy.textContent = '⧉'; }
  });
  line.append(copy);
  try {
    const response = await apiFetch(`api/report-url?task_id=${encodeURIComponent(taskId)}`);
    if (response.ok) {
      const data = await response.json();
      if (data.url) {
        const report = document.createElement('a');
        report.className = 'btn';
        report.href = data.url;
        report.target = '_blank';
        report.rel = 'noopener';
        report.textContent = 'Open full SimC report';
        line.append(report);
      }
    }
  } catch { /* report link is best-effort */ }
  // fetchResults retries re-run this; replace the previous line instead of
  // stacking duplicate run-id rows (NB1, review t_89761608).
  hero.querySelectorAll('.run-id-line').forEach((node) => node.remove());
  hero.append(line);
}
