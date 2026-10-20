// js/pages/results.js — results page entry (I-37): fetch with retry, chip
// batch pre-resolve, render. Ported from results.js by t_94a15fe3.
import { apiFetch } from '../core/api.js';
import {
  pickBaseline, changesFromBaseline, bestGearChanges,
} from '../results/model.js';
import { resolveChips } from '../results/chips.js';
import { renderResults } from '../results/table.js';
import { renderHeroExtras } from '../results/hero.js';

const query = new URLSearchParams(window.location.search);
const taskId = query.get('task_id');
const els = {
  subtitle: document.getElementById('results-subtitle'),
  baselineCard: document.getElementById('baseline-card'),
  resultList: document.getElementById('result-list'),
  baselineName: query.get('baseline'),
};

async function fetchResults(attempt = 0) {
  if (!taskId) {
    els.subtitle.textContent = 'No simulation task was provided.';
    return;
  }
  renderHeroExtras(taskId);
  try {
    const response = await apiFetch(`api/get-results?task_id=${encodeURIComponent(taskId)}`);
    const data = await response.json();
    if (response.ok && data.status === 'success' && data.results?.length) {
      const healthy = data.results.filter(result => result && Number(result.dps) > 0);
      const { baseline } = pickBaseline(healthy, els.baselineName);
      // A2 (MGE-2 §2): below-rank-1 diffs are described against BEST, and the
      // best-combination ids join the same batched chip resolve.
      const rankedAll = healthy.filter(result => result !== baseline)
        .sort((a, b) => b.dps - a.dps);
      const ranked = baseline
        ? rankedAll.filter(result => changesFromBaseline(result, baseline).length)
        : rankedAll;
      const topRow = ranked[0] || baseline;
      await resolveChips(ranked, topRow, topRow ? bestGearChanges(topRow, baseline) : []);
      return renderResults(data.results, data.mode, els);
    }
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    els.subtitle.textContent = data.message || 'The report could not be loaded.';
  } catch {
    if (attempt < 5) return setTimeout(() => fetchResults(attempt + 1), 1200);
    els.subtitle.textContent = 'The report could not be loaded.';
  }
}

fetchResults();
