"""t_9040b457 — QA round 3 bugfix source contracts.

Three defects from QA t_f3b29a14, fixed at root cause:
- t_ca74bb9c: Start over left stale run-bar counters (16/15) and selections.
- t_6732b9de: sticky .runbar-top/#qj hide section headings; main (the overflow
  scroller) had no scroll-padding-top.
- t_66acf0b2: .slot-sort-select `background:` shorthand clobbered the global
  select chevron's background-image.

CSS/JS source-contract style per the t_e3af01b6 precedent; the measured
geometry and computed-style assertions live in
browser_tests/test_t9040b457_qa3_browser.py.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
SETUP_CSS = (STATIC / "css" / "setup.css").read_text()
TOKENS_CSS = (STATIC / "css" / "tokens.css").read_text()
STATE_JS = (STATIC / "js" / "core" / "state.js").read_text()
PASTE_JS = (STATIC / "js" / "setup" / "paste.js").read_text()
RUNBAR_JS = (STATIC / "js" / "setup" / "runbar.js").read_text()

# t_ca74bb9c: the layers QA measured (16 combos / 15 items, gem/enchant
# selections retained) — the reset must cover every one of them.
SELECTION_FIELDS = (
    "selectedItems", "selectedEnchants", "selectedGems", "selectedMetaGems",
    "selectedAugurnium", "equippedEnchants", "equippedGems", "gearUpgrades",
    "extraSockets", "voidforgedItems", "gearTouchedByUser", "addedItems",
)


def _reset_body():
    body = STATE_JS.split("export function resetCharacterState() {", 1)[1]
    return body.split("\nexport function initializeSelections", 1)[0]


def test_start_over_clears_every_selection_layer():
    reset = _reset_body()
    for field in SELECTION_FIELDS:
        assert f"state.{field} = " in reset, field
    # the Start over handler runs the reset before repainting the counters
    handler = PASTE_JS.split("btn-new-export').addEventListener", 1)[1]
    assert "resetCharacterState()" in handler
    assert handler.index("resetCharacterState()") < handler.index("updateSummary()")


def test_initialize_selections_reuses_the_same_reset():
    init = STATE_JS.split("export function initializeSelections() {", 1)[1]
    assert init.lstrip().startswith("resetCharacterState();")


def test_run_bar_counters_zero_out_without_a_character():
    # estimateCombinations()'s baseline combo of 1 must not survive Start over
    assert "!state.parsedData ? 0 :" in RUNBAR_JS


def test_main_scroller_carries_scroll_padding_below_the_sticky_stack():
    # root cause: scroll-padding is per-scroll-container; html's never reaches
    # the main scroller (t_6732b9de). CSS floor + JS sync with the fluid bar.
    main_rule = SETUP_CSS.split("main{", 1)[1].split("}", 1)[0]
    assert "overflow-y:auto" in main_rule
    assert "scroll-padding-top:12px" in main_rule
    # runbar.js re-measures the sticky stack (fluid bar + sticky margin,
    # measured from main's scrollport top) on every relevant resize
    assert "scrollPaddingTop" in RUNBAR_JS
    assert "ResizeObserver" in RUNBAR_JS
    assert "getBoundingClientRect" in RUNBAR_JS
    # the sticky selectors two sibling tests pin verbatim stay untouched
    assert "main>.runbar-top{position:sticky;top:0" in SETUP_CSS
    assert ".runbar-top{position:static" in TOKENS_CSS


def test_slot_sort_group_uses_background_color_not_the_shorthand():
    rule = SETUP_CSS.split(".slot-sort-select,.slot-toggle-all,.slot-add-toggle{", 1)[1]
    rule = rule.split("}", 1)[0]
    assert "background-color:var(--surface)" in rule
    assert "background:var(" not in rule  # the shorthand that reset the chevron


def test_global_select_chevron_rule_survives_page_wide():
    # the tokens.css chevron must stay the LAST select background in the
    # cascade (it follows the input/select/textarea background shorthand)
    assert 'select{appearance:none;-webkit-appearance:none;padding-right:28px' in TOKENS_CSS
    assert 'background-image:url("data:image/svg+xml' in TOKENS_CSS
    assert TOKENS_CSS.index("input,select,textarea{") < TOKENS_CSS.index("select{appearance:none")
    # no CSS rule targeting a select sets a `background:` shorthand AFTER the
    # chevron rule in the cascade (tokens.css chevron onward, then setup.css,
    # which is linked second) — that class of clobber killed slot-sort.
    # Comments are stripped first: the word "select" in prose must not
    # implicate a rule (e.g. the .vrow button row inside a dropdown).
    tail = (TOKENS_CSS[TOKENS_CSS.index("select{appearance:none"):] + SETUP_CSS)
    tail = re.sub(r"/\*.*?\*/", "", tail, flags=re.S)
    for chunk in tail.split("}"):
        if "{" not in chunk:
            continue
        selector = chunk.split("{", 1)[0]
        if re.search(r"select\b", selector):
            assert "background:" not in chunk.split("{", 1)[1], selector
    # chevron room stays reserved on the slot-sort controls
    assert ".slot-sort-select{padding-right:26px}" in SETUP_CSS
