from pathlib import Path


RESULTS_TABLE = Path("src/web/static/js/results/table.js").read_text()


def test_results_labels_fallback_baseline_and_deltas():
    assert "isEquipped ? 'your equipped gear' : 'the top candidate (fallback baseline)'" in RESULTS_TABLE
    assert "ranked against ${isEquipped ? 'your equipped gear' : 'the top candidate (fallback baseline)'}." in RESULTS_TABLE
    assert "deltas vs ${baseLabel}" in RESULTS_TABLE
    assert "vs ${baseLabel}" in RESULTS_TABLE


def test_results_keeps_explicit_equipped_baseline_wording():
    assert "isEquipped ? 'your equipped gear' : 'the top candidate (fallback baseline)'" in RESULTS_TABLE
    assert "Only your equipped baseline was simulated." in RESULTS_TABLE
    assert "isEquipped\n        ? '' : ' No equipped baseline run was found" in RESULTS_TABLE
