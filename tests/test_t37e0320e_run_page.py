"""t_37e0320e — run progress moves off the gear page onto its own page.

Source contracts (repo convention, see test_t76a0ceb9 precedent): the run
panel hosts live on the results page, the gear page carries no run overlay,
run.js owns the single copy of the run-state/SSE logic, and the elapsed
timer math that runs across navigations is exercised in a node harness.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "web" / "static"


def _read(p):
    return (STATIC / p).read_text(encoding="utf-8")


APP_HTML = _read("app.html")
RESULTS_HTML = _read("results.html")
RUN_JS = _read("js/setup/run.js")
RESULTS_JS = _read("js/pages/results.js")
SETUP_JS = _read("js/pages/setup.js")
PASTE_JS = _read("js/setup/paste.js")
RUN_CSS = _read("css/run.css")
RESULTS_CSS = _read("css/results.css")


def test_gear_page_carries_no_run_panel():
    for host in ("run-view", "run-progress", "runview-log", "simulation-log",
                 "log-card", "btn-stop", "run-result", "log-toolbar"):
        assert f'id="{host}"' not in APP_HTML, host
    assert "aria-modal" not in APP_HTML
    # the runbar affordance is a plain link, hidden at rest (source state)
    assert '<a id="btn-open-run" class="btn-ghost" hidden href="results">View run</a>' in APP_HTML


def test_run_panel_hosts_live_on_results_page():
    for host in ("run-panel", "run-panel-title", "run-progress", "runview-combos",
                 "run-eta", "run-elapsed", "run-stage", "run-progress-fill",
                 "run-progress-meta", "runview-log", "simulation-log",
                 "run-result", "log-toolbar", "log-follow", "btn-log-download", "btn-stop"):
        assert f'id="{host}"' in RESULTS_HTML, host
    # back-to-gear is a plain link (the modal-close semantics are preserved)
    assert ('<a class="btn-ghost" href="./" style="margin-left:auto">Back to gear</a>'
            in RESULTS_HTML)
    # a11y: labelled panel section + progressbar semantics; no dialog hack
    assert 'aria-labelledby="run-panel-title"' in RESULTS_HTML
    assert 'role="progressbar"' in RESULTS_HTML and 'aria-valuemin="0"' in RESULTS_HTML
    assert 'role="dialog"' not in RESULTS_HTML


def test_run_state_logic_moved_not_duplicated():
    # one copy in the module graph: stream/progress/log live only in run.js
    assert "export function watchRun" in RUN_JS
    assert "watchRun" in RESULTS_JS
    for token in ("function renderLogTail", "function updateRunProgressMeta",
                  "function startRunProgress", "function pushLogLines"):
        assert token in RUN_JS, token
        assert token not in RESULTS_JS, token
    # the panel-as-dialog open/close/move helpers are gone everywhere
    for gone in ("openRunView", "closeRunView", "resetRunUI", "backToGear"):
        assert gone not in RUN_JS, gone
        assert gone not in SETUP_JS, gone
        assert gone not in PASTE_JS, gone


def test_start_navigates_and_the_run_session_survives_navigation():
    assert "window.location.href = activeRunHref(run)" in RUN_JS
    assert "results?run_task=" in RUN_JS
    assert "'simc-active-run@1'" in RUN_JS  # localStorage row (cleared on terminal)
    assert "function saveActiveRun" in RUN_JS
    assert "export function loadActiveRun" in RUN_JS
    assert "export function clearActiveRun" in RUN_JS
    assert "loadActiveRun" in SETUP_JS   # gear page reveals the View run link
    assert "clearActiveRun" in RESULTS_JS  # terminal events clear the row
    # gear drafts persist per change (draft.js) and the run is server-side;
    # closing the tab mid-run touches neither.
    assert "persistDraft" in SETUP_JS


def test_results_render_in_place_on_the_run_page():
    assert "watchRun({" in RESULTS_JS
    assert "fetchResults(runTask)" in RESULTS_JS
    assert "Simulation finished" in RESULTS_JS
    # the plain report view (?task_id=) keeps its pre-existing boot path
    assert "query.get('task_id')" in RESULTS_JS
    assert "run-panel" not in SETUP_JS  # setup never touches the panel


def test_overlay_css_removed_and_assets_versioned():
    assert ".runview{position:fixed" not in RUN_CSS
    assert ".runpanel .simulation-log" in RUN_CSS
    assert ".panelbody" in RESULTS_CSS
    # cache sweep for every touched asset reference (skill: manual ?v= busting)
    assert "run.css?v=red3-6" in APP_HTML and "run.css?v=red3-6" in RESULTS_HTML
    assert "results.css?v=red3-7" in RESULTS_HTML
    assert "results.js?v=red3-7" in RESULTS_HTML and "setup.js?v=red3-9" in APP_HTML


def test_format_elapsed_survives_renavigation():
    # startRunProgress renders elapsed from the persisted started_at, so a
    # mid-run reload keeps the true timer; harness the extracted formatter.
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    fn = re.search(r"function formatElapsed\(ms\) \{.*?\n\}", RUN_JS, re.S).group(0)
    script = (
        fn +
        "const cases = [[0, '00:00'], [90000, '01:30'], [3605000, '60:05']];"
        "let fail = 0;"
        "for (const [ms, want] of cases) {"
        "  const got = formatElapsed(ms);"
        "  if (got !== want) {"
        "    console.error(ms + ' -> ' + got + ' (want ' + want + ')'); fail = 1;"
        "  }"
        "}"
        "process.exit(fail);"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
