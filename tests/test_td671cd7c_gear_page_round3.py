"""t_d671cd7c — gear-page round 3 (source contract, t_76a0ceb9 style).

Pins the six user directives + the binding addenda:
1 footer nav removed (links live in the header profile dropdown)
2 gem/enchant entries: icon anchor + grade-colored name
3 gem stat columns + backend `stat` validation + example values
4 enchantment slot columns
5 run controls moved to the top (runbar above the gear grid)
6 profile dropdown (aria-expanded, keyboard-wired, existing hrefs)
7 select chevron normalization + aligned entry columns
+ addendum 3: 'Start over' label, hidden at rest
+ addendum 4: Armory band above the gear grid (#armory-import exists, and
  paste.js collapse/reset toggling is wired to a real element)
+ version 1.4.2-dev.1 and cache-bust sweep.
"""
import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
APP_HTML = (STATIC / "app.html").read_text()
SETUP_CSS = (STATIC / "css" / "setup.css").read_text()
TOKENS_CSS = (STATIC / "css" / "tokens.css").read_text()
ENH_JS = (STATIC / "js" / "setup" / "enhancements.js").read_text()
PASTE_JS = (STATIC / "js" / "setup" / "paste.js").read_text()
SETUP_JS = (STATIC / "js" / "pages" / "setup.js").read_text()
EXAMPLE = json.loads(
    (Path(__file__).resolve().parents[1] / "examples" / "config.example.json").read_text()
)


def _footmeta():
    return re.search(r'<div class="footmeta">.*?</div>', APP_HTML, re.S).group(0)


def test_directive_1_footer_nav_buttons_removed():
    foot = _footmeta()
    assert "<a " not in foot
    assert 'id="app-version"' in foot and 'id="draft-note"' in foot  # metadata kept


def test_directive_2_entries_render_like_gear_rows():
    assert "enhancementEntry(group," in ENH_JS
    assert "q-${qualityOf(entry?.quality ?? 4).cls}" in ENH_JS  # grade-colored name, default epic
    assert "appendWowheadLink(row, entry, name)" in ENH_JS  # icon anchor appended after the button
    assert ".enh-entry{display:grid;grid-template-columns:26px minmax(0,1fr)" in SETUP_CSS
    assert ".enh-entry .name{display:block" in SETUP_CSS


def test_directive_3_gem_stat_columns_and_schema():
    for label in ("Mastery", "Critical Strike", "Versatility", "Haste", "Other"):
        assert f"'{label}'" in ENH_JS
    assert "GEM_STAT_ORDER" in ENH_JS
    assert "gemStatLabel(gem)" in ENH_JS
    # meta gems + extra test sockets keep their own groups
    assert "addFieldset(bodies.Gems, 'Meta gems')" in ENH_JS
    assert "addFieldset(bodies.Gems, 'Extra test sockets')" in ENH_JS
    # example config carries sensible stat values for every non-PvP gem
    stats = {g.get("stat") for g in EXAMPLE["gems"]["standard"] if "Heliotrope" not in g["name"]}
    assert stats <= {"mastery", "crit", "versatility", "haste"}
    assert len(stats) == 4, stats


def test_directive_4_enchantment_slot_columns():
    assert 'addFieldset(enchantColumns, ENCHANT_SLOT_LABELS[slot]' in ENH_JS
    for label in ("Helm", "Shoulders", "Chest", "Legs", "Boots", "Rings", "Weapon"):
        assert f"'{label}'" in ENH_JS
    assert ".enh-columns{display:grid;grid-template-columns:" in SETUP_CSS
    assert "repeat(auto-fit,minmax(190px,1fr))" in SETUP_CSS


def test_directive_5_runbar_is_the_top_card():
    assert APP_HTML.index('class="runbar runbar-top"') < APP_HTML.index('id="import-details"')
    assert APP_HTML.index('class="runbar runbar-top"') < APP_HTML.index('id="gear-grid"')
    for host in ("btn-run", "btn-open-run", "fight-style", "compare-mode", "combo-count",
                 "selected-item-count", "btn-review", "workflow-status"):
        assert f'id="{host}"' in APP_HTML, host
    assert ".runbar-top{position:static" in TOKENS_CSS
    assert ".runbar{position:fixed;inset:auto 0 0 0" in TOKENS_CSS  # results action bar untouched
    assert "@media (min-width:851px){main>.runbar-top{position:sticky;top:0" in SETUP_CSS


def test_directive_6_profile_dropdown_replaces_footer_nav():
    assert 'aria-haspopup="true"' in APP_HTML and 'aria-expanded="false"' in APP_HTML
    assert 'id="btn-profile-menu"' in APP_HTML and 'id="profile-menu-panel"' in APP_HTML
    assert '<a href="history">Run history</a>' in APP_HTML
    assert '<a href="./">My runs</a>' in APP_HTML
    assert '<a href="logout">Sign out</a>' in APP_HTML  # existing GET /logout surface
    assert "aria-expanded" in SETUP_JS and "Escape" in SETUP_JS  # keyboard accessible
    assert ".profile-menu-panel{position:absolute;right:0;top:calc(100% + 6px)" in TOKENS_CSS


def test_directive_7_select_chevron_normalized_everywhere():
    assert "select{appearance:none;-webkit-appearance:none;padding-right:28px" in TOKENS_CSS
    # the shorthand no longer resets the chevron:
    assert ".fight-style-select{background-color:" in TOKENS_CSS
    assert ".armory-field .armory-region-select{background-color:" in TOKENS_CSS
    assert ".slot-sort-select{padding-right:26px}" in SETUP_CSS


def test_addendum_3_start_over_hidden_at_rest():
    assert "Start over" in APP_HTML and "New export" not in APP_HTML
    assert 'id="btn-new-export" class="btn-ghost" hidden' in APP_HTML
    # collapse shows it, reset hides it (behavior unchanged)
    assert "getElementById('btn-new-export').hidden = false" in PASTE_JS
    assert "getElementById('btn-new-export').hidden = true" in PASTE_JS


def test_addendum_4_armory_band_above_the_gear_grid():
    assert 'id="armory-import"' in APP_HTML
    assert APP_HTML.index('id="armory-import"') < APP_HTML.index('id="gear-grid"')
    # paste.js toggling now targets a real element
    assert "getElementById('armory-import')" in PASTE_JS


def test_version_and_cache_bust_sweep():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert 'version = "1.4.2-dev.1"' in pyproject
    assert "css/tokens.css?v=red3-5" in APP_HTML
    assert "css/setup.css?v=red3-18" in APP_HTML
    assert "css/run.css?v=red3-5" in APP_HTML
    assert "js/pages/setup.js?v=red3-6" in APP_HTML
    assert "import { renderWorkflow } from '../pages/setup.js?v=red3-6';" in PASTE_JS
    for page in ("history.html", "login.html", "register.html", "results.html"):
        assert "tokens.css?v=red3-5" in (STATIC / page).read_text(), page
