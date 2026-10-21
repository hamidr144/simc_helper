// js/core/theme.js — RED-3 theme contract (design contract §2). Three states:
// System (default, stores NOTHING, tracks prefers-color-scheme live) / Light /
// Dark (explicit choice stored under 'simc-theme', beats the OS, survives
// reload). Picking System deletes the key. Semantics ported verbatim from
// gear-run.html L121–148 minus the mockup-only ?set/?pal/?os params and the
// Simulate-OS button. Pages pre-paint data-pal inline (no FOUC); this module
// only wires the radiogroup and OS tracking (change event + 1.5 s poll — CDP
// media emulation fires no change event, M6 note).
let pref = 'system';
try { pref = localStorage.getItem('simc-theme') || 'system'; } catch { /* System */ }
// headless harnesses have no matchMedia: degrade to a light-OS stub.
const mq = typeof matchMedia === 'function'
  ? matchMedia('(prefers-color-scheme: dark)')
  : { matches: false, addEventListener() {}, removeEventListener() {} };
let osDark = mq.matches;
const effective = () => (pref === 'system' ? (osDark ? 'dark' : 'light') : pref);

function applyTheme() {
  document.documentElement.dataset.pal = effective();
  document.querySelectorAll('.seg[role=radiogroup] [data-th]').forEach(button => {
    const on = button.dataset.th === pref;
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  });
}

export function wireTheme() {
  const group = document.querySelector('.seg[role=radiogroup]');
  group?.addEventListener('click', event => {
    const button = event.target.closest('[data-th]');
    if (!button) return;
    pref = button.dataset.th;
    try {
      if (pref === 'system') localStorage.removeItem('simc-theme');
      else localStorage.setItem('simc-theme', pref);
    } catch { /* storage errors degrade silently to System */ }
    applyTheme();
  });
  const trackOs = () => {
    if (osDark !== mq.matches) {
      osDark = mq.matches;
      if (pref === 'system') applyTheme();
    }
  };
  mq.addEventListener('change', trackOs);
  setInterval(trackOs, 1500);
  applyTheme();
}
