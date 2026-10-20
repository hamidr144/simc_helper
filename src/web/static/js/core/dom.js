// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: core/dom)

export function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
// t_2ab8f3be: shared popover behavior (gear upgrade + pre-run diff, doc 5):
// aria-expanded, Esc, outside-click, focus return, Tab trap.
export function wirePopover(trigger, popover, onOpen) {
  const focusables = () => [...popover.querySelectorAll('button, select, input, a[href]')]
    .filter(el => !el.disabled && el.offsetParent !== null);
  function onKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key !== 'Tab') return;
    const els = focusables();
    if (!els.length) return;
    const first = els[0];
    const last = els[els.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  function onDoc(event) {
    if (!popover.contains(event.target) && event.target !== trigger) close(false);
  }
  function open() {
    popover.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    if (onOpen) onOpen();
    focusables()[0]?.focus();
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('click', onDoc, true);
  }
  function close(focusBack = true) {
    if (popover.hidden) return;
    popover.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('click', onDoc, true);
    if (focusBack) trigger.focus();
  }
  trigger.setAttribute('aria-expanded', 'false');
  trigger.addEventListener('click', () => { if (popover.hidden) open(); else close(); });
}
