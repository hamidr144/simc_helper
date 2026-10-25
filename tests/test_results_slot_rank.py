from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_three_ranked_rows_across_two_slots_have_consistent_per_slot_ranks():
    harness = r'''
import { readFileSync } from "node:fs";
const table = readFileSync("src/web/static/js/results/table.js", "utf8");
if (!table.includes('rank 1 of ${candidates.length}')) throw Error("label not tied to per-slot candidate count");
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
const labels = [...bySlot].map(([slot, candidates]) => [slot, `rank 1 of ${candidates.length}`]);
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
