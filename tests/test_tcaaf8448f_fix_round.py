"""RED-3F (t_caa8448f): fix-round pins for the PR #38 review findings.

R1 Runs panel (ruling O-4), R2 rec/enchant-gem chips + set gem line (C-3,
gate 5), R3 §4 run bar + batched apply queue, R4 Σ across ranked swaps,
R5 set swapped/kept treatment, R6 combination Details ▾, R7 import-band
collapse (D-4), R8 honest-absences ledger. Static pins in house style.
"""
import pathlib

from static_assets import read_js

JS = read_js()
RESULTS_HTML = (pathlib.Path(__file__).resolve().parents[1] / "src" / "web" / "static" / "results.html").read_text()
SETUP_JS = (pathlib.Path(__file__).resolve().parents[1] / "src" / "web" / "static" / "js" / "pages" / "setup.js").read_text()

REC_SRC = "enhancement recommendations (app config), not per-combo output"


def test_r1_runs_panel_wired():
    # §4 / ruling O-4: fetch + host + task_id linkage from report_url.
    assert "api/history?limit=3" in JS
    assert 'id="runs-slot"' in RESULTS_HTML and 'id="runs-list"' in RESULTS_HTML
    assert "All history" in RESULTS_HTML
    assert "function renderRuns" in JS
    assert 'slice(-2, -1)' in JS          # task_id = parent dir of report_url
    assert '<span class="tag sel">this</span>' in JS


def test_r2_rec_chips_and_source_label():
    # C-3 / gate 5: source label verbatim; solid only from gear ids; dashed
    # rec carries the §6 textual word; set gem line renders the 16-pool.
    assert REC_SRC in JS
    assert REC_SRC in RESULTS_HTML  # the ledger cites the same label (R8)
    assert 'class="mod ench rec"' in JS
    assert '<i class="recm">rec</i>' in JS
    assert "enchant_id=(\\d+)" in JS and "gem_id=(\\d+)" in JS
    assert "gems?.standard" in JS and 'class="setgems"' in JS
    assert "api/config" in JS


def test_r3_runbar_and_batched_apply_queue():
    # §4 run bar hosts; per-row buttons toggle aria-pressed; ONE writeApply
    # rides the Review-on-Gear navigation (queue), not per-row navigation.
    for host in ("results-runbar", "btn-review-gear", "btn-apply-all-bar",
                 "apply-count", "recos-count", "btn-apply-all", "chip-quarantined"):
        assert f'id="{host}"' in RESULTS_HTML, host
    assert 'aria-pressed="false"' in JS and "✓ Applied" in JS and "Use this" in JS
    assert "applied to your draft" in JS
    assert "function wireApplyQueue" in JS
    # Queue: single writeApply on navigation for the batched draft.
    assert "if (applied.size) writeApply" in JS


def test_r4_sigma_across_ranked_swaps():
    assert "across ranked swaps" in JS
    assert "sum of every ranked single-swap gain vs baseline" in JS


def test_r5_set_swapped_kept_treatment():
    assert "stays equipped — the bundle does not change this slot" in JS
    assert 'class="d il-d ' in JS                       # ilvl-delta pill
    assert "second trinket kept" in JS
    assert "swapped in the best set" in JS and "kept — equipped" in JS


def test_r6_combination_details_expansion():
    assert "Details ▾" in JS and "Details ▴" in JS
    assert 'aria-expanded' in JS
    assert 'class="cdet" hidden' in JS


def test_r7_import_band_collapses_when_loaded():
    # D-4: renderWorkflow collapses; paste.js btn-new-export keeps the open
    # direction (`.open = true` stays there).
    assert "import-details" in SETUP_JS
    assert "importBand.open = false" in SETUP_JS


def test_r8_honest_absences_ledger():
    assert "Honest absences" in RESULTS_HTML
    assert "No probability badges" in RESULTS_HTML
    assert "bundle as one actor" in RESULTS_HTML
    assert "dashed" in RESULTS_HTML and REC_SRC in RESULTS_HTML
