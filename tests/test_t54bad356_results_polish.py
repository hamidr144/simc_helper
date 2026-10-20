"""TG3-G (t_54bad356): batched results-page polish pins.

Gap 1 compare-mode indicator (mode passthrough through /api/get-results +
mode chip), gap 2 top-3 card block removed, gap 3 one primary number per
row, gap 4 human candidate labels, gap 5 chip replaces-context.
"""
import os
from pathlib import Path

import web.main
from fastapi.testclient import TestClient
from src.core.db import task_owner_upsert
from web.main import app
from static_assets import read_css, read_js, resp  # t_94a15fe3 split pins

STATIC = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
RESULTS_JS = read_js()
CSS = read_css()

client = TestClient(app)


# ---- gap 2: one render layer -------------------------------------------------

def test_top3_card_block_removed():
    assert "result-card" not in RESULTS_JS
    assert "best-result" not in RESULTS_JS
    assert ".result-card" not in CSS
    assert ".best-result" not in CSS
    # The card-only helpers/classes are gone with the block.
    assert "chip-row" not in CSS.split("/* --- Icon fallback")[0]  # chip-row rule dead


# ---- gap 3: one primary comparison number ------------------------------------

def test_demoted_columns_stay_in_dom():
    assert '<th scope="col" class="results-secondary">' in RESULTS_JS
    assert 'class="results-num results-secondary"' in RESULTS_JS
    # Demoted values remain in DOM via sr-only spans and the delta tooltip.
    assert "results-table .results-secondary" in CSS
    assert "vs best" in RESULTS_JS  # header + tooltip text still present


# ---- gap 4: human candidate labels -------------------------------------------

def test_candidate_label_humanized():
    assert "function candidateLabel" in RESULTS_JS
    assert "Combination #" in RESULTS_JS
    assert "${slot} swap" in RESULTS_JS
    # Machine name survives as the row tooltip.
    assert 'class="candidate-label" title="${escapeHtml(result.name)}"' in RESULTS_JS


# ---- gap 5: chip replaces-context ---------------------------------------------

def test_chip_replaces_context():
    assert " replaces " in RESULTS_JS
    assert "beforeBonus" in RESULTS_JS
    # Resolved through the existing batch path (no new endpoint): the before
    # ids join the same wanted-map chunking.
    assert "wanted.set(change.before" in RESULTS_JS


# ---- gap 1: mode passthrough ---------------------------------------------------

def test_task_mode_reads_persisted_meta(tmp_path):
    task_owner_upsert("t-g-mode-db", "testuser", '{"mode": "combinations"}')
    assert web.main._task_mode(str(tmp_path / "t-g-mode-db")) == "combinations"


def test_task_mode_in_memory_and_bogus(tmp_path):
    web.main.task_meta_map["t-g-mode-mem"] = {"mode": "single_swap"}
    try:
        assert web.main._task_mode("/x/t-g-mode-mem") == "single_swap"
    finally:
        web.main.task_meta_map.pop("t-g-mode-mem", None)
    task_owner_upsert("t-g-mode-bogus", "u", "not-json")
    assert web.main._task_mode(str(tmp_path / "t-g-mode-bogus")) is None
    task_owner_upsert("t-g-mode-unknown", "u", '{"mode": "bogus"}')
    assert web.main._task_mode(str(tmp_path / "t-g-mode-unknown")) is None
    # Never-seen task -> honest absence, no DB error.
    assert web.main._task_mode(str(tmp_path / "t-g-mode-never")) is None


def _write_report(task_id: str) -> None:
    # Read REPORTS_DIR LIVE from the module: test_security_config reloads
    # web.main mid-suite, which rebinds the global away from the conftest
    # temp; a module-import-time snapshot then misses the handler's lookups.
    task_dir = os.path.join(web.main.REPORTS_DIR, "testuser", task_id)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "report_t.html"), "w", encoding="utf-8") as f:
        f.write('<h2 class="toggle">Hamidriel&#160;:&#160;190,626 dps</h2>\n'
                '<h2 class="toggle">Hamidriel_Combo_2&#160;:&#160;194,349 dps</h2>')


def test_get_results_carries_mode():
    task_id = "test-tg3g-mode"
    _write_report(task_id)
    task_owner_upsert(task_id, "testuser", '{"mode": "combinations"}')
    data = client.get(f"/api/get-results?task_id={task_id}").json()
    assert data["status"] == "success"
    assert len(data["results"]) == 2
    assert data["mode"] == "combinations"


def test_get_results_legacy_run_has_no_mode():
    task_id = "test-tg3g-legacy"
    _write_report(task_id)  # no task_owner meta row -> pre-TG3-G run
    data = client.get(f"/api/get-results?task_id={task_id}").json()
    assert data["status"] == "success"
    assert data["mode"] is None
