// Run history page (t_d34ced81): lists the signed-in user's stored runs and
// a per-run detail view (?run=<id>) with a working link to the stored report.
const historyQuery = new URLSearchParams(window.location.search);
const runId = historyQuery.get('run');
const titleEl = document.getElementById('history-title');
const subtitleEl = document.getElementById('history-subtitle');
const contentEl = document.getElementById('history-content');
const backEl = document.getElementById('history-back');

function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

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

function reportCell(run) {
  if (run.report_url) {
    return `<a class="history-report" href="${escapeHtml(run.report_url)}" target="_blank" rel="noopener">Open report</a>`;
  }
  if (run.status === 'failed') return '<span class="history-missing">no report</span>';
  return '<span class="history-missing" title="Old runs are pruned automatically">expired</span>';
}

function statusBadge(status) {
  const ok = status === 'success';
  return `<span class="history-status ${ok ? 'history-status-ok' : 'history-status-failed'}">${escapeHtml(status)}</span>`;
}

function renderList(runs) {
  subtitleEl.textContent = runs.length
    ? `${runs.length} stored run${runs.length === 1 ? '' : 's'}. Reports are kept for your 50 most recent runs.`
    : 'No runs recorded yet. Finish a simulation with an account to build your history.';
  if (!runs.length) {
    contentEl.innerHTML = '<section class="panel-card empty-results"><h2>Nothing here yet</h2><p>Run a comparison and it will show up here with its report link.</p></section>';
    return;
  }
  const rows = runs.map(run => `<tr class="history-row" data-run="${escapeHtml(run.run_id)}">
    <td>${escapeHtml(formatWhen(run.created_at))}</td>
    <td>${escapeHtml(characterLabel(run))}</td>
    <td>${escapeHtml(run.spec || '—')}</td>
    <td>${escapeHtml(run.fighting_style || '—')}</td>
    <td class="history-dps">${escapeHtml(formatDps(run.top_dps))}</td>
    <td>${statusBadge(run.status)}</td>
    <td>${reportCell(run)}</td>
  </tr>`).join('');
  contentEl.innerHTML = `<section class="panel-card full-width history-table-card">
    <table class="history-table">
      <thead><tr><th>When</th><th>Character</th><th>Spec</th><th>Fight</th><th>Top DPS</th><th>Status</th><th>Report</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </section>`;
  contentEl.querySelectorAll('.history-row').forEach(row => {
    row.addEventListener('click', () => {
      window.location.assign(`history?run=${encodeURIComponent(row.dataset.run)}`);
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
    <div class="history-detail-actions">${reportCell(run)}</div>
  </section>`;
}

async function load() {
  const url = runId ? `api/history/${encodeURIComponent(runId)}` : 'api/history?limit=50';
  try {
    const response = await fetch(url);
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
