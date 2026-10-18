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
    const baseItem = baseline.gear?.[slot] || '';
    const before = itemId(baseItem);
    const after = itemId(candidate.gear?.[slot]);
    if (after && after !== before) {
      // TG3-G gap 5: carry the replaced equipped item so the chip tooltip can
      // name it (peer pattern: candidate-shown-beside-equipped).
      changes.push({ slot: slot.replaceAll('_', ' '), id: after, bonus: itemBonus(candidate.gear[slot]), before, beforeBonus: itemBonus(baseItem) });
    }
  }
  return changes;
}

// TG3-G gap 4: human labels for engine copy names ("<char>_Combo_12" from
// cli/generate_input.py, "<char>_head_3" from generate-simc single_swap).
// The machine name stays in the row title tooltip; unknown names
// (user-embedded copies) fall back verbatim — never fabricate a label.
function candidateLabel(name) {
  const text = String(name || '');
  const combo = text.match(/^.*_Combo_(\d+)(?:,|$)/);
  if (combo) return `Combination #${combo[1]}`;
  const swap = text.match(/^(?:.+)_(head|neck|shoulder|shoulders|back|chest|wrist|wrists|hands|waist|legs|feet|finger1?|finger2|trinket1?|trinket2|main_hand|off_hand)_(\d+)$/);
  if (swap) {
    const slot = swap[1].replace(/_/g, ' ').replace(/(\d)$/, ' $1').replace(/^./, (c) => c.toUpperCase());
    return `${slot} swap`;
  }
  return text;
}

// --- item chips: batch-resolve every changed item id (doc 4.4) ---
const chipInfo = new Map();

async function resolveChips(ranked, baseline) {
  const wanted = new Map();
  for (const result of ranked) {
    for (const change of changesFromBaseline(result, baseline)) {
      if (change.id && !wanted.has(change.id)) wanted.set(change.id, change.bonus);
      // Gap 5: the replaced equipped items resolve through the SAME batch path
      // (their ids join one chunked request) — no new endpoint.
      if (change.before && !wanted.has(change.before)) wanted.set(change.before, change.beforeBonus);
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
  // Gap 5: replaces-context in the tooltip, resolved via the same batch path.
  const base = change.before ? chipInfo.get(change.before) : null;
  const replaces = base ? ` replaces ${base.name} (ilvl ${base.ilvl ?? '?'})` : '';
  const color = info.quality_color ? ` style="color:${escapeHtml(info.quality_color)}"` : '';
  return `<a class="item-chip" href="${href}" target="_blank" rel="noopener" title="${escapeHtml(`${info.name} (ilvl ${info.ilvl ?? '?'})${replaces}`)}">` +
    `<img src="api/item-icon/${encodeURIComponent(change.id)}" alt="" loading="lazy">` +
    `<span${color}>${escapeHtml(info.name)}</span><span class="item-chip-slot">${escapeHtml(change.slot)}</span></a>`;
}

function deltaHtml(delta) {
  return `<span class="result-delta ${delta >= 0 ? 'positive' : 'negative'}">${delta >= 0 ? '+' : ''}${delta.toLocaleString()}</span>`;
}

// Gap 1: compare-mode indicator. Keys mirror MODE_* in src/web/main.py;
// unknown/absent modes render no chip (honest absence, no guessing).
const MODE_LABELS = { single_swap: 'Single swap', combinations: 'Combinations' };
const MODE_HINTS = {
  single_swap: 'Each row changes exactly one item in your equipped gear — the delta is that item’s.',
  combinations: 'Each row simulates a full combination of changed items — the delta belongs to the whole combination.',
};

function renderResults(results, mode) {
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
  // Gap 1: compare-mode indicator (single source: run metadata from
  // /api/get-results). Runs generated before TG3-G have no stored mode —
  // the chip is honestly absent rather than guessed from candidate names.
  const modeChip = MODE_LABELS[mode]
    ? `<span class="mode-chip" title="${MODE_HINTS[mode]}">${MODE_LABELS[mode]}</span>`
    : '';
  baselineCard.innerHTML = `<div class="baseline-result"><span>${isEquipped ? 'Equipped baseline' : 'Best candidate (no baseline run)'}</span><strong>${baseline.dps.toLocaleString()} DPS</strong><small>${escapeHtml(baseline.name)}</small>${modeChip}</div>`;

  if (!ranked.length) {
    resultList.innerHTML = `<section class="panel-card empty-results"><h2>No alternatives to rank</h2><p>Select another item, enchant, gem, grade, or socket before running a comparison.</p>${quarantineHtml}</section>`;
    return;
  }

  // Gap 2 (t_54bad356): the old top-3 card block rendered rows 1-3 a second
  // time verbatim; the ranked table is now the single render layer.

  const tableRows = ranked.map((result, index) => {
    const delta = result.dps - baseline.dps;
    // Index 0 is the band's reference row — best itself is never a sidegrade.
    const tie = band !== null && index > 0 && result.dps >= band;
    const err = typeof result.mean_error_pct === 'number'
      ? ` <span class="result-err">± ${result.mean_error_pct}%</span>` : '';
    const vsBest = `${((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)}%`;
    // Gap 3: Δ vs equipped is the one primary number; DPS and % vs best are
    // demoted to the Δ-cell tooltip but stay in the DOM (sr-only spans) so
    // the table keeps its full semantics for assistive tech.
    const detail = `${result.dps.toLocaleString()} DPS${typeof result.mean_error_pct === 'number' ? ` ± ${result.mean_error_pct}%` : ''} · ${vsBest} vs best`;
    return `<tr${tie ? ' class="is-sidegrade"' : ''}>
      <td class="results-num">${index + 1}</td>
      <td><span class="candidate-label" title="${escapeHtml(result.name)}">${escapeHtml(candidateLabel(result.name))}</span>${tie ? '<span class="sidegrade-badge">≈ best (statistical tie)</span>' : ''}</td>
      <td class="results-num results-secondary"><span class="sr-only">${result.dps.toLocaleString()}${err}</span></td>
      <td class="results-num" title="${escapeHtml(detail)}">${deltaHtml(delta)}</td>
      <td class="results-num results-secondary"><span class="sr-only">${vsBest}</span></td>
      <td class="results-changes">${result.changes.map(chipHtml).join('')}</td>
    </tr>`;
  }).join('');

  resultList.innerHTML = `
    <section class="panel-card full-width results-table-card">
      <table class="results-table">
        <caption class="sr-only">Best candidates, ranked by DPS</caption>
        <thead><tr><th scope="col">&nbsp;</th><th scope="col">Candidate</th><th scope="col" class="results-secondary"><span class="sr-only">DPS</span></th><th scope="col">Δ vs equipped</th><th scope="col" class="results-secondary"><span class="sr-only">% vs best</span></th><th scope="col">Changes</th></tr></thead>
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
      return renderResults(data.results, data.mode);
    }
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    subtitle.textContent = data.message || 'The report could not be loaded.';
  } catch {
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    subtitle.textContent = 'The report could not be loaded.';
  }
}

fetchResults();
