"""Regression tests for QA task t_2aede9cd (GUI redesign verification).

Red before the fix, green after. String-pinning style follows
test_project_hardening.py (static-file assertions, no browser needed).

Only bug-1 (TC-RESP-390-DASH) ships here (fix card t_ab5b5f2e); bug-3
(TC-A11Y-TABLE, results.js) rides its own fix card t_dccc2343.
"""
from pathlib import Path
import re

CSS = Path("src/web/static/style.css").read_text()


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
