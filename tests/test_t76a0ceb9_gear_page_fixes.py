"""t_76a0ceb9 — 12 Gear-page directives: cheap source/layout contracts.

Tested here (source contracts): 1,2,3,5,6,7(no-eqc),9,10,11.
Visual-only (screenshot review, not assertable from source): 4 (spacing
rhythm rides existing .workflow-step token margins), 8 row-height equality
(one shared .vrow rule IS the structural guarantee, asserted via the
no-eqc pins), 12 button size-class normalization.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "web" / "static"


def _read(p):
    return (STATIC / p).read_text(encoding="utf-8")


APP_HTML = _read("app.html")
SETUP_JS = _read("js/setup/gear.js")
RUN_JS = _read("js/setup/run.js")
ENH_JS = _read("js/setup/enhancements.js")
ITEMS_JS = _read("js/core/items.js")
WOWHEAD_JS = _read("js/core/wowhead.js")
SETUP_CSS = _read("css/setup.css")
RUN_CSS = _read("css/run.css")


def test_directives_1_2_3_instruction_text_removed():
    for gone in ("every candidate stays visible", "nothing is ever auto-selected",
                 "visit each equipment slot while holding Shift", "run /cmc",
                 "=== Begin SimC ===", "public characters only"):
        assert gone not in APP_HTML, f"helper text must be removed: {gone}"


def test_directive_5_enhancements_and_log_hidden_until_import():
    assert 'id="enh-card" hidden' in APP_HTML
    assert 'id="log-card" hidden' in APP_HTML
    assert 'id="gear-step" hidden' in APP_HTML
    pages = _read("js/pages/setup.js")
    assert "getElementById('gear-step').hidden = false" in pages
    assert "getElementById('enh-card').hidden = false" in pages
    assert "getElementById('log-card').hidden = false" in pages
    paste = _read("js/setup/paste.js")
    assert "getElementById('enh-card').hidden = true" in paste
    assert "paste-guide" not in APP_HTML


def test_directive_6_run_opens_as_own_view():
    assert 'id="run-view"' in APP_HTML
    assert "export function openRunView" in RUN_JS
    assert "openRunView();" in RUN_JS  # runSimulation opens the view
    assert "btn-close-runview" in APP_HTML
    assert "btn-open-run" in APP_HTML
    # mobile: the view bar padding exists in the 430px block
    assert ".runview-in{padding:var(--gap-sm) 12px 24px}" in RUN_CSS


def test_directives_7_8_no_oversized_equipped_card():
    assert "itemRow('eqc'" not in SETUP_JS and "eqBlock" not in SETUP_JS
    assert "itemRow('eqc'" not in _read("js/core/ui.js")
    assert ".eqc{" not in SETUP_CSS and ".eqc,.vrow{" not in SETUP_CSS
    # equipped items are ordinary rows with the equipped tag, selected state
    assert "eq: !variant.rank && !variant.voidforged && equippedSet.has(item)" in SETUP_JS
    assert "if (d.eq) return '<span class=\"tag eq\">equipped</span> '" in _read("js/core/ui.js")
    # seeds selections from equipped only (directive 7 first render)
    state = _read("js/core/state.js")
    assert "new Set(items.filter(item => equipped.has(item)))" in state


def test_directive_9_ring_and_trinket_merged_sections():
    assert "label: 'Ring', slot: 'finger'" in ITEMS_JS
    assert "label: 'Trinket', slot: 'trinket'" in ITEMS_JS
    assert "label: 'Ring 1'" not in ITEMS_JS and "label: 'Trinket 1'" not in ITEMS_JS
    assert "key: 'finger1'" not in ITEMS_JS and "key: 'trinket2'" not in ITEMS_JS
    # payload contract stays frozen: sections ride the pool keys
    assert "key: 'finger', label: 'Ring', slot: 'finger'" in ITEMS_JS
    assert "Array.from(items)" in _read("js/setup/payload.js")


def test_directive_10_trio_open_by_default_split_three():
    for group in ("Gems", "Enchantments", "Augurnium"):
        assert f'data-enh-group="{group}" open' in APP_HTML
    assert "if (augurnium.length)" in ENH_JS
    assert 'data-enh-group="Augurnium" open' in APP_HTML
    assert "searchOpened" not in ENH_JS


def test_directives_4_12_spacing_and_button_dimensions_use_shared_tokens():
    assert ".import,.workflow-step{margin-top:var(--gap-lg)}" in SETUP_CSS
    assert "main button:not(.cand),\n.runbar button:not(.cand){min-height:36px;padding:6px 12px" in SETUP_CSS
    assert ".runbar button.runbtn{min-height:36px" in SETUP_CSS
    assert "main button.row-x{min-height:28px" in SETUP_CSS


def test_directive_11_enhancements_get_gear_pattern_tooltip_links():
    assert 'data-wowhead="iconsize=large"' in WOWHEAD_JS
    assert "api/item-icon/" in WOWHEAD_JS
    assert "appendWowheadLink(group, enchant, name)" in ENH_JS
    assert "appendWowheadLink(group, gem, name)" in ENH_JS
    assert "appendWowheadLink(group, entry, name)" in ENH_JS
