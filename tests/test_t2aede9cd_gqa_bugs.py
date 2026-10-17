"""Regression tests for QA task t_2aede9cd (GUI redesign verification).

Red before the fix, green after. String-pinning style follows
test_project_hardening.py (static-file assertions, no browser needed).

Only bug-1 (TC-RESP-390-DASH) ships here (fix card t_ab5b5f2e); bug-3
(TC-A11Y-TABLE, results.js) rides its own fix card t_dccc2343.
Bug-2 (TC-A11Y-TABSTOPS, t_16e4f177) adds the two tests below per the
leader-reconciled gate: enhancement <details> groups closed by default with
checked-count in the summary, and a skip link that reaches the run controls
in one activation. The raw visible-stop total stays browser-only (QA manual
procedure on t_16e4f177); these pins cover the two code-level causes.
Bug-3 (TC-A11Y-TABLE, fix card t_dccc2343) appends the results-table
accessible-name and th-scope pins below.
"""
from pathlib import Path
import re

CSS = Path("src/web/static/style.css").read_text()
APP_JS = Path("src/web/static/app.js").read_text()
RESULTS_JS = Path("src/web/static/results.js").read_text()


def _rule(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"rule not found: {selector}"
    return m.group(1)


def test_bug_t2aede9cd_1_slot_group_header_wraps_at_narrow_width():
    """BUG t_2aede9cd-1 (TC-RESP-390-DASH): .slot-group-header (title + count +
    sort select + select-all + add-by-ID buttons) never wraps, so with a parsed
    export its min-content width (~396px) overflows the 390px viewport —
    document.documentElement.scrollWidth 437 vs clientWidth 390, failing the
    design doc §7 zero-overflow acceptance gate on the dashboard."""
    body = _rule(CSS, ".slot-group-header")
    assert re.search(r"flex-wrap\s*:\s*wrap|flex-flow[^;]*wrap|flex-wrap\s*:\s*wrap-reverse", body), (
        ".slot-group-header must allow wrapping (flex-wrap: wrap) so its "
        "controls fit 390px viewports"
    )


def test_bug_t2aede9cd_2a_enhancement_groups_closed_by_default():
    """BUG t_16e4f177 (TC-A11Y-TABSTOPS, leader ruling): the design doc's
    open-if-checked clause (section.open = Boolean(group.querySelector
    ('input:checked'))) forced every enhancement group that held an
    equipped/checked candidate open on a real export, keeping 136 chip +
    wowhead-link stops permanently in the tab order (137 of 281 visible
    stops). Groups must start closed and show selection state in the
    summary label instead."""
    assert "section.open = Boolean" not in APP_JS, (
        "enhancement <details> groups must not auto-open on checked content"
    )
    assert "${checked} selected" in APP_JS, (
        "summary label must show the checked count (e.g. 'Gems · 2 selected')"
    )
    assert "group.addEventListener('change', renderLabel)" in APP_JS, (
        "summary label must update when a checkbox changes"
    )
    # Chrome >=131 hides closed <details> via paint containment on
    # ::details-content, leaving descendant rects non-zero — rect-based
    # tab-stop audits then count the closed groups. Pin the explicit hide.
    assert ".enh-section:not([open]) .enhancement-group" in CSS and "display: none" in (
        _rule(CSS, ".enh-section:not([open]) .enhancement-group")
    ), "closed enhancement groups must be display:none so rect-based tools agree"


def test_bug_t2aede9cd_2b_skip_link_reaches_run_controls_after_parse():
    """BUG t_16e4f177 (TC-A11Y-TABSTOPS, leader ruling): the skip link
    pointed at #main, which CONTAINS the gear list — activating it never
    skipped the 135 gear-panel stops. After the workflow renders it must
    target the run controls (#btn-run) so one activation moves focus past
    the gear list; New export restores the plain #main target."""
    assert "skipLink.href = '#btn-run'" in APP_JS, (
        "skip link must retarget to the run controls once the gear list exists"
    )
    assert "skipLink.href = '#main'" in APP_JS, (
        "New export must restore the plain skip-to-content target"
    )


def test_bug_t2aede9cd_3_results_table_accessible_name_and_scope():
    """BUG t_2aede9cd-3 (TC-A11Y-TABLE): the results comparison table has no
    <caption> and no aria-label, and its first <th> uses scope="#" (invalid
    value), failing design doc §6 item 7 (tables need caption/aria-label and
    valid th scope)."""
    assert re.search(r"<table[^>]*aria-label|<caption", RESULTS_JS), (
        "results.js must give the comparison table an accessible name "
        "(<caption> or aria-label on the <table>)"
    )
    assert 'scope="#"' not in RESULTS_JS and "scope='#'" not in RESULTS_JS, (
        'first table header must not use scope="#"'
    )
