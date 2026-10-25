// js/pages/history.js — run history page (t_d34ced81): lists the signed-in
// user's stored runs and a per-run detail view (?run=<id>).
import { apiFetch } from '../core/api.js';
import { escapeHtml } from '../core/dom.js';
import { wireTheme } from '../core/theme.js';
import { fetchVersion } from '../core/version.js';

wireTheme(document.querySelector('.pal .seg'));
fetchVersion();

wireTheme(document.querySelector('.pal .seg'));


const historyQuery = new URLSearchParams(window.location.search);
const runId = historyQuery.get('run');
const titleEl = document.getElementById('history-title');
const subtitleEl = document.getElementById('history-subtitle');
const contentEl = document.getElementById('history-content');
const backEl = document.getElementById('history-back');

function formatWhen(epoch) {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function formatDps(value) {
  return value == null ? '—' : Number(value).toLocaleString();
}

function characterLabel(run) {
  const name = run.char_name || 'Unknown character';
  const realm = run.realm_slug ? `${run.realm_slug}${run.region ? ` (${run.region})` : ''}` : '';
  return realm ? `${name} · ${realm}` : name;
}

function resultsCell(run) {
  if (run.report_url) {
    const taskId = String(run.report_url).split('/').slice(-2, -1)[0] || '';
    return `<a class="history-results" href="results?task_id=${encodeURIComponent(taskId)}">View results</a>`;
  }
  if (run.status === 'failed' || run.status === 'stopped') return '<span class="history-missing">no results</span>';
  return '<span class="history-missing" title="Old runs are pruned automatically">expired</span>';
}

function statusBadge(status) {
  const ok = status === 'success';
  return `<span class="history-status ${ok ? 'history-status-ok' : 'history-status-failed'}">${escapeHtml(status)}</span>`;
}

function renderList(runs) {
  subtitleEl.textContent = runs.length
    ? `${runs.length} stored run${runs.length === 1 ? '' : 's'}. Showing your 50 most recent runs.`
    : 'No runs recorded yet. Finish a simulation with an account to build your history.';
  if (!runs.length) {
    contentEl.innerHTML = '<section class="panel-card empty-results"><h2>Nothing here yet</h2><p>Run a comparison and it will show up here with its results.</p></section>';
    return;
  }
  const rows = runs.map(run => `<tr class="history-row" data-run="${escapeHtml(run.run_id)}" data-search="${escapeHtml(`${characterLabel(run)} ${run.spec || ''}`.toLowerCase())}">
    <td data-label="When"><a class="history-run-link" href="history?run=${encodeURIComponent(run.run_id)}">${escapeHtml(formatWhen(run.created_at))}</a></td>
    <td data-label="Character">${escapeHtml(characterLabel(run))}</td>
    <td data-label="Spec">${escapeHtml(run.spec || '—')}</td>
    <td data-label="Fight">${escapeHtml(run.fighting_style || '—')}</td>
    <td data-label="Top DPS" class="history-dps">${escapeHtml(formatDps(run.top_dps))}</td>
    <td data-label="Status">${statusBadge(run.status)}</td>
    <td data-label="Results">${resultsCell(run)}</td>
    <td data-label="Run"><span class="history-run-id">${escapeHtml(String(run.run_id).slice(0, 8))}</span> <button type="button" class="run-copy" data-copy="${escapeHtml(run.run_id)}" aria-label="Copy full run id">⧉</button></td>
  </tr>`).join('');
  contentEl.innerHTML = `<section class="panel-card full-width history-table-card">
    <label class="sr-only" for="history-filter">Filter runs by character or spec</label>
    <input id="history-filter" class="history-filter" type="search" placeholder="Filter runs…" autocomplete="off">
    <table class="history-table">
      <caption class="sr-only">Your simulation runs, newest first</caption>
      <thead><tr><th scope="col">When</th><th scope="col">Character</th><th scope="col">Spec</th><th scope="col">Fight</th><th scope="col">Top DPS</th><th scope="col">Status</th><th scope="col">Results</th><th scope="col">Run</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </section>`;
  // Row click still opens the run; the date-cell anchor covers keyboard/
  // middle-click/new-tab (a tr is not focusable).
  contentEl.querySelectorAll('.history-row').forEach(row => {
    row.addEventListener('click', event => {
      if (event.target.closest('a, button')) return;
      window.location.assign(`history?run=${encodeURIComponent(row.dataset.run)}`);
    });
  });
  contentEl.querySelectorAll('.run-copy').forEach(button => {
    button.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(button.dataset.copy); button.textContent = '✓'; }
      catch { button.textContent = '⧉'; }
    });
  });
  const filter = document.getElementById('history-filter');
  filter.addEventListener('input', () => {
    const needle = filter.value.trim().toLowerCase();
    contentEl.querySelectorAll('.history-row').forEach(row => {
      row.hidden = Boolean(needle) && !row.dataset.search.includes(needle);
    });
  });
}

function renderDetail(run) {
  titleEl.textContent = run.char_name || 'Simulation run';
  subtitleEl.textContent = formatWhen(run.created_at);
  backEl.hidden = false;
  const fields = [
    ['Character', characterLabel(run)],
    ['Spec', run.spec || '—'],
    ['Fighting style', run.fighting_style || '—'],
    ['Source', run.source || '—'],
    ['Top DPS', formatDps(run.top_dps)],
    ['Status', null],
    ['Run ID', run.run_id],
  ];
  const rows = fields.map(([label, value]) => `<div class="history-field"><span>${escapeHtml(label)}</span><strong>${
    label === 'Status' ? statusBadge(run.status) : escapeHtml(value)
  }</strong></div>`).join('');
  contentEl.innerHTML = `<section class="panel-card full-width history-detail">
    <div class="history-fields">${rows}</div>
    <div class="history-detail-actions">${resultsCell(run)}</div>
  </section>`;
}

async function load() {
  const url = runId ? `api/history/${encodeURIComponent(runId)}` : 'api/history?limit=50';
  try {
    const response = await apiFetch(url);
    if (response.status === 401) {
      subtitleEl.innerHTML = '<a href="login">Log in</a> to see your run history.';
      contentEl.innerHTML = '';
      return;
    }
    if (response.status === 404) {
      titleEl.textContent = 'Run not found';
      subtitleEl.textContent = 'This run does not exist or belongs to another account.';
      backEl.hidden = false;
      contentEl.innerHTML = '';
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (runId) renderDetail(data.run);
    else renderList(data.runs);
  } catch (error) {
    subtitleEl.textContent = 'Could not load your history — try again in a moment.';
  }
}

load();
