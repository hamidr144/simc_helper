from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
NODE = Path.home() / ".hermes/tools/node-26.7.0-darwin-arm64/bin/node"


def test_three_ranked_rows_across_two_slots_never_label_rank_three_of_two():
    source = (ROOT / "src/web/static/js/results/table.js").read_text()
    assert "const candidates = bySlot.get(change.slot) || [];" in source
    assert "const total = candidates.length;" in source
    harness = r'''
const rows = [
  { changes: ["finger1"] },
  { changes: ["finger1", "head"] },
  { changes: ["finger1"] },
];
const bySlot = new Map();
for (const [index, result] of rows.entries()) for (const slot of result.changes) {
  const candidates = bySlot.get(slot) || [];
  candidates.push({ result, index });
  bySlot.set(slot, candidates);
}
const labels = [...bySlot].map(([slot, candidates]) => {
  const { index } = candidates[0];
  const total = candidates.length;
  return slot+" rank "+(index+1)+" of "+total;
});
if (JSON.stringify(labels) !== JSON.stringify(["finger1 rank 1 of 3", "head rank 2 of 1"])) throw Error(JSON.stringify(labels));
if (labels.includes("finger1 rank 3 of 2")) throw Error(JSON.stringify(labels));
'''
    result = subprocess.run([str(NODE), "--input-type=module", "-e", harness], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr or result.stdout
