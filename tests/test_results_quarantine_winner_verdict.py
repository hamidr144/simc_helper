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
def test_quarantined_winner_must_not_coexist_with_baseline_is_best_claim():
    # Repro of the live contradiction at /results?task_id=39e2539f&baseline=Hamidriel.
    # t_9c515360 fix: the band discloses the quarantined leader instead of
    # claiming "baseline is best" (xfail marker removed as the tripwire).
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


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_quarantined_leader_disclosed_by_name_and_dps():
    # t_9c515360: positive half — the band names the quarantined leader and
    # its DPS, states the rail invariant, and keeps the no-Apply treatment
    # (a gear-identical row is noise, never an appliable upgrade).
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 196240, gear: { neck: "id=1" } },
  { name: "Hamidriel_head_0", dps: 196257, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_1", dps: 194610, gear: { neck: "id=2" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
const v = verdict();
if (!v.includes("quarantined")) throw Error("band must disclose the quarantined leader: " + v);
if (!v.includes("Hamidriel_head_0")) throw Error("band must name the quarantined leader: " + v);
if (!v.includes("196,257")) throw Error("band must state the leader DPS: " + v);
if (v.includes("Apply best set")) throw Error("no Apply for a below-baseline ranked row: " + v);
if (!rail().includes("never ranked and never become the baseline"))
  throw Error("rail invariant text must survive: " + rail());
'''
    run_harness(body)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_honest_baseline_is_best_claim_kept_without_beating_quarantine():
    # The honesty fix must not kill the honest claim: all-losers run whose
    # quarantined rows also lose keeps "baseline is best" (QA t_67656572
    # case 1 state, e.g. eba6944b).
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 196182, gear: { neck: "id=1" } },
  { name: "Hamidriel_head_0", dps: 195000, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_1", dps: 195004, gear: { neck: "id=2" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
if (!verdict().includes("No upgrade found — baseline is best"))
  throw Error("honest claim must survive with no beating quarantined run: " + verdict());
if (verdict().includes("quarantined")) throw Error("no disclosure without a beating leader: " + verdict());
'''
    run_harness(body)
