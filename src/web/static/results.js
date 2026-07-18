const query = new URLSearchParams(window.location.search);
const taskId = query.get('task_id');
const baselineName = query.get('baseline');
const subtitle = document.getElementById('results-subtitle');
const baselineCard = document.getElementById('baseline-card');
const resultList = document.getElementById('result-list');

function escapeHtml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function itemId(item) {
  return String(item || '').match(/(?:^|,)id=(\d+)/)?.[1] || '';
}

function changesFromBaseline(candidate, baseline) {
  const changes = [];
  const slots = new Set([...Object.keys(baseline.gear || {}), ...Object.keys(candidate.gear || {})]);
  for (const slot of slots) {
    const before = itemId(baseline.gear?.[slot]);
    const after = itemId(candidate.gear?.[slot]);
    if (after && after !== before) changes.push(`${slot.replaceAll('_', ' ')} → item ${after}`);
  }
  return changes;
}

function renderResults(results) {
  const baseline = results.find(result => result.name === baselineName) || results[0];
  const ranked = results.filter(result => result !== baseline).sort((a, b) => b.dps - a.dps);
  baselineCard.hidden = false;
  baselineCard.innerHTML = `<div class="baseline-result"><span>Equipped baseline</span><strong>${baseline.dps.toLocaleString()} DPS</strong><small>${escapeHtml(baseline.name)}</small></div>`;
  subtitle.textContent = ranked.length
    ? `${ranked.length} alternatives ranked against your equipped gear.`
    : 'Only your equipped baseline was simulated.';

  if (!ranked.length) {
    resultList.innerHTML = '<section class="panel-card empty-results"><h2>No alternatives to rank</h2><p>Select another item, enchant, gem, grade, or socket before running a comparison.</p></section>';
    return;
  }
  resultList.innerHTML = ranked.map((result, index) => {
    const delta = result.dps - baseline.dps;
    const changes = changesFromBaseline(result, baseline);
    return `<article class="panel-card result-card ${index === 0 ? 'best-result' : ''}">
      <div class="result-rank">#${index + 1}${index === 0 ? ' · Best' : ''}</div>
      <div class="result-score"><strong>${result.dps.toLocaleString()}</strong><span>DPS</span></div>
      <div class="result-delta ${delta >= 0 ? 'positive' : 'negative'}">${delta >= 0 ? '+' : ''}${delta.toLocaleString()} vs equipped</div>
      <div class="result-changes"><b>Changes</b><p>${escapeHtml(changes.join(' · ') || 'No gear difference was parsed from the report.')}</p></div>
    </article>`;
  }).join('');
}

async function fetchResults(attempt = 0) {
  if (!taskId) {
    subtitle.textContent = 'No simulation task was provided.';
    return;
  }
  try {
    const response = await fetch(`/api/get-results?task_id=${encodeURIComponent(taskId)}`);
    const data = await response.json();
    if (response.ok && data.status === 'success' && data.results?.length) return renderResults(data.results);
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    subtitle.textContent = data.message || 'The report could not be loaded.';
  } catch {
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    subtitle.textContent = 'The report could not be loaded.';
  }
}

fetchResults();
