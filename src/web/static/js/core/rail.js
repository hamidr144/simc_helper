// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: core/rail)

import { state } from './state.js';

const RAIL_STEPS = [
  { id: 'step-export', num: 1, label: 'Export' },
  { id: 'step-gear', num: 2, label: 'Gear' },
  { id: 'step-enhance', num: 3, label: 'Enhancements' },
  { id: 'step-run', num: 4, label: 'Run' }
];
let railObserver = null;
const RAIL_TARGETS = {
  'step-export': 'addon-input-card',
  'step-gear': 'baseline-gear-panel',
  'step-enhance': 'step-enhance',
  'step-run': 'step-run'
};
export function renderRail() {
  const nav = document.getElementById('rail-steps');
  if (!nav || nav.childElementCount) return;
  nav.innerHTML = RAIL_STEPS.map(step =>
    `<button type="button" class="rail-step" data-step="${step.id}">` +
    `<span class="rail-step-num num-badge">${step.num}</span><span class="rail-step-label">${step.label}</span></button>`
  ).join('');
  nav.querySelectorAll('.rail-step').forEach(button =>
    button.addEventListener('click', () => {
      document.getElementById(RAIL_TARGETS[button.dataset.step] || button.dataset.step)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));
  updateRailState();
}
export function updateRailState() {
  const stepDone = {
    'step-export': Boolean(state.parsedData),
    'step-gear': Boolean(state.generatedInput),
    'step-enhance': state.simulationDone,
    'step-run': state.simulationDone
  };
  document.querySelectorAll('.rail-step').forEach(button => {
    const id = button.dataset.step;
    const step = RAIL_STEPS.find(item => item.id === id);
    const done = Boolean(stepDone[id]);
    button.classList.toggle('is-done', done);
    button.disabled = !(id === 'step-export' || state.parsedData);
    button.querySelector('.rail-step-num').textContent = done ? '✓' : step.num;
  });
}
export function observeWorkflowSteps() {
  if (railObserver) railObserver.disconnect();
  railObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    document.querySelectorAll('.rail-step').forEach(button =>
      button.classList.toggle('is-active', button.dataset.step === visible.target.dataset.stepId));
  }, { rootMargin: '-15% 0px -55% 0px', threshold: [0.05, 0.25] });
  const sections = {
    'step-export': document.getElementById('addon-input-card'),
    'step-gear': document.getElementById('baseline-gear-panel'),
    'step-enhance': document.getElementById('step-enhance'),
    'step-run': document.getElementById('step-run')
  };
  for (const [id, element] of Object.entries(sections)) {
    if (element) { element.dataset.stepId = id; railObserver.observe(element); }
  }
}

/* ---------- Worker status ---------- */
