from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_render_results_recommendations_rank_and_select_per_slot_candidates():
    harness = r'''
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
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 100, gear: { finger1: "id=1", head: "id=10" } },
  { name: "best", dps: 130, gear: { finger1: "id=2", head: "id=10" } },
  { name: "second", dps: 120, gear: { finger1: "id=3", head: "id=11" } },
  { name: "third", dps: 110, gear: { finger1: "id=4", head: "id=10" } },
];
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
const html = document.getElementById("recos-slot").querySelector(".upgrid").innerHTML;
const sections = [...html.matchAll(/<section class="slotsec" aria-label="([^"]+)">([\s\S]*?)<\/section>/g)];
if (sections.length !== 2) throw Error(`expected two rendered slot recommendations, got ${sections.length}`);
const bySlot = new Map(sections.map(([, aria, body]) => [aria.split(" ")[0], body]));
for (const body of bySlot.values()) {
  const label = body.match(/class="cnt num">rank (\d+) of (\d+)</);
  if (!label || Number(label[1]) > Number(label[2])) throw Error(`invalid rendered rank: ${body}`);
}
if (!bySlot.get("finger1")?.includes('data-item="id=2"') || !bySlot.get("finger1")?.includes("rank 1 of 3")) throw Error("finger1 did not render its best-ranked candidate and count");
if (!bySlot.get("head")?.includes('data-item="id=11"') || !bySlot.get("head")?.includes("rank 1 of 1")) throw Error("head did not render its best-ranked candidate and count");
'''
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", harness],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
