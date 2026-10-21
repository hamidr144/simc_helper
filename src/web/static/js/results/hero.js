// js/results/hero.js — run identity facts for the results side rail
// (RED-3: the old .results-hero block is replaced by the v11 resaside;
// run id + copy + full-report link semantics unchanged from t_94a15fe3 port).
import { apiFetch } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';

export async function renderHeroExtras(taskId) {
  const kv = document.getElementById('side-run-kv');
  if (!kv) return;
  const short = String(taskId || '').slice(0, 8);
  // retries re-run this; rebuild instead of stacking (NB1, review t_89761608).
  kv.replaceChildren();
  const row = document.createElement('div');
  row.className = 'kv';
  const label = document.createElement('span');
  label.textContent = 'Run';
  const value = document.createElement('b');
  value.className = 'run num';
  value.textContent = short;
  value.title = String(taskId || '');
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'row-x';
  copy.setAttribute('aria-label', 'Copy full run id');
  copy.textContent = '⧉';
  copy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(taskId); copy.textContent = '✓'; }
    catch { copy.textContent = '⧉'; }
  });
  value.append(copy);
  row.append(label, value);
  kv.append(row);
  try {
    const response = await apiFetch(`api/report-url?task_id=${encodeURIComponent(taskId)}`);
    if (response.ok) {
      const data = await response.json();
      const link = document.getElementById('btn-open-report');
      if (data.url && link) {
        link.href = data.url;
        link.hidden = false;
      }
    }
  } catch { /* report link is best-effort */ }
}
