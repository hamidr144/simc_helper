from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

# Shared DOM fake (same shape as test_results_slot_rank.py).
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
const setPanel = () => document.getElementById("set-slot").innerHTML;
'''


def run_harness(body):
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", HARNESS_PRELUDE + body],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_all_losers_render_no_upgrade_state_not_best_candidate():
    # QA t_02facd2d: neck_0 at -0.8% vs baseline must not be labelled
    # "best candidate" — the baseline is the best set in the report.
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 1000, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_0", dps: 992, gear: { neck: "id=2" } },
  { name: "Hamidriel_head_1", dps: 985, gear: { neck: "id=1", head: "id=9" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
if (!verdict().includes("No upgrade found — baseline is best")) throw Error("verdict h2 missing no-upgrade label: " + verdict());
if (verdict().includes("best candidate<")) throw Error("verdict still labels a loser 'best candidate'");
if (!verdict().includes("top-ranked candidate · below baseline")) throw Error("missing below-baseline label: " + verdict());
if (!verdict().includes("Every simulated candidate lost to the baseline")) throw Error("missing explanatory line");
if (verdict().includes("Apply best set")) throw Error("apply button offered for a losing set");
if (setPanel().includes("Apply full set")) throw Error("apply-full-set offered for a losing set");
if (!setPanel().includes("Top-ranked set — below baseline")) throw Error("set panel keeps 'Best combination' title: " + setPanel());
if (!verdict().includes("-0.8%")) throw Error("honest delta not shown: " + verdict());
'''
    run_harness(body)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_tie_with_baseline_counts_as_no_upgrade():
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 1000, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_0", dps: 1000, gear: { neck: "id=2" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
if (!verdict().includes("No upgrade found — baseline is best")) throw Error("tie vs baseline not treated as no-upgrade");
if (verdict().includes("Apply best set")) throw Error("apply button offered for a tie");
'''
    run_harness(body)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_winning_candidate_keeps_best_candidate_label_and_apply():
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 1000, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_0", dps: 1300, gear: { neck: "id=2" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
if (!verdict().includes("Top gear")) throw Error("winner verdict h2 regressed");
if (!verdict().includes("best candidate<")) throw Error("winner lost its best-candidate label");
if (!verdict().includes("Apply best set")) throw Error("winner lost its apply button");
if (!setPanel().includes("Best combination — full set")) throw Error("winner set panel title regressed");
if (!setPanel().includes("Apply full set")) throw Error("winner lost apply-full-set");
if (verdict().includes("No upgrade found")) throw Error("winner falsely shows no-upgrade");
'''
    run_harness(body)
