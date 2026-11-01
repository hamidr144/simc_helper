"""t_38a21c87 browser regression: two gear/gem panel defects.

Defect 1 (maxed equipped row '+3 ilvl'): in two-equipment slots rowDelta
baselines against the weakest equipped item, so the stronger equipped
piece showed '+N ilvl' on its own row, reading like an upgrade offer.
Equipped rows now carry the 'base' label; ladder rows keep their deltas.

Defect 2 (Heliotrope gems never render): a name-substring PVP filter in
enhancements.js silently dropped the shipped config's standard Heliotrope
gems (the example config ships 35 standard + 4 meta; 32+4 rendered).
The filter is gone — every configured standard gem renders.
"""
import pytest
from playwright.sync_api import sync_playwright

from test_mobile_geometry_browser import FIXTURE, app_url, config_app_url

EXAMPLE_STANDARD = 35
EXAMPLE_META = 4


def _open_gear(page, url):
    page.goto(url, wait_until="networkidle")
    page.locator("#addon-input").evaluate(
        "(el, value) => { el.value = value; "
        "el.dispatchEvent(new Event('input', {bubbles:true})); }",
        FIXTURE.read_text(),
    )
    page.locator("#btn-parse-addon").click()
    page.locator("#gear-grid .slotsec").first.wait_for(state="visible", timeout=15000)


def test_equipped_rows_carry_base_label_not_upgrade_delta(app_url):
    # The fixture export equips two rings: Vile Alchemist's Band (328) and
    # Loa Worshiper's Band (331). Pre-fix the 331 row read '+3 ilvl' (the
    # two-equipment baseline is the weakest equipped, 328).
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, app_url)
        ring = page.locator('#gear-grid .slotsec[data-slot="finger"]')
        ring.locator(".vrow").first.wait_for()
        eq_rows = ring.locator(".vrow:has(.tag.eq)")
        assert eq_rows.count() == 2
        for row in eq_rows.all():
            assert row.locator(".d").inner_text().strip() == "base", row.inner_text()
            assert row.locator(".d.il-d").count() == 0
        maxed = eq_rows.filter(has_text="Loa Worshiper")
        assert maxed.count() == 1  # the 331 piece is present and labelled base
        # ladder rows are untouched (label-only fix): every non-equipped row
        # keeps its delta cell, none carries the equipped tag.
        plain = ring.locator(".vrow:not(:has(.tag.eq))")
        assert plain.count() > 0
        assert plain.evaluate_all("rows => rows.every(r => !!r.querySelector('.d'))")
        # single-equipment slot regression guard: the equipped neck row stays
        # 'base' too.
        neck_eq = page.locator("#sec-neck .vrow:has(.tag.eq) .d")
        assert neck_eq.count() == 1
        assert neck_eq.first.inner_text().strip() == "base"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


def test_all_configured_standard_gems_render(config_app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, config_app_url)
        gems_body = page.locator('#enhancement-options [data-enh-group="Gems"] .enh-body')
        chips = gems_body.locator(".enh-group .choice-chip")
        # every configured standard + meta gem renders as a chip
        assert chips.count() == EXAMPLE_STANDARD + EXAMPLE_META
        heliotrope = chips.filter(has_text="Heliotrope")
        assert heliotrope.count() == 3
        for name in ("Determined Heliotrope", "Cognitive Heliotrope", "Enduring Heliotrope"):
            assert chips.filter(has_text=name).count() == 1, name
        # stat grouping untouched: the stat-less Heliotrope entries land in
        # the 'Other' group, meta gems keep their own group and count.
        heads = gems_body.locator(".enh-group-head").all_inner_texts()
        assert "Other" in heads and "Meta gems" in heads
        assert gems_body.locator(".enh-group").filter(
            has_text="Meta gems").locator(".choice-chip").count() == EXAMPLE_META
        browser.close()
