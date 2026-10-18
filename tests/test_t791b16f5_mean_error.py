"""TG2-D (t_791b16f5): pinned UI strings for the mean±error ranked table.

Mirror-image guards for results.js (design §4.3/§5.5, ruling Q3): the
sidegrade band computes from the merged ``mean_error_pct`` at 2x the best
candidate's error, the band is presentation-only (rank order stays the raw
engine order), and the ``% vs best`` column + tie badge strings are exact.
Behavioural coverage rides tests/test_master_api.py (parse+merge) and
tests/test_worker.py (stage-3 log in artifacts.zip).
"""
from pathlib import Path

RESULTS_JS = Path("src/web/static/results.js").read_text(encoding="utf-8")
STYLE_CSS = Path("src/web/static/style.css").read_text(encoding="utf-8")


def test_sidegrade_band_inputs_pinned():
    assert "topRow.mean_error_pct" in RESULTS_JS
    assert "2 * topRow.mean_error_pct / 100" in RESULTS_JS
    assert 'class="is-sidegrade"' in RESULTS_JS
    assert "≈ best (statistical tie)" in RESULTS_JS
    assert "sidegrades within 2× error of best" in RESULTS_JS
    # Presentation-only: the band never touches the sort — raw SimC mean
    # order is the ruling (design §5.5).
    assert ".sort((a, b) => b.dps - a.dps)" in RESULTS_JS


def test_vs_best_column_pinned():
    assert "% vs best" in RESULTS_JS
    assert "((result.dps - topRow.dps) / topRow.dps * 100).toFixed(2)" in RESULTS_JS
    # Error suffix renders only when the server merged precision data
    # (legacy runs have no stage-3 log — the page must stay unchanged).
    assert "± ${result.mean_error_pct}%" in RESULTS_JS
    assert "typeof result.mean_error_pct === 'number'" in RESULTS_JS


def test_sidegrade_styles_present():
    assert ".results-table tr.is-sidegrade td" in STYLE_CSS
    assert ".sidegrade-badge" in STYLE_CSS
