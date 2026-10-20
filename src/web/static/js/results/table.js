// js/results/table.js — baseline card, A2 best-combination section and the
// ranked table (t_94a15fe3 port of results.js render layer).
import { escapeHtml } from '../core/dom.js';
import {
  pickBaseline, changesFromBaseline, candidateLabel, bestGearChanges,
} from './model.js';
import { chipHtml } from './chips.js';

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

export function renderResults(results, mode, els) {
  const { subtitle, baselineCard, resultList } = els;
  // Quarantine (doc 4.4): dps<=0 means the sim failed — never rank it, never
  // let it be the baseline.
  const healthy = results.filter(result => result && Number(result.dps) > 0);
  const failed = results.filter(result => !result || !(Number(result.dps) > 0));
  const { baseline, isEquipped } = pickBaseline(healthy, els.baselineName);
  if (!baseline) {
    subtitle.textContent = 'The report could not be loaded.';
    return;
  }
  const rankedAll = healthy.filter(result => result !== baseline)
    .sort((a, b) => b.dps - a.dps);
  // Quarantine (doc D1): dps>0 but zero gear difference vs baseline is the
  // "No gear difference was parsed" marker — excluded, never ranked as a row.
  const noDiff = rankedAll.filter(result => !changesFromBaseline(result, baseline).length);
  const rankedRows = rankedAll.filter(result => changesFromBaseline(result, baseline).length);
  const topRow = rankedRows[0];
  // A2 (MGE-2 §2): every ranked row is kept, best included (rank 1, empty
  // changes cell); rows below best are described ONLY by their diff vs best.
  const ranked = rankedRows.map((result, index) => ({
    ...result,
    changes: index === 0 ? [] : changesFromBaseline(result, topRow),
  }));

  // Sidegrade band (D6 / ruling Q3, presentation only): ranked rows within
  // 2x the best candidate's reported error of it are statistical ties —
  // tint + badge only; rank order stays the raw engine order (§5.5). Do not
  // conflate this 2xerr display band with the culling K used server-side.
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

  // A2 (MGE-2 §2): the best combination first, slot-by-slot with named chips.
  const bestCombination = `<section id="best-combination" class="panel-card full-width"><h2>Best combination</h2><div class="best-combination-chips">${
    bestGearChanges(topRow, baseline).map(chipHtml).join('')
  }</div></section>`;

  // Gap 2 (t_54bad356): the old top-3 card block rendered rows 1-3 a second
  // time verbatim; the ranked table is now the single render layer.
  const tableRows = ranked.map((result, index) => {
    const delta = result.dps - baseline.dps;
    // Index 0 is the band's reference row — best itself is never a sidegrade.
    const tie = band !== null && index > 0 && result.dps >= band;
    const err = typeof result.mean_error_pct === 'number'
      ? ` <span class="result-err">± ${result.mean_error_pct}%</span>` : '';
    const vsBest = `${((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)}%`;
    // Gap 3: Δ vs equipped is the one primary number; DPS stays demoted to
    // the sr-only cell (A2 makes % vs best VISIBLE in its existing column).
    const detail = `${result.dps.toLocaleString()} DPS${typeof result.mean_error_pct === 'number' ? ` ± ${result.mean_error_pct}%` : ''} · ${vsBest} vs best`;
    return `<tr${tie ? ' class="is-sidegrade"' : ''}>
      <td class="results-num">${index + 1}</td>
      <td><span class="candidate-label" title="${escapeHtml(result.name)}">${escapeHtml(candidateLabel(result.name))}</span>${tie ? '<span class="sidegrade-badge">≈ best (statistical tie)</span>' : ''}</td>
      <td class="results-num results-secondary"><span class="sr-only">${result.dps.toLocaleString()}${err}</span></td>
      <td class="results-num" title="${escapeHtml(detail)}">${deltaHtml(delta)}</td>
      <td class="results-num results-secondary">${vsBest}</td>
      <td class="results-changes">${result.changes.map(chipHtml).join('')}</td>
    </tr>`;
  }).join('');

  resultList.innerHTML = `
    ${bestCombination}
    <section class="panel-card full-width results-table-card">
      <table class="results-table">
        <caption class="sr-only">Best candidates, ranked by DPS</caption>
        <thead><tr><th scope="col">&nbsp;</th><th scope="col">Candidate</th><th scope="col" class="results-secondary"><span class="sr-only">DPS</span></th><th scope="col">Δ vs equipped</th><th scope="col" class="results-secondary">% vs best</th><th scope="col">Changes</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
      ${quarantineHtml}
    </section>`;
}
