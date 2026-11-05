from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

# t_c007fe8f rank-1: the boot-disabled Run button must explain itself
# (ISO 9241-110 self-descriptiveness): title "Load a character first" plus
# an import hint in the empty #workflow-status band, replaced by the normal
# generateInput summary after import. Shared DOM fake per the
# test_results_slot_rank.py harness shape.
HARNESS_PRELUDE = r'''
import { updateSummary } from "./src/web/static/js/setup/runbar.js";
import { state } from "./src/web/static/js/core/state.js";
class Element {
  constructor() { this.textContent = ""; this.title = ""; this.disabled = true; }
}
const elements = new Map();
globalThis.document = {
  getElementById(id) { return elements.get(id) || elements.set(id, new Element()).get(id); },
  querySelector() { return null; },
  querySelectorAll() { return []; },
};
const run = () => document.getElementById("btn-run");
const band = () => document.getElementById("workflow-status");
'''

HINT = ("Import a character (paste an export, or load from Armory) "
        "to start comparing gear.")


def run_harness(body):
    result = subprocess.run(
        [str(NODE), "--input-type=module", "-e", HARNESS_PRELUDE + body],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_boot_without_character_explains_disabled_run():
    body = r'''
state.parsedData = null; state.generatedInput = null;
updateSummary();
if (run().title !== "Load a character first") throw Error("run title missing: " + run().title);
if (!run().disabled) throw Error("Run must start disabled with no character");
if (band().textContent !== HINT) throw Error("band hint missing: " + band().textContent);
if (band().title !== band().textContent) throw Error("band title must carry the full text (t_5c33fefb contract)");
'''.replace("HINT", repr(HINT))
    run_harness(body)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_hint_never_stomps_boot_notes_or_live_messages():
    # setup wire() writes the run-in-progress note after updateSummary();
    # selectionChanged writes "Updating comparison…" later. The hint may
    # only claim an EMPTY band, so those messages always win.
    body = r'''
state.parsedData = null; state.generatedInput = null;
band().textContent = "A simulation run is in progress — gear editing stays free; View run follows its progress.";
updateSummary();
if (band().textContent.includes("Import a character")) throw Error("hint overwrote the run-in-progress note");
band().textContent = "Updating comparison…";
updateSummary();
if (band().textContent !== "Updating comparison…") throw Error("hint resurrected over a live message: " + band().textContent);
if (run().title !== "Load a character first") throw Error("run title lost while band is busy");
'''
    run_harness(body)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for this JavaScript regression")
def test_imported_character_clears_title_and_keeps_generate_summary():
    # Faithful import tail: generateInput wrote its summary unconditionally,
    # then calls updateSummary() in finally.
    body = r'''
state.parsedData = { char_name: "Testie" };
state.generatedInput = { combinations: 3 };
band().textContent = "Ready to run 3 candidate combinations.";
updateSummary();
if (run().title !== "") throw Error("title not cleared after import: " + run().title);
if (run().disabled) throw Error("Run must enable after import");
if (band().textContent !== "Ready to run 3 candidate combinations.") throw Error("stale/overwritten import summary: " + band().textContent);
'''
    run_harness(body)
