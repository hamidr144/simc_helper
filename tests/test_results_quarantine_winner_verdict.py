from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

# Shared DOM fake (same shape as test_results_no_upgrade_state.py).
HARNESS_PRELUDE = r'''
import { renderResults } from "./src/web/static/js/results/table.js";
class Element {
  constructor() { this.hidden = true; this.dataset = {}; this.classList = { add() {}, toggle() {}, contains() { return false; } }; }
  querySelector(selector) { return this.children ||= new Map(), this.children.get(selector) || this.children.set(selector, new Element()).get(selector); }
  querySelectorAll() { return []; }
  addEventListener() {}
  insertAdjacentHTML() {}
  setAttribute() {}
}
const elements = new Map();
globalThis.document = {
  getElementById(id) { return elements.get(id) || elements.set(id, new Element()).get(id); },
};
const verdict = () => document.getElementById("verdict-slot").innerHTML;
const rail = () => document.getElementById("side-quarantine").innerHTML;
'''


def run_harness(body):
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", HARNESS_PRELUDE + body],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
@pytest.mark.xfail(
    strict=True,
    reason=(
        "defect t_67656572 (live 39e2539f): an ilvl-only upgrade-track candidate "
        "parses identity-equal to baseline, is quarantined as 'no gear difference', "
        "is never ranked nor considered for the verdict — so a quarantined 196,257 "
        "DPS row sits in the rail while the band claims 'No upgrade found — baseline "
        "is best' over a 196,240 fallback baseline. Self-contradicting state; the "
        "real winner is invisible."
    ),
)
def test_quarantined_winner_must_not_coexist_with_baseline_is_best_claim():
    # Repro of the live contradiction at /results?task_id=39e2539f&baseline=Hamidriel.
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 1000, gear: { neck: "id=1" } },
  // ilvl-only upgrade: gear string parses identity-equal -> quarantined noDiff.
  { name: "Hamidriel_head_0", dps: 1017, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_1", dps: 992, gear: { neck: "id=2" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
// Truth rule: the rail discloses the excluded run (this half already holds).
if (!rail().includes("1017")) throw Error("quarantine rail must disclose the excluded run: " + rail());
// Honesty rule (the defect): the band must not claim the baseline is best while a
// disclosed quarantined run beats it.
if (verdict().includes("No upgrade found — baseline is best"))
  throw Error("false 'baseline is best' claim while quarantined 1017 > baseline 1000: " + verdict());
'''
    run_harness(body)
