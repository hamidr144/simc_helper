// js module — mechanical port of app.js regions by t_94a15fe3 (gui-rewrite-contract §3.1: core/workers)
import { apiFetch } from '../core/api.js';

let workerPollFailures = 0;
export async function pollWorkerStatus() {
  const chip = document.getElementById('worker-status');
  const text = document.getElementById('worker-status-text');
  if (!chip || !text) return;
  try {
    const response = await apiFetch('api/state');
    // 401 = logged out: the banner explains it; the chip stays unknown ("—")
    // until a successful authenticated poll (A4 — never a misleading chip).
    if (response.status === 401) return;
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    workerPollFailures = 0;
    const workers = data.workers || [];
    const idle = workers.filter(worker => /idle/i.test(worker.status || '')).length;
    const titles = workers.map(worker => `${worker.name}: ${worker.status}`).join('\n');
    if (!workers.length) {
      chip.className = 'status-chip status-err';
      text.textContent = 'No idle workers';
      chip.title = 'No SimC worker is connected to the master.';
    } else if (idle === 0) {
      // Busy is a queue state, not an error (doc 4.1).
      chip.className = 'status-chip status-warn';
      text.textContent = 'All workers busy \u00b7 waiting';
      chip.title = titles;
    } else {
      chip.className = 'status-chip status-ok';
      text.textContent = `${idle}/${workers.length} workers idle`;
      chip.title = titles;
    }
  } catch {
    // Only after 3 consecutive failures is "Server offline" honest.
    workerPollFailures += 1;
    if (workerPollFailures >= 3) {
      chip.className = 'status-chip status-err';
      text.textContent = 'Server offline';
      chip.title = 'The master server could not be reached.';
    }
  }
}

/* ---------- Character chip ---------- */
