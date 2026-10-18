// Results page (t_2ab8f3be redesign): failed sims are quarantined instead of
// ranking as "best", changes render as item chips, the full SimC report is one
// click from the hero, and the run id is visible + copyable.
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

function itemBonus(item) {
  const match = String(item || '').match(/(?:^|,)bonus=([\d/]+)/);
  return match ? match[1] : '';
}

// TG3-D2 baseline pick: prefer the actor named in ?baseline (the real
// character with equipped gear). When the report has no such run, fall back
// to the HIGHEST-DPS healthy actor — never the name-sorted first row — and
// let the caller label the card honestly (no baseline run => say so).
function pickBaseline(healthy) {
  const equipped = healthy.find(result => result.name === baselineName);
  if (equipped) return { baseline: equipped, isEquipped: true };
  if (!healthy.length) return { baseline: null, isEquipped: false };
  const top = healthy.reduce((best, r) => (Number(r.dps) > Number(best.dps) ? r : best));
  return { baseline: top, isEquipped: false };
}

function changesFromBaseline(candidate, baseline) {
  const changes = [];
  const slots = new Set([...Object.keys(baseline.gear || {}), ...Object.keys(candidate.gear || {})]);
  for (const slot of slots) {
    const before = itemId(baseline.gear?.[slot]);
    const after = itemId(candidate.gear?.[slot]);
    if (after && after !== before) {
      changes.push({ slot: slot.replaceAll('_', ' '), id: after, bonus: itemBonus(candidate.gear[slot]) });
    }
  }
  return changes;
}

// --- item chips: batch-resolve every changed item id (doc 4.4) ---
const chipInfo = new Map();

async function resolveChips(ranked, baseline) {
  const wanted = new Map();
  for (const result of ranked) {
    for (const change of changesFromBaseline(result, baseline)) {
      if (change.id && !wanted.has(change.id)) wanted.set(change.id, change.bonus);
    }
  }
  if (!wanted.size) return;
  const ids = [...wanted.keys()];
  const chunks = [];
  for (let i = 0; i < ids.length; i += 40) chunks.push(ids.slice(i, i + 40));
  await Promise.all(chunks.map(async (chunk) => {
    try {
      const response = await apiFetch('api/wowhead/tooltips/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          char_class: null,
          items: chunk.map(id => ({ item: Number(id), bonus: wanted.get(id) || null })),
        }),
      });
      if (!response.ok) return;
      const data = await response.json();
      for (const entry of data.results || []) {
        if (entry.ok) chipInfo.set(String(entry.item), entry);
      }
    } catch { /* chips fall back to bare ids */ }
  }));
}

function chipHtml(change) {
  const info = chipInfo.get(change.id);
  const bonusQuery = change.bonus ? `?bonus=${encodeURIComponent(change.bonus.replaceAll('/', ':'))}` : '';
  const href = `https://www.wowhead.com/item=${encodeURIComponent(change.id)}${bonusQuery}`;
  if (!info) {
    return `<span class="chip-pending">${escapeHtml(change.slot)} #${escapeHtml(change.id)}</span>`;
  }
  const color = info.quality_color ? ` style="color:${escapeHtml(info.quality_color)}"` : '';
  return `<a class="item-chip" href="${href}" target="_blank" rel="noopener" title="${escapeHtml(info.name)} (ilvl ${escapeHtml(info.ilvl ?? '?')})">` +
    `<img src="api/item-icon/${encodeURIComponent(change.id)}" alt="" loading="lazy">` +
    `<span${color}>${escapeHtml(info.name)}</span><span class="item-chip-slot">${escapeHtml(change.slot)}</span></a>`;
}

function deltaHtml(delta) {
  return `<span class="result-delta ${delta >= 0 ? 'positive' : 'negative'}">${delta >= 0 ? '+' : ''}${delta.toLocaleString()}</span>`;
}

function renderResults(results) {
  // Quarantine (doc 4.4): dps<=0 means the sim failed — never rank it, never
  // let it be the baseline.
  const healthy = results.filter(result => result && Number(result.dps) > 0);
  const failed = results.filter(result => !result || !(Number(result.dps) > 0));
  const { baseline, isEquipped } = pickBaseline(healthy);
  if (!baseline) {
    subtitle.textContent = 'The report could not be loaded.';
    return;
  }
  const rankedAll = healthy.filter(result => result !== baseline)
    .sort((a, b) => b.dps - a.dps)
    .map(result => ({ ...result, changes: changesFromBaseline(result, baseline) }));
  // Quarantine (doc D1): dps>0 but zero gear difference vs baseline is the
  // "No gear difference was parsed" marker — excluded, never ranked as a row.
  const noDiff = rankedAll.filter(result => !result.changes.length);
  const ranked = rankedAll.filter(result => result.changes.length);

  // Sidegrade band (D6 / ruling Q3, presentation only): ranked rows within
  // 2x the best candidate's reported error of it are statistical ties —
  // tint + badge only; rank order stays the raw engine order (§5.5). Do not
  // conflate this 2xerr display band with the culling K used server-side.
  const topRow = ranked[0];
  const band = topRow && typeof topRow.mean_error_pct === 'number'
    ? topRow.dps * (1 - 2 * topRow.mean_error_pct / 100)
    : null;
  const sidegrades = band === null ? 0 : ranked.filter((r, i) => i > 0 && r.dps >= band).length;

  subtitle.textContent = ranked.length
    ? `${ranked.length} alternatives ranked against ${isEquipped ? 'your equipped gear' : 'the top candidate'}.`
    : (isEquipped ? 'Only your equipped baseline was simulated.' : 'No equipped baseline run was found in the report.');
  if (sidegrades > 0) subtitle.textContent += ` ${sidegrades} sidegrades within 2× error of best.`;

  const quarantined = [
    ...failed.map(result => [result, 'failed to simulate']),
    ...noDiff.map(result => [result, 'no gear difference']),
  ];
  const quarantineHtml = quarantined.length
    ? `<details class="quarantine"><summary>${quarantined.length} run${quarantined.length === 1 ? '' : 's'} excluded from ranking</summary><ul>` +
      quarantined.map(([result, reason]) => `<li>${escapeHtml(result?.name || 'unnamed run')} — ${escapeHtml(result?.dps ?? '?')} DPS (${reason})</li>`).join('') +
      `</ul></details>`
    : '';

  baselineCard.hidden = false;
  baselineCard.innerHTML = `<div class="baseline-result"><span>${isEquipped ? 'Equipped baseline' : 'Best candidate (no baseline run)'}</span><strong>${baseline.dps.toLocaleString()} DPS</strong><small>${escapeHtml(baseline.name)}</small></div>`;

  if (!ranked.length) {
    resultList.innerHTML = `<section class="panel-card empty-results"><h2>No alternatives to rank</h2><p>Select another item, enchant, gem, grade, or socket before running a comparison.</p>${quarantineHtml}</section>`;
    return;
  }

  const top = ranked.slice(0, 3);
  const topCards = top.map((result, index) => {
    const delta = result.dps - baseline.dps;
    return `<article class="panel-card result-card ${index === 0 ? 'best-result' : ''}">
      <div class="result-rank">#${index + 1}${index === 0 ? ' · Best' : ''}</div>
      <div class="result-score"><strong>${result.dps.toLocaleString()}</strong><span>DPS</span></div>
      <div class="result-delta ${delta >= 0 ? 'positive' : 'negative'}">${delta >= 0 ? '+' : ''}${delta.toLocaleString()} vs equipped</div>
      <div class="result-changes"><b>Changes</b><p class="chip-row">${result.changes.map(chipHtml).join('')}</p></div>
    </article>`;
  }).join('');

  const tableRows = ranked.map((result, index) => {
    const delta = result.dps - baseline.dps;
    // Index 0 is the band's reference row — best itself is never a sidegrade.
    const tie = band !== null && index > 0 && result.dps >= band;
    const err = typeof result.mean_error_pct === 'number'
      ? ` <span class="result-err">± ${result.mean_error_pct}%</span>` : '';
    const vsBest = `${((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)}%`;
    return `<tr${tie ? ' class="is-sidegrade"' : ''}>
      <td class="results-num">${index + 1}</td>
      <td>${escapeHtml(result.name)}${tie ? '<span class="sidegrade-badge">≈ best (statistical tie)</span>' : ''}</td>
      <td class="results-num">${result.dps.toLocaleString()}${err}</td>
      <td class="results-num">${deltaHtml(delta)}</td>
      <td class="results-num">${vsBest}</td>
      <td class="results-changes">${result.changes.map(chipHtml).join('')}</td>
    </tr>`;
  }).join('');

  resultList.innerHTML = `${topCards}
    <section class="panel-card full-width results-table-card">
      <table class="results-table">
        <caption class="sr-only">Best combinations, ranked by DPS</caption>
        <thead><tr><th scope="col">&nbsp;</th><th scope="col">Candidate</th><th scope="col">DPS</th><th scope="col">Δ vs equipped</th><th scope="col">% vs best</th><th scope="col">Changes</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
      ${quarantineHtml}
    </section>`;
}

async function renderHeroExtras() {
  const hero = document.querySelector('.results-hero') || subtitle.parentElement;
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

async function fetchResults(attempt = 0) {
  if (!taskId) {
    subtitle.textContent = 'No simulation task was provided.';
    return;
  }
  renderHeroExtras();
  try {
    const response = await apiFetch(`api/get-results?task_id=${encodeURIComponent(taskId)}`);
    const data = await response.json();
    if (response.ok && data.status === 'success' && data.results?.length) {
      const healthy = data.results.filter(result => result && Number(result.dps) > 0);
      const baseline = pickBaseline(healthy).baseline;
      const ranked = healthy.filter(result => result !== baseline);
      await resolveChips(ranked, baseline);
      return renderResults(data.results);
    }
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    subtitle.textContent = data.message || 'The report could not be loaded.';
  } catch {
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    subtitle.textContent = 'The report could not be loaded.';
  }
}

fetchResults();
