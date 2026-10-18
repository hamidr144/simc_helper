"""TG3-D (t_9fdd2c1b): compact gear-selection rows per TG3-A contract.

Structural pins only — the measurable gates G1-G6 are browser-verified on
dev :8001 (handoff screenshots + JSON); these tests guard the markup/contract
invariants that the compaction must not regress.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
CSS = (STATIC / "style.css").read_text()
APP_JS = (STATIC / "app.js").read_text()
APP_HTML = (STATIC / "app.html").read_text()


def test_gear_card_is_a_dense_grid_row():
    # §3.1: one 44px grid row, padding 6px 12px, no overflow clipping
    # (overflow:hidden would clip the anchored upgrade popover on a row).
    block = CSS.split(".gear-card {", 1)[1].split("}", 1)[0]
    assert "display: grid;" in block
    assert "grid-template-columns: minmax(0, 1fr) auto auto auto;" in block
    assert "min-height: 44px;" in block
    assert "padding: 6px 12px;" in block
    assert "overflow: hidden" not in block


def test_slot_conflict_line_and_collapse_keep_the_row_layout():
    # §3.4: the inline conflict line spans the row; un-hiding a collapsed
    # card restores the grid row, not the pre-redesign block stack.
    assert ".gear-card .gear-conflict { grid-column: 1 / -1; }" in CSS
    assert (".slot-items.is-expanded .gear-card.is-collapsed,\n"
            ".gear-card.is-collapsed.is-selected { display: grid; }") in CSS


def test_ilvl_prefix_replaces_item_level_label():
    # §3.1: same data, compact "ilvl N" pair; the old stacked label is gone.
    assert '<span class="gear-card-slot"><span>ilvl</span>' in APP_JS
    assert "<span>Item level</span>" not in APP_JS
    # 390px shrink chain: the name-inside-anchor must be allowed to shrink
    # (stale flex:0 0 32px from .item-select-row caused min-content overflow).
    link_block = CSS.split(".gear-card-info .item-icon-link {", 1)[1].split("}", 1)[0]
    assert "flex: 0 1 auto;" in link_block
    assert "min-width: 0;" in link_block
    name_block = CSS.split(".gear-card-info .item-icon-link .gear-card-name {", 1)[1].split("}", 1)[0]
    assert "flex: 1 1 0;" in name_block  # zero-basis: kills min-content overflow


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
    bar = CSS.split(".run-bar {", 1)[1].split("}", 1)[0]
    assert "padding: 10px 24px;" in bar
    assert ".run-bar .workflow-status { margin-top: 0; min-height: 0; min-width: 0; flex: 1; font-size: 13px; }" in CSS


def test_group_chrome_gaps_match_contract():
    assert "#gear-grid {\n  display: grid;\n  gap: 12px;" in CSS
    assert ".slot-group {\n  border-top: 1px solid var(--border-hairline);\n  padding-top: 10px;" in CSS
    assert "grid-template-columns: 1fr;\n  gap: 8px;" in CSS
