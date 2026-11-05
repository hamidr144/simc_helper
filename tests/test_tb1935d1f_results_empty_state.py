"""t_b1935d1f (iter-2 rank-2): results-page actionable no-task empty state.

Source contract + node harness for the no-task render branch:
- pages/results.js renders the .panel-card.empty-results card (h2, guidance
  line, primary a.btn CTA to './') instead of a bare subtitle.
- results.html: the Excluded-runs section is hidden by default (no empty
  heading without a report) and the duplicate footer Run-history link is gone.
- table.js renderResults un-hides the quarantine section (task pages keep the
  "truth stays visible" rail).
"""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "web" / "static"
RESULTS_HTML = (STATIC / "results.html").read_text(encoding="utf-8")
PAGE_JS = (STATIC / "js" / "pages" / "results.js").read_text(encoding="utf-8")
TABLE_JS = (STATIC / "js" / "results" / "table.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def test_no_task_branch_renders_actionable_empty_card():
    assert "<h2>No run selected</h2>" in PAGE_JS
    assert "Start a comparison on the Gear page and results will appear here." in PAGE_JS
    assert 'class="panel-card empty-results"' in PAGE_JS
    assert '<a class="btn" href="./">' in PAGE_JS


def test_results_html_defaults_and_footer():
    assert '<div class="side" id="side-quarantine-sec" hidden>' in RESULTS_HTML
    # Duplicate footer link dropped; the side rail "View run history" stays.
    assert '<div class="footmeta">\n    <!-- t_b1935d1f' in RESULTS_HTML
    assert '<a href="history">Run history</a>' not in RESULTS_HTML
    assert '<a class="btn-ghost" href="history">View run history</a>' in RESULTS_HTML
    assert "results.js?v=red3-9" in RESULTS_HTML


def test_render_results_unhides_quarantine_section():
    assert "getElementById('side-quarantine-sec')" in TABLE_JS


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
'''


def run_harness(body):
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", HARNESS_PRELUDE + body],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_report_render_opens_quarantine_section_hidden_in_html():
    body = r'''
const subtitle = { textContent: "" };
const results = [
  { name: "equipped", dps: 1000, gear: { neck: "id=1" } },
  { name: "Hamidriel_neck_1", dps: 1100, gear: { neck: "id=2" } },
];
// Fake starts hidden=true — same default as the hidden attribute in HTML.
renderResults(results, "single_swap", { subtitle, baselineName: "equipped", taskId: "task" });
const sec = document.getElementById("side-quarantine-sec");
if (sec.hidden !== false) throw Error("rendered report must un-hide the quarantine section");
'''
    run_harness(body)
