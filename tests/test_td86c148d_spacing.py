"""t_d86c148d — panel spacing + border-overflow root fixes (source contract).

CSS clearance source contract, not live viewport geometry: the live audit ran
in the PR (Playwright geometry sweep at 1280/850/430). These pins keep the
shared card-step rules from regressing to unstyled summaries/cardbodies and
keep the deduped CSS a single source of truth.
"""
from pathlib import Path

STATIC = Path(__file__).parent.parent / "src/web/static"
SETUP_CSS = (STATIC / "css/setup.css").read_text()
TOKENS_CSS = (STATIC / "css/tokens.css").read_text()
APP_HTML = (STATIC / "app.html").read_text()


def test_stacked_card_steps_use_token_rhythm():
    # one margin rule for the import/enhancements/log cards (token gap, not 0)
    assert ".import,.workflow-step{margin-top:var(--gap-lg)}" in SETUP_CSS


def test_all_card_summaries_get_disclosure_clearance():
    # Enhancements summary shares the import summary language: native marker
    # hidden, ▸/▾ glyph inset 16px inside the border, not on it.
    assert ".import>summary,.workflow-step>summary{cursor:pointer;padding:12px 16px" in SETUP_CSS
    assert ".workflow-step>summary::-webkit-details-marker{display:none}" in SETUP_CSS
    assert '.workflow-step[open]>summary::before{content:"▾ "}' in SETUP_CSS


def test_cardbody_padding_and_separator():
    assert ".import .cardbody,.workflow-step .cardbody{padding:var(--gap-md)}" in SETUP_CSS
    assert ".import>summary+.cardbody,.workflow-step>summary+.cardbody" in SETUP_CSS


def test_no_ad_hoc_margins_in_stack_area():
    for dead in ("margin:10px 0 0", "margin:10px 0 4px", "margin:0 0 10px",
                 "margin-bottom:8px", "margin:0 0 12px"):
        assert dead not in SETUP_CSS, dead


def test_dead_details_panel_rules_removed():
    # the D-4/D-6 importpanel/enhpanel rules targeted classes no page renders
    assert "details.importpanel" not in TOKENS_CSS
    assert "details.enhpanel" not in TOKENS_CSS


def test_setup_css_has_no_duplicate_rule_blocks():
    for selector in (".enh-section{", ".choice-chip{", ".slot-add-form{"):
        assert SETUP_CSS.count(selector) == 1, selector


def test_tokens_css_has_no_duplicate_rule_blocks():
    for selector in (".panel-card{", ".history-table{", ".diff-table{",
                     ".status-unknown{", ".armory-controls{", ".gear-conflict{",
                     ".error-panel{"):
        assert TOKENS_CSS.count(selector) == 1, selector


def test_cache_bust_and_inline_style_removal():
    assert "css/tokens.css?v=red3-4" in APP_HTML
    assert "css/setup.css?v=red3-17" in APP_HTML
    assert "css/run.css?v=red3-4" in APP_HTML
    assert 'class="run-actions" style=' not in APP_HTML
