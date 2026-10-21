"""TG3-D (t_9fdd2c1b): compact gear-selection rows per TG3-A contract.

Structural pins only — the measurable gates G1-G6 are browser-verified on
dev :8001 (handoff screenshots + JSON); these tests guard the markup/contract
invariants that the compaction must not regress.
"""

from pathlib import Path
from static_assets import read_css, read_js, resp  # t_94a15fe3 split pins

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
CSS = read_css()
APP_JS = read_js()
ENHANCEMENTS_JS = (STATIC / "js/setup/enhancements.js").read_text()
APP_HTML = (STATIC / "app.html").read_text()


def test_setup_mobile_content_reserves_measured_runbar_height():
    setup_css = (STATIC / "css" / "setup.css").read_text()
    setup_js = (STATIC / "js" / "pages" / "setup.js").read_text()
    mobile = setup_css.split("@media (max-width:430px){", 1)[1].split("}", 1)[0]
    assert "var(--setup-runbar-height, 0px)" in mobile
    assert "env(safe-area-inset-bottom)" in mobile
    assert "ResizeObserver(reserve)" in setup_js
    assert "getBoundingClientRect().height" in setup_js


def test_gear_card_is_a_dense_grid_row():
    # RED-3 (v11 §M10): equipped card and candidate row are ONE shared grid —
    # icon | name(minmax 0) | ilvl | grade | delta; selection is conveyed by
    # the button's pressed state, not a decorative square.
    block = CSS.split(".eqc,.vrow{display:grid", 1)[1].split("}", 1)[0]
    assert "grid-template-columns:var(--col-ic) minmax(0,1fr) var(--col-il) var(--col-grd) var(--col-d)" in block
    assert "overflow: hidden" not in block and "overflow:hidden" not in block
    assert ".gear-card" not in CSS  # v11 retired the tile component


def test_slot_conflict_line_and_collapse_keep_the_row_layout():
    # §3.4: the inline conflict line spans the row; un-hiding a collapsed
    # card restores the grid row, not the pre-redesign block stack.
    assert ".gear-conflict" in CSS  # v11: inline line under the section head
    # v11 collapse = [hidden] attribute rows + native fold chip (never <div
    # onclick>); un-hiding restores the row via the shared grid display.
    assert "[hidden]{display:none !important}" in CSS
    assert ".rows>.fold" in CSS


def test_ilvl_prefix_replaces_item_level_label():
    # §3.1: same data, compact "ilvl N" pair; the old stacked label is gone.
    # RED-3: compact ilvl number column (the row header carries the label);
    # the old stacked Item-level pair is gone.
    assert 'class="il num"' in APP_JS
    assert "<span>Item level</span>" not in APP_JS
    # 390px shrink chain: name column is minmax(0,1fr) and ellipsized.
    assert "minmax(0,1fr)" in CSS
    name_block = CSS.split(".vrow .name{", 1)[1].split("}", 1)[0]
    assert "overflow:hidden" in name_block
    assert "text-overflow:ellipsis" in name_block


def test_run_bar_helper_moved_to_title_and_sr_only():
    # §3.2 (leader ruling Q2): verbatim helper text survives machine-
    # readable; no always-visible <small> remains on the compare control.
    assert "<small>Combination mode simulates" not in APP_HTML
    assert 'aria-describedby="compare-mode-help"' in APP_HTML
    help_text = ("Combination mode simulates every selected item of every "
                 "slot together, like Raidbots Top Gear.")
    assert f'<span id="compare-mode-help" class="sr-only">{help_text}</span>' in APP_HTML
    assert help_text in APP_HTML.split('id="compare-mode"', 1)[1].split(">", 1)[0]


def test_run_bar_compaction_rules():
    # §3.2: padding 14->10 vertical, status stays shrink-safe for the
    # two-line conflict aggregate (TG3-C §3.4 real estate).
    # RED-3: fixed .runbar inner line stays compact; status stays shrink-safe.
    bar = CSS.split(".runbar .in{", 1)[1].split("}", 1)[0]
    assert "padding:10px 20px" in bar
    status = CSS.split(".workflow-status{", 1)[1].split("}", 1)[0]
    assert "min-width:0" in status
    assert "font-size:13px" in status


def test_run_bar_status_clamped_to_two_lines():
    # t_5c33fefb (bug t_da6227d7): the slot-conflict / generate-error aggregate
    # must never grow the sticky run-bar past the G2 110px cap — 2-line clamp
    # + ellipsis; full text stays in textContent (aria-live) and is mirrored
    # to title by setWorkflowStatus.
    status = CSS.split(".workflow-status{", 1)[1].split("}", 1)[0]
    assert "-webkit-line-clamp:2" in status
    assert "line-clamp:2" in status
    assert "overflow:hidden" in status


def test_group_chrome_gaps_match_contract():
    # RED-3: >=900px splits the section list into two balanced columns;
    # sections never break across them. Spacing is tokenized.
    assert "#gear-grid{columns:2" in CSS
    assert ".slotsec{break-inside:avoid}" in CSS
    assert ".rows{margin-top:var(--gap-sm)" in CSS
    # extra sockets moved into the enhancements panel (decision D-6); the
    # per-slot group footer is gone with the tile era.
    assert ".slot-group" not in CSS
    assert 'extra socket' in ENHANCEMENTS_JS
