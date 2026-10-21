// js/results/table.js — RED-3 v11 render layer for the results page.
// Data semantics are the t_94a15fe3 port's verbatim (baseline pick, A2
// best-combination, quarantine doc 4.4, sidegrade band D6/Q3, mode chip
// Gap 1); only the markup changed to the v11 registers (results.css):
// verdict band, per-slot recommendations, best-set, combination register,
// ranked .dt table, side rails, and the §10 apply-back queue.
import { escapeHtml } from '../core/dom.js';
import {
  pickBaseline, changesFromBaseline, candidateLabel, bestGearChanges,
} from './model.js';
import { chipHtml, infoFor, titleFor } from './chips.js';
import { fmt, toast } from '../core/ui.js';
import { writeApply } from '../setup/draft.js';

// Gap 1: compare-mode indicator. Keys mirror MODE_* in src/web/main.py;
// unknown/absent modes render no chip (honest absence, no guessing).
const MODE_LABELS = { single_swap: 'Single swap', combinations: 'Combinations' };
const MODE_HINTS = {
  single_swap: 'Each row changes exactly one item in your equipped gear — the delta is that item’s.',
  combinations: 'Each row simulates a full combination of changed items — the delta belongs to the whole combination.',
};

// model.js derives display slots from raw gear keys via replaceAll('_',' ');
// this is its exact inverse. shortcut: relies on that derivation; upgrade to
// carrying the raw key on the change object if new key shapes appear.
const rawSlot = slot => slot.replaceAll(' ', '_');

function deltaPill(delta, { pct = null, title = '' } = {}) {
  const dir = delta > 0 ? 'up' : delta < 0 ? 'dn' : 'zero';
  const text = pct != null
    ? `${pct > 0 ? '+' : ''}${(pct * 100).toFixed(1)}%`
    : `${delta > 0 ? '+' : delta < 0 ? '−' : ''}${fmt(Math.abs(delta))}`;
  return `<span class="d ${dir}"${title ? ` title="${escapeHtml(title)}"` : ''}>${text}</span>`;
}


function iconSpan(id, fallbackName) {
  return `<span class="ic"><img src="api/item-icon/${encodeURIComponent(id)}" alt="" loading="lazy" onerror="this.remove()">${escapeHtml((fallbackName || String(id)).slice(0, 2).toUpperCase())}</span>`;
}

function replacesText(change) {
  const base = change.before ? infoFor(change.before) : null;
  return base ? `replaces ${base.name}` : '';
}

/* §10 apply-back: write the chosen changes as a payload-shaped apply queue
   (report rows only carry gear, so enchants/gems are honestly absent) and
   navigate home. writeApply lives in draft.js; payload.js stays FROZEN. */
function applyAndGo(selectedItems, taskId, charName) {
  writeApply({ char_name: charName, selected_items: selectedItems }, taskId);
  toast('Applied — opening the gear page…');
  setTimeout(() => { window.location.href = './'; }, 450);
}

function gearStringFor(row, change) {
  return row.gear?.[rawSlot(change.slot)] || `id=${change.id}`;
}

function selectedItemMap(row, baseline) {
  const map = {};
  for (const change of changesFromBaseline(row, baseline)) {
    (map[rawSlot(change.slot)] ||= []).push(gearStringFor(row, change));
  }
  return map;
}

export function renderResults(results, mode, els) {
  const { subtitle, taskId, baselineName } = els;
  const slots = {
    verdict: document.getElementById('verdict-slot'),
    recos: document.getElementById('recos-slot'),
    set: document.getElementById('set-slot'),
    combos: document.getElementById('combos-slot'),
    table: document.getElementById('table-slot'),
    quarantine: document.getElementById('side-quarantine'),
    modeNote: document.getElementById('side-mode-note'),
    runKv: document.getElementById('side-run-kv'),
  };
  // Quarantine (doc 4.4): dps<=0 means the sim failed — never rank it, never
  // let it be the baseline.
  const healthy = results.filter(result => result && Number(result.dps) > 0);
  const failed = results.filter(result => !result || !(Number(result.dps) > 0));
  const { baseline, isEquipped } = pickBaseline(healthy, baselineName);
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

  const baseLabel = isEquipped ? 'equipped gear' : 'top candidate';
  const modeChip = MODE_LABELS[mode]
    ? `<span class="chip">${MODE_LABELS[mode]}</span>` : '';
  if (slots.modeNote) slots.modeNote.textContent = MODE_HINTS[mode] ||
    'This report did not record its comparison mode — read each row against its own name.';
  const kvRow = (k, v) => `<div class="kv"><span>${escapeHtml(k)}</span><b>${v}</b></div>`;
  if (slots.runKv) slots.runKv.insertAdjacentHTML('beforeend',
    kvRow('Mode', escapeHtml(MODE_LABELS[mode] || 'not recorded')) +
    kvRow('Ranked', fmt(ranked.length)) +
    kvRow('Baseline', escapeHtml(baseline.name)));

  // ---- verdict band ----
  const topChanges = topRow ? changesFromBaseline(topRow, baseline) : [];
  const gain = topRow ? topRow.dps - baseline.dps : 0;
  const gainPct = topRow && baseline.dps ? gain / baseline.dps : null;
  slots.verdict.className = 'panel verdict';
  slots.verdict.innerHTML = `<div class="vl">
      <div class="lvg">${modeChip}${topRow ? deltaPill(gain, { pct: gainPct, title: `vs ${baseLabel}` }) : ''}</div>
      <h2>${topRow ? 'Top gear' : 'Your current gear is the reference'}</h2>
      <p class="tdesc">${escapeHtml(MODE_HINTS[mode] || '')}${isEquipped
        ? '' : ' No equipped baseline run was found, so percentages compare against the top candidate — the equipped set itself is not ranked here.'}</p>
      <div class="chips">${topChanges.map(c => chipHtml(c, 'cchip')).join('')}</div>
    </div>
    <div class="vbigbox">
      <div class="vbig num">${fmt(topRow ? topRow.dps : baseline.dps)}</div>
      <div class="ol">DPS · ${topRow ? 'best candidate' : 'baseline'}</div>
      <div class="vabs num">${fmt(baseline.dps)} baseline · ${escapeHtml(baseline.name)}</div>
    </div>
    <div class="chips vbtns">${topRow
      ? '<button type="button" class="btn" id="btn-apply-best">Apply best set</button>'
      : ''}<a class="btn-ghost" href="/">Back to gear</a></div>`;
  document.getElementById('btn-apply-best')?.addEventListener('click', () => {
    applyAndGo(selectedItemMap(topRow, baseline), taskId, baselineName || baseline.name);
  });

  // ---- per-slot recommendations (one best-ranked candidate per changed slot) ----
  const bySlot = new Map();
  for (const [index, result] of ranked.entries()) {
    for (const change of changesFromBaseline(result, baseline)) {
      if (!bySlot.has(change.slot)) bySlot.set(change.slot, { result, change, index });
    }
  }
  if (bySlot.size) {
    slots.recos.hidden = false;
    slots.recos.querySelector('.panelh .sub').textContent =
      'best ranked candidate per slot · deltas vs your baseline';
    slots.recos.querySelector('.upgrid').innerHTML = [...bySlot.entries()].map(([slot, { result, change, index }]) => {
      const info = infoFor(change.id);
      const delta = result.dps - baseline.dps;
      const pct = baseline.dps ? delta / baseline.dps : null;
      const err = typeof result.mean_error_pct === 'number' ? ` ± ${result.mean_error_pct}%` : '';
      const replaces = replacesText(change);
      return `<div class="slotsec"><div class="sechead"><h2>${escapeHtml(slot)}</h2><span class="cnt">#${index + 1}</span></div>
        <div class="rows"><div class="candup">
          ${iconSpan(change.id, info?.name || slot)}
          <a class="name" href="https://www.wowhead.com/item=${encodeURIComponent(change.id)}" target="_blank" rel="noopener" title="${escapeHtml(titleFor(change))}">${escapeHtml(info?.name || `#${change.id}`)}</a>
          <span class="il num">${info?.ilvl ?? '?'}</span><span class="grd"></span>
          <button type="button" class="apply btn btn-sm" data-slot="${escapeHtml(change.slot)}" data-item="${escapeHtml(gearStringFor(result, change))}" aria-label="Apply ${escapeHtml(info?.name || change.id)} to ${escapeHtml(slot)}">Apply</button>
        </div>
        ${replaces ? `<div class="rowfoot"><span class="replaces">${escapeHtml(replaces)}</span><span class="gainbox">${deltaPill(delta, { pct, title: `${fmt(result.dps)} DPS${err} vs ${baseLabel}` })}</span></div>` : ''}
        </div></div>`;
    }).join('');
    slots.recos.querySelectorAll('.candup .apply').forEach((button) => {
      button.addEventListener('click', () => {
        applyAndGo({ [rawSlot(button.dataset.slot)]: [button.dataset.item] }, taskId, baselineName || baseline.name);
      });
    });
  }

  // ---- best combination — full set (A2, MGE-2 §2) ----
  if (topRow) {
    slots.set.hidden = false;
    const setChanges = bestGearChanges(topRow, baseline);
    const changedKeys = new Set(topChanges.map(c => rawSlot(c.slot)));
    const rows = setChanges.map((change) => {
      const info = infoFor(change.id);
      const wasChanged = changedKeys.has(change.slot);
      return `<div class="setrow ${wasChanged ? 'sw' : 'kept'}"><div class="candup setcard">
          ${iconSpan(change.id, info?.name || change.slot)}
          <a class="name" href="https://www.wowhead.com/item=${encodeURIComponent(change.id)}" target="_blank" rel="noopener" title="${escapeHtml(titleFor(change))}">${escapeHtml(info?.name || `#${change.id}`)}</a>
          <span class="il num">${info?.ilvl ?? '?'}</span><span class="grd"></span>
          <span class="tag${wasChanged ? ' eq' : ''}">${wasChanged ? 'changed' : 'kept'}</span>
        </div></div>`;
    }).join('');
    slots.set.innerHTML = `<div class="panelh"><h2>Best combination — full set</h2>
        <span class="sub">#1 vs your ${escapeHtml(baseLabel)}</span>
        <span class="seg setseg" role="radiogroup" aria-label="Set view">
          <button type="button" role="radio" aria-checked="true" class="on" data-view="sw">Changes</button><button
          type="button" role="radio" aria-checked="false" data-view="all">Full set</button></span></div>
      <div class="setsum"><span class="rdps num">${fmt(topRow.dps)} DPS</span>
        <span class="gainbox">${deltaPill(gain, { pct: gainPct, title: `vs ${baseLabel}` })}</span>
        <button type="button" class="btn setapply" id="btn-apply-set">Apply full set</button></div>
      <div class="setgrid">${rows}</div>
      <p class="setnote dnote">ilvl numbers are equipped-item levels from Wowhead; the DPS gain belongs to the whole combination, not to any single row.</p>`;
    const applyView = (view) => {
      slots.set.querySelectorAll('.setrow').forEach((row) => {
        row.hidden = view === 'sw' && !row.classList.contains('sw');
      });
      slots.set.querySelectorAll('.setseg button').forEach((b) => {
        const on = b.dataset.view === view;
        b.classList.toggle('on', on);
        b.setAttribute('aria-checked', String(on));
      });
    };
    slots.set.querySelectorAll('.setseg button').forEach((b) => {
      b.addEventListener('click', () => applyView(b.dataset.view));
    });
    applyView(changedKeys.size ? 'sw' : 'all');
    document.getElementById('btn-apply-set').addEventListener('click', () => {
      applyAndGo(selectedItemMap(topRow, baseline), taskId, baselineName || baseline.name);
    });
  }

  // ---- combination register (only when the run simulated combinations) ----
  if (mode === 'combinations' && ranked.length) {
    slots.combos.hidden = false;
    slots.combos.querySelector('.combolist').innerHTML = ranked.map((result, index) => {
      const changes = index === 0 ? topChanges : changesFromBaseline(result, topRow);
      const chips = changes.map(c => chipHtml(c, 'cchip'));
      const shown = chips.slice(0, 4);
      const fold = chips.length > 4
        ? `<span class="cchip">+${chips.length - 4}</span>` : '';
      const delta = result.dps - baseline.dps;
      const pct = baseline.dps ? delta / baseline.dps : null;
      const vsBest = topRow ? `${((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)}%` : '';
      const n = changes.length;
      return `<div class="combo"><div class="comboh">
          <span class="czone1"><span class="rk num">#${index + 1}</span><span class="cchips">${shown.join('')}${fold}</span>
            <span class="cntn">${n} item${n === 1 ? '' : 's'}</span></span>
          <span class="cgain gainbox">${deltaPill(delta, { pct, title: `vs ${baseLabel}` })}</span>
          <span class="czone3"><span class="vsbest num">${escapeHtml(vsBest)} vs best</span></span>
        </div></div>`;
    }).join('');
  }

  // ---- ranked table (single render layer for every row, Gap 2) ----
  if (ranked.length) {
    slots.table.hidden = false;
    slots.table.querySelector('tbody').innerHTML = ranked.map((result, index) => {
      const delta = result.dps - baseline.dps;
      // Index 0 is the band's reference row — best itself is never a sidegrade.
      const tie = band !== null && index > 0 && result.dps >= band;
      const err = typeof result.mean_error_pct === 'number'
        ? ` ± ${result.mean_error_pct}%` : '';
      const vsBest = topRow
        ? `${((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)}%` : '';
      return `<tr${tie ? ' class="sidegrade"' : ''}>
        <td class="c-rk num">${index + 1}</td>
        <td class="c-swap"><span class="cand-swap"><span class="name" title="${escapeHtml(result.name)}">${escapeHtml(candidateLabel(result.name))}</span>${tie ? '<span class="sg-badge">≈ best (statistical tie)</span>' : ''}</span></td>
        <td class="c-dps num" title="${fmt(result.dps)} DPS${err}">${fmt(result.dps)}</td>
        <td class="c-d" title="vs ${baseLabel}">${deltaPill(delta, { title: `vs ${baseLabel}` })}</td>
        <td class="c-vb num">${escapeHtml(vsBest)}</td>
        <td class="c-ch"><span class="cchips">${result.changes.map(c => chipHtml(c, 'cchip')).join('')}</span></td>
      </tr>`;
    }).join('');
  } else {
    slots.table.hidden = false;
    slots.table.innerHTML = `<div class="panelh"><h2>No alternatives to rank</h2></div>
      <p class="setnote dnote">Select another item, enchant, gem, grade, or socket before running a comparison.</p>`;
  }

  // ---- quarantine rail (truth stays visible) ----
  const quarantined = [
    ...failed.map(result => [result, 'failed to simulate']),
    ...noDiff.map(result => [result, 'no gear difference']),
  ];
  slots.quarantine.innerHTML = quarantined.length
    ? quarantined.map(([result, reason]) =>
        `<div class="kv"><span title="${escapeHtml(reason)}">${escapeHtml(result?.name || 'unnamed run')}</span><b>${escapeHtml(String(result?.dps ?? '?'))} DPS</b></div>`).join('') +
      '<p class="honest">Quarantined runs are never ranked and never become the baseline.</p>'
    : '<p class="honest">Nothing excluded — every simulated run was rankable.</p>';
}
