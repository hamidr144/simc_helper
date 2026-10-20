// js/core/version.js (gui-rewrite §3.1, A6/I-35): version chip in the rail footer.
// GET api/version -> {version}; any failure leaves the chip empty (honest
// absence, G-R28 — no version literal ships in static/).
import { apiFetch } from './api.js';

export async function fetchVersion() {
  const el = document.getElementById('app-version');
  if (!el) return;
  try {
    const res = await apiFetch('api/version');
    if (!res.ok) return;
    const data = await res.json();
    el.textContent = data.version || '';
  } catch { /* chip stays empty */ }
}
