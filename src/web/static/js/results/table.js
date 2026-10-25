// js/results/table.js — RED-3 v11 render layer for the results page.
// Data semantics are the t_94a15fe3 port's verbatim (baseline pick, A2
// best-combination, quarantine doc 4.4, sidegrade band D6/Q3, mode chip
// Gap 1); markup follows the locked v11 registers (results.css): verdict
// band (+Σ), per-slot recommendations with mod/rec chips and the §4
// apply-queue, best-set with swapped/kept treatment, combination register
// with Details ▾, ranked .dt table, Runs panel, side rails, run bar.
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

// R2 (C-3 / §12 gate 5): the source label on every rec chip, verbatim.
const REC_SRC = 'enhancement recommendations (app config), not per-combo output';

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

/* C-3: /api/config id→name index (enchantments + gems share one id space). */
function cfgIndex(config) {
  const names = new Map();
  for (const list of Object.values(config?.enchantments || {})) {
    for (const entry of list) names.set(String(entry.id), entry.name);
  }
  for (const list of Object.values(config?.gems || {})) {
    for (const entry of list) names.set(String(entry.id), entry.name);
  }
  return names;
}

/* Config enchant pick for a raw gear key: finger1/finger2 share `finger`;
   off_hand falls back to main_hand; slots with no config entry (trinkets,
   unknown slots) are honest absence. */
function enchRec(config, rawKey) {
  const key = rawKey.replace(/[12]$/, '');
  return (config?.enchantments?.[key] || [])[0]
    || (key === 'off_hand' ? (config?.enchantments?.main_hand || [])[0] : null)
    || null;
}

/* R2 (C-3): solid chip only when the gear string actually carries the
   enchant_id/gem_id the report parser extracted (name resolved via the
   /api/config index); otherwise a dashed `rec` chip from the config's first
   entry for the slot — §6 requires the textual `rec` word, not color only. */
function modChips(gearString, rawKey, { config, names, noun, rec = false }) {
  const mods = [];
  const solid = (kind, icon, id, titleNoun) => {
    const name = names.get(id);
    if (name) mods.push(`<span class="mod ${kind}" title="${escapeHtml(`${titleNoun}: ${name}`)}">${icon} ${escapeHtml(name)}</span>`);
  };
  const ench = String(gearString).match(/(?:^|,)enchant_id=(\d+)/);
  const gem = String(gearString).match(/(?:^|,)gem_id=(\d+)/);
  if (ench) solid('ench', '⚡', ench[1], `${noun} enchant`);
  if (gem) solid('gem', '◆', gem[1], `${noun} gem`);
  if (rec && !mods.length) {
    const entry = enchRec(config, rawKey);
    if (entry) mods.push(
      `<span class="mod ench rec" title="${escapeHtml(`Recommended enchant — ${REC_SRC}: ${entry.name}`)}">⚡ ${escapeHtml(entry.name)}<i class="recm">rec</i></span>`,
    );
  }
  return mods.length ? `<span class="mods">${mods.join('')}</span>` : '';
}

/* §4 Runs panel (ruling O-4): run_id ≠ task_id — link rows via the task_id
   segment of report_url (reports/<user>/<task_id>/report_*.html); tag `this`
   when it equals the current run; never link a row without report_url. */
function runTaskId(run) {
  if (!run?.report_url) return '';
  const segment = String(run.report_url).split('/').slice(-2, -1)[0] || '';
  try { return decodeURIComponent(segment); } catch { return segment; }
}

function relTime(epoch) {
  const mins = Math.floor((Date.now() / 1000 - epoch) / 60);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
  return new Date(epoch * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function renderRuns(runs, currentTaskId) {
  const panel = document.getElementById('runs-slot');
  const list = document.getElementById('runs-list');
  if (!panel || !list) return;
  panel.hidden = false;
  list.innerHTML = (runs || []).slice(0, 3).map((run) => {
    const task = runTaskId(run);
    const id = escapeHtml(String(run.run_id || '').slice(0, 8));
    const meta = [run.fighting_style, run.status].filter(Boolean).join(' · ') || 'stored run';
    return `<div class="histrow">${task && task === currentTaskId ? '<span class="tag sel">this</span>' : ''}<span class="run">${task ? `<a href="results?task_id=${encodeURIComponent(task)}" title="Open this run's results">${id}</a>` : id}</span><span>${escapeHtml(meta)}</span><span class="now">${escapeHtml(relTime(run.created_at))}</span></div>`;
  }).join('')
    || '<p class="honest">No stored runs found for this account — history is recorded for signed-in runs.</p>';
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
  const appConfig = els.appConfig || null;
  const cfgNames = cfgIndex(appConfig);
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
    ? `${ranked.length} alternative${ranked.length === 1 ? '' : 's'} ranked against ${isEquipped ? 'your equipped gear' : 'the top candidate'}.`
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
  // R4 (§4 verdict band): Σ across ranked swaps — client arithmetic on the
  // ranked singles' deltas vs baseline (single_swap mode only); it is a sum
  // of independent single swaps, never a simulated set.
  const sumDelta = rankedRows.reduce((acc, r) => acc + (r.dps - baseline.dps), 0);
  const sumPct = baseline.dps ? sumDelta / baseline.dps : null;
  slots.verdict.className = 'panel verdict';
  slots.verdict.innerHTML = `<div class="vl">
      <div class="lvg">${modeChip}${topRow ? deltaPill(gain, { pct: gainPct, title: `vs ${baseLabel}` }) : ''}</div>
      <h2>${topRow ? 'Top gear' : 'Your current gear is the reference'}</h2>
      <p class="tdesc">${escapeHtml(MODE_HINTS[mode] || '')}${isEquipped
        ? '' : ' No equipped baseline run was found, so percentages compare against the top candidate — the equipped set itself is not ranked here.'}</p>
      ${mode === 'single_swap' && rankedRows.length && sumPct != null ? `<div style="margin:4px 0 2px"><span class="gain num">Σ <b>${deltaPill(sumDelta, { pct: sumPct, title: 'sum of every ranked single-swap gain vs baseline — arithmetic on independent swaps, not one simulated set' })}</b> across ranked swaps</span></div>` : ''}
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
      const candidates = bySlot.get(change.slot) || [];
      candidates.push({ result, change, index });
      bySlot.set(change.slot, candidates);
    }
  }
  const recButtons = [];
  if (bySlot.size) {
    slots.recos.hidden = false;
    slots.recos.querySelector('.panelh .sub').textContent =
      'best ranked candidate per slot · deltas vs your baseline';
    slots.recos.querySelector('.upgrid').innerHTML = [...bySlot.entries()].map(([slot, candidates]) => {
      const { result, change } = candidates[0];
      const info = infoFor(change.id);
      const baseInfo = change.before ? infoFor(change.before) : null;
      const delta = result.dps - baseline.dps;
      const pct = baseline.dps ? delta / baseline.dps : null;
      const err = typeof result.mean_error_pct === 'number' ? ` ± ${result.mean_error_pct}%` : '';
      const raw = rawSlot(change.slot);
      const gearString = gearStringFor(result, change);
      const replaces = baseInfo ? `replaces ${baseInfo.name}${typeof info?.ilvl === 'number' && typeof baseInfo.ilvl === 'number' ? ` · ilvl ${baseInfo.ilvl}` : ''}` : '';
      return `<section class="slotsec" aria-label="${escapeHtml(`${slot} recommended upgrade`)}"><div class="sechead"><h2>${escapeHtml(slot)}</h2><span class="cnt num">rank 1 of ${candidates.length}</span></div>
        <div class="cand candup"${ariaRecLabel(slot, info, change, pct, baseLabel, baseInfo)}>
          ${iconSpan(change.id, info?.name || slot)}
          <a class="name" href="https://www.wowhead.com/item=${encodeURIComponent(change.id)}" target="_blank" rel="noopener" title="${escapeHtml(titleFor(change))}">${escapeHtml(info?.name || `#${change.id}`)}</a>
          <span class="il num">${info?.ilvl ?? '?'}</span><span class="grd"></span>
          <button type="button" class="apply btn btn-sm" data-slot="${escapeHtml(raw)}" data-item="${escapeHtml(gearString)}" aria-pressed="false" aria-label="Use ${escapeHtml(info?.name || change.id)} for ${escapeHtml(slot)}">Use this</button>
        </div>
        <div class="rowfoot">${modChips(gearString, raw, { config: appConfig, names: cfgNames, noun: 'Recommended', rec: true })}${replaces ? `<span class="replaces">${escapeHtml(replaces)}</span>` : ''}<span class="gainbox">${deltaPill(delta, { pct, title: `${fmt(result.dps)} DPS${err} vs ${baseLabel}` })}</span></div>
        </section>`;
    }).join('');
    recButtons.push(...slots.recos.querySelectorAll('.candup .apply'));
  }

  // ---- best combination — full set (A2, MGE-2 §2; R5 treatment) ----
  if (topRow) {
    slots.set.hidden = false;
    const setChanges = bestGearChanges(topRow, baseline);
    const beforeByRaw = new Map(topChanges.map(c => [rawSlot(c.slot), c]));
    const changedKeys = new Set(beforeByRaw.keys());
    const setrow = (change) => {
      const raw = rawSlot(change.slot);
      const info = infoFor(change.id);
      const swapped = changedKeys.has(raw);
      const before = swapped ? beforeByRaw.get(raw) : null;
      const bInfo = before && before.before ? infoFor(before.before) : null;
      const gearString = swapped ? (topRow.gear?.[raw] || `id=${change.id}`) : (baseline.gear?.[raw] || `id=${change.id}`);
      // §4: second-trinket annotation — the sibling slot kept equipped.
      const sibling = raw === 'trinket1' ? 'trinket2' : raw === 'trinket2' ? 'trinket1' : '';
      const trinketNote = sibling && baseline.gear?.[sibling] && !changedKeys.has(sibling)
        ? ` · slot ${sibling === 'trinket1' ? '1' : '2'} — second trinket kept` : '';
      const caption = swapped
        ? (bInfo ? `replaces ${bInfo.name}${typeof bInfo.ilvl === 'number' ? ` · ilvl ${bInfo.ilvl}` : ''}${trinketNote}` : `replaces the equipped item${trinketNote}`)
        : 'stays equipped — the bundle does not change this slot';
      const il = typeof info?.ilvl === 'number' ? info.ilvl : null;
      const di = swapped && bInfo && il != null && typeof bInfo.ilvl === 'number' ? il - bInfo.ilvl : null;
      const aria = swapped
        ? `${change.slot} swapped in the best set — ${info?.name || `#${change.id}`}${il != null ? `, item level ${il}` : ''}${bInfo ? `, replaces ${bInfo.name}${typeof bInfo.ilvl === 'number' ? ` at item level ${bInfo.ilvl}` : ''}` : ''}`
        : `${change.slot} kept — equipped ${info?.name || `#${change.id}`}${il != null ? `, item level ${il}` : ''}, stays in the set`;
      return `<section class="slotsec setrow ${swapped ? 'sw' : 'kept'}" aria-label="${escapeHtml(aria)}"><div class="sechead"><h2>${escapeHtml(change.slot)}</h2><span class="cnt">${swapped ? 'swapped' : 'kept'}</span></div>
        <div class="cand candup setcard">
          ${iconSpan(change.id, info?.name || change.slot)}
          <a class="name" href="https://www.wowhead.com/item=${encodeURIComponent(change.id)}" target="_blank" rel="noopener" title="${escapeHtml(titleFor(change))}">${escapeHtml(info?.name || `#${change.id}`)}</a>
          <span class="il num">${info?.ilvl ?? '?'}</span><span class="grd"></span>
          ${swapped
            ? (di != null ? `<span class="d il-d ${di > 0 ? 'up' : di < 0 ? 'dn' : 'eq'} num" title="${escapeHtml(caption)}">${di > 0 ? '+' : ''}${di || '='} ilvl</span>` : '')
            : '<span class="d eq">base</span>'}
        </div>
        <div class="rowfoot">${modChips(gearString, raw, { config: appConfig, names: cfgNames, noun: swapped ? 'Recommended' : 'Equipped', rec: swapped })}<span class="replaces"${swapped && bInfo ? ` title="${escapeHtml(`${caption} — bundle delta only, no per-slot DPS exists inside a combination`)}"` : ''}>${escapeHtml(caption)}</span></div>
      </section>`;
    };
    // §4 set-level gem line: the config's 16-name standard pool, labelled
    // with the REC_SRC source string (combo output carries no per-item picks).
    const gemPool = appConfig?.gems?.standard || [];
    slots.set.innerHTML = `<div class="panelh"><h2>Best combination — full set</h2>
        <span class="sub">${changedKeys.size} of ${setChanges.length} slots replaced · the rest stay equipped</span>
        <span class="seg setseg" role="radiogroup" aria-label="Set view">
          <button type="button" role="radio" aria-checked="true" class="on" data-view="all">All slots</button><button
          type="button" role="radio" aria-checked="false" data-view="sw">Only changed</button></span></div>
      <div class="setsum"><span class="rdps num">${fmt(topRow.dps)} DPS</span>
        <span class="gainbox">${deltaPill(gain, { pct: gainPct, title: `vs ${baseLabel}` })}</span>
        <button type="button" class="btn setapply" id="btn-apply-set">Apply full set</button>
        ${gemPool.length ? `<span class="setgems"><span class="ol">Recommended gems · ${escapeHtml(REC_SRC)}</span>${gemPool.map(g => `<span class="mod gem" title="${escapeHtml(`Recommended gem — ${REC_SRC}: ${g.name}`)}">◆ ${escapeHtml(g.name)}</span>`).join('')}</span>` : ''}</div>
      <div class="setgrid">${setChanges.map(setrow).join('')}</div>
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
    applyView('all');
    document.getElementById('btn-apply-set').addEventListener('click', () => {
      applyAndGo(selectedItemMap(topRow, baseline), taskId, baselineName || baseline.name);
    });
  }

  // ---- combination register (only when the run simulated combinations) ----
  if (mode === 'combinations' && ranked.length) {
    slots.combos.hidden = false;
    const comboList = slots.combos.querySelector('.combolist');
    // R6 (§4): Details ▾ per-row expansion — item, ilvl before→after (both
    // ids resolved in the same chip batch), replaces caption, bundle honesty
    // note. The delta belongs to the bundle; the engine reports no per-item
    // deltas inside a combination.
    comboList.addEventListener('click', (e) => {
      const button = e.target.closest('.exp');
      if (!button) return;
      const det = button.closest('.combo').querySelector('.cdet');
      det.hidden = !det.hidden;
      button.setAttribute('aria-expanded', String(!det.hidden));
      button.textContent = det.hidden ? 'Details ▾' : 'Details ▴';
    });
    comboList.innerHTML = ranked.map((result, index) => {
      const changes = index === 0 ? topChanges : changesFromBaseline(result, topRow);
      const chips = changes.map(c => chipHtml(c, 'cchip'));
      const shown = chips.slice(0, 4);
      const fold = chips.length > 4
        ? `<span class="cchip">+${chips.length - 4}</span>` : '';
      const delta = result.dps - baseline.dps;
      const pct = baseline.dps ? delta / baseline.dps : null;
      const vsBest = topRow ? `${((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)}%` : '';
      const n = changes.length;
      const det = changes.map((c) => {
        const info = infoFor(c.id);
        const bInfo = c.before ? infoFor(c.before) : null;
        return `<div class="cdetrow">${iconSpan(c.id, info?.name || c.slot)}<span class="nm">${escapeHtml(info?.name || `#${c.id}`)}</span><span class="cdl">${escapeHtml(`${c.slot} · ilvl ${bInfo?.ilvl ?? '?'} → ${info?.ilvl ?? '?'}${bInfo ? ` · replaces ${bInfo.name}` : ''}`)}</span></div>`;
      }).join('');
      return `<div class="combo"><div class="comboh">
          <span class="czone1"><span class="rk num">#${index + 1}</span><span class="cchips">${shown.join('')}${fold}</span>
            <span class="cntn">${n} item${n === 1 ? '' : 's'}</span></span>
          <span class="cgain gainbox">${deltaPill(delta, { pct, title: `vs ${baseLabel}` })}</span>
          <span class="czone3"><span class="vsbest num">${escapeHtml(vsBest)} vs best</span>
            <button type="button" class="link exp" aria-expanded="false">Details ▾</button></span>
        </div>
        <div class="cdet" hidden>${det || '<div class="cdetrow"><span class="cdl">Equipped baseline — no changed items.</span></div>'}<p class="dnote">One simulated combination — the total belongs to the bundle as a whole. The engine reports no per-item deltas inside a combination, so none are shown.</p></div>
        </div>`;
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

  // ---- R3 (§4 run bar) + apply queue ----
  // The §10 queue batches every "Use this" into one writeApply on the single
  // Review-on-Gear navigation — applying k slots no longer costs k reloads.
  // Budget chip omitted (ruling R-1 honest absence): the combination budget
  // exists only server-side at run time (TG_MAX_COMBINATIONS) and is carried
  // on no get-results field. shortcut: if get-results ever ships a budget,
  // render `<span class="bud">budget N</span>` here.
  const runbar = document.getElementById('results-runbar');
  if (runbar) {
    const chip = document.getElementById('chip-quarantined');
    if (chip && quarantined.length) {
      chip.textContent = `${quarantined.length} quarantined · excluded from ranking`;
      chip.hidden = false;
    }
    runbar.hidden = !recButtons.length;
    if (recButtons.length) wireApplyQueue({
      recButtons,
      panelCount: document.getElementById('recos-count'),
      panelAll: document.getElementById('btn-apply-all'),
      barCount: document.getElementById('apply-count'),
      barAll: document.getElementById('btn-apply-all-bar'),
      review: document.getElementById('btn-review-gear'),
      taskId,
      charName: baselineName || baseline.name,
    });
  }
}

function ariaRecLabel(slot, info, change, pct, baseLabel, baseInfo) {
  const pctTxt = pct != null ? `${pct > 0 ? '+' : ''}${(pct * 100).toFixed(1)}% versus ${baseLabel}` : '';
  return ` role="group" aria-label="Recommended ${escapeHtml(slot)}: ${escapeHtml(info?.name || `#${change.id}`)}, ilvl ${info?.ilvl ?? '?'}, ${pctTxt}${baseInfo ? `, replaces ${escapeHtml(baseInfo.name)}` : ''}"`;
}

function wireApplyQueue({
  recButtons, panelCount, panelAll, barCount, barAll, review, taskId, charName,
}) {
  const total = new Set(recButtons.map(b => b.dataset.slot)).size;
  const applied = new Set();
  const queued = {}; // raw gear key -> [gear string] (§10 payload shape)
  const label = panelAll ? `Apply all ${total}` : '';
  if (panelCount) { panelCount.hidden = false; panelCount.textContent = `0 / ${total} applied`; }
  if (panelAll) { panelAll.hidden = false; panelAll.textContent = label; }
  if (barAll) barAll.textContent = `${label} upgrades`;
  const sync = () => {
    if (panelCount) panelCount.textContent = `${applied.size} / ${total} applied`;
    if (barCount) barCount.textContent = `${applied.size} / ${total}`;
    panelAll?.classList.toggle('on', applied.size === total);
    barAll?.classList.toggle('on', applied.size === total);
  };
  const mark = (button, on) => {
    const key = button.dataset.slot;
    if (on) {
      applied.add(key);
      queued[key] = [button.dataset.item];
    } else {
      applied.delete(key);
      delete queued[key];
    }
    button.closest('.candup').classList.toggle('applied', on);
    button.setAttribute('aria-pressed', String(on));
    button.textContent = on ? '✓ Applied' : 'Use this';
  };
  recButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const on = !applied.has(button.dataset.slot);
      mark(button, on);
      sync();
      if (applied.size) toast(`${applied.size} upgrade${applied.size > 1 ? 's' : ''} applied to your draft`);
    });
  });
  const setAll = () => {
    recButtons.forEach((button) => {
      if (!applied.has(button.dataset.slot)) mark(button, true);
    });
    sync();
    toast(`All ${total} upgrades applied to your draft`);
  };
  panelAll?.addEventListener('click', setAll);
  barAll?.addEventListener('click', setAll);
  // Plain <a href="./"> navigates; the queue write rides the same click.
  // Empty queue = pure navigation (an empty payload would CLEAR the gear
  // page's own selections via applyPayloadToState).
  review?.addEventListener('click', () => {
    if (applied.size) writeApply({ char_name: charName, selected_items: queued }, taskId);
  });
  sync();
}
