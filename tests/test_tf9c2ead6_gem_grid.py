"""t_f9c2ead6 — gem panel 5-column grid incl. meta gems (source contract).

Pins:
1 the gem panel (standard + meta gems) renders into ONE grid with the
  gem-grid class; the meta-gem fieldset is folded in.
2 dense 5-column desktop layout with the app's standard collapse widths
  (3 columns at <=850px, 2 at <=430px, 1 at <=320px), with the grid capped
  at the densest group's chip count (--gem-cols) so a sparse 4-per-group
  stat config fills its tracks edge-to-edge (review round 1: no full-height
  empty 5th column).
3 groups flow inline inside the grid (display:contents + full-row head) so
  an unclassifiable 'Other'-only config fills every column — no giant
  whitespace column.
4 toggle / equipped / single-select-meta semantics ride the same chips.
5 the enh-search filter loop also hides the new div.enh-group gem groups.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
APP_HTML = (STATIC / "app.html").read_text()
SETUP_CSS = (STATIC / "css" / "setup.css").read_text()
ENH_JS = (STATIC / "js" / "setup" / "enhancements.js").read_text()


def test_gem_grid_five_columns_with_standard_collapse():
    # default 5 columns; --gem-cols (JS density cap) collapses unused tracks
    assert ".gem-grid{grid-template-columns:repeat(var(--gem-cols,5),minmax(0,1fr))" in SETUP_CSS
    assert "@media (max-width:850px){.gem-grid{grid-template-columns:repeat(3,minmax(0,1fr))" in SETUP_CSS
    assert "@media (max-width:430px){.gem-grid{grid-template-columns:repeat(2,minmax(0,1fr))" in SETUP_CSS
    assert "@media (max-width:320px){.gem-grid{grid-template-columns:minmax(0,1fr)}" in SETUP_CSS


def test_grid_collapses_unused_tracks_on_sparse_configs():
    # review round 1: the shipped 4/4/4/4+meta shape rendered a full-height
    # empty 5th grid track; JS caps --gem-cols at the densest group's chip
    # count (max 5) so every desktop track is filled.
    assert "grid.style.setProperty('--gem-cols'" in ENH_JS
    assert "Math.min(5, Math.max(" in ENH_JS
    # cap rides the custom property, AFTER groups are built (the density
    # computation must not sit at grid creation — children are empty there)
    cap = ENH_JS.index("grid.style.setProperty('--gem-cols'")
    assert cap > ENH_JS.index("addGemGroup(grid, 'Meta gems')")


def test_all_gem_groups_share_one_grid_meta_folded_in():
    assert "grid.classList.add('gem-grid')" in ENH_JS
    assert "addGemGroup(grid, label)" in ENH_JS
    assert "addGemGroup(grid, 'Meta gems')" in ENH_JS
    assert "addFieldset(bodies.Gems, 'Meta gems')" not in ENH_JS
    # stat-grouped configs AND 'Other'-only configs share the same flow:
    # groups are display:contents, heads span the row, chips are grid items.
    assert ".gem-grid .enh-group{display:contents}" in SETUP_CSS
    assert ".gem-grid .enh-group-head{grid-column:1/-1" in SETUP_CSS


def test_gem_semantics_unchanged():
    # toggle / equipped / single-select-meta ride the untouched chip builder
    assert "if (selected) state.selectedGems.add(id);" in ENH_JS
    assert "else state.selectedGems.delete(id)" in ENH_JS
    assert "state.equippedGems.has(id)" in ENH_JS
    assert "state.selectedMetaGems.clear()" in ENH_JS
    assert "if (selected) state.selectedMetaGems.add(id);" in ENH_JS
    assert "group.querySelectorAll('button.choice-chip')" in ENH_JS
    assert "if (equipped) {" in ENH_JS


def test_search_filter_covers_gem_groups():
    assert "querySelectorAll('fieldset, .enh-group')" in ENH_JS
    assert "querySelectorAll('legend, .enh-group-head')" in ENH_JS
