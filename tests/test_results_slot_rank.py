from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NODE = Path.home() / ".hermes/tools/node-26.7.0-darwin-arm64/bin/node"


def test_three_ranked_rows_across_two_slots_have_consistent_per_slot_ranks():
    harness = r'''
import { slotRankLabel } from "./src/web/static/js/results/table.js";
const rows = [
  { changes: ["finger1"] },
  { changes: ["finger1", "head"] },
  { changes: ["finger1"] },
];
const bySlot = new Map();
for (const result of rows) for (const slot of result.changes) {
  const candidates = bySlot.get(slot) || [];
  candidates.push(result);
  bySlot.set(slot, candidates);
}
const labels = [...bySlot].map(([slot, candidates]) => [slot, slotRankLabel(candidates)]);
if (JSON.stringify(labels) !== JSON.stringify([["finger1", "rank 1 of 3"], ["head", "rank 1 of 1"]])) throw Error(JSON.stringify(labels));
for (const [, label] of labels) {
  const [, position, total] = label.match(/^rank (\d+) of (\d+)$/).map(Number);
  if (position > total) throw Error(label);
}
'''
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", harness],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
