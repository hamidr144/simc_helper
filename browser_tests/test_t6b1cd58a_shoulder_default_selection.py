"""t_6b1cd58a browser regression: equipped 321 shoulder row must render
selected by default — and a rank pick must never leave a slot section with
zero selected rows (the invisible-pick desync).

Mechanism (user screenshot: 'Pauldrons of the Consecrated Flame' 321
EQUIPPED, Epic, unselected, '1 candidate'): the shoulder is 321 = hero 6/6
(top of the hero ladder; myth 2/6 ambiguity) and is NOT ascension-eligible
in Midnight S2, so a rank pick at the ladder top expands ZERO rank rows.
variantMatches keys every row on pickedRank, so the item's only row (the
base/equipped row) renders unselected while the pick lives on invisibly —
surviving fresh imports through the 30-day draft (both addon-paste and
Armory imports restore it via applyDraftToState).
"""
import json

import pytest
from playwright.sync_api import expect, sync_playwright

from test_mobile_geometry_browser import FIXTURE, app_url

SHOULDER_ITEM = (
    ",id=271463,enchant_id=8001,bonus_id=6652/13440/13694/13697/12846,"
    "redirected_base_stats=251138"
)


def _open_gear(page, url):
    page.goto(url, wait_until="networkidle")
    page.locator("#addon-input").evaluate(
        "(el, value) => { el.value = value; "
        "el.dispatchEvent(new Event('input', {bubbles:true})); }",
        FIXTURE.read_text(),
    )
    page.locator("#btn-parse-addon").click()
    page.locator("#sec-shoulder .vrow").first.wait_for(state="visible", timeout=15000)
    # the parse transition fires scrollIntoView({behavior:'smooth'}); let it
    # settle before geometry-sensitive clicks (t_d671cd7c suite lesson).
    page.wait_for_timeout(700)


def _ghost_sections(page):
    # Every section showing an equipped row must show at least one selected
    # row — a section with an equipped row and zero pressed rows is the
    # invisible-pick desync the user reported.
    return page.evaluate("""() => [...document.querySelectorAll('#gear-grid .slotsec')]
        .filter(sec => sec.querySelector('.rows .vrow .tag.eq')
            && ![...sec.querySelectorAll('.rows .vrow')]
                 .some(r => r.getAttribute('aria-pressed') === 'true'))
        .map(sec => sec.dataset.slot)""")


def _equipped_row(page):
    row = page.locator('#sec-shoulder .vrow:has(.tag.eq)')
    expect(row).to_have_count(1)
    return row.first


def test_equipped_shoulder_selected_on_fresh_import(app_url):
    # DoD 1: after a fresh import the equipped shoulder row renders selected
    # by default on first render, same as every other slot.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, app_url)
        base = _equipped_row(page)
        expect(base).to_have_attribute("aria-pressed", "true")
        assert "sel" in (base.get_attribute("class") or "").split()
        assert _ghost_sections(page) == []
        browser.close()


def test_rank_pick_never_leaves_section_without_selected_row(app_url):
    # The fresh parse grades the shoulder myth 2/6 (export bonus 12846):
    # rank rows Myth 3/6..6/6 exist. Picking a rank consumes that rung
    # (seasonFallbackRanks expands rank+1..top), so the clicked row vanishes;
    # pre-fix the equipped base row then renders unselected with NOTHING
    # pressed in the section — the reported symptom at first click.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, app_url)
        page.locator('#sec-shoulder .vrow[data-rank="3"]').click()
        base = _equipped_row(page)
        expect(base).to_have_attribute("aria-pressed", "true", timeout=5000)
        assert _ghost_sections(page) == []
        # Toggle-back stays coherent: clicking the selected base row clears
        # the pick and the item (single-candidate slot).
        base.click()
        expect(page.locator("#sec-shoulder .vrow[aria-pressed='true']")).to_have_count(0)
        browser.close()


def test_hero6_regrade_keeps_equipped_shoulder_selected(app_url):
    # The user's exact live flow: a rank pick at the ladder top (Myth 6/6),
    # then a FRESH re-import of the same character. The grade resolves to
    # hero 6/6 (server bonus_track rule for the 321 ambiguity — stubbed as
    # /api/wowhead-upgrades would answer live), which expands zero rank
    # rows on the ascension-ineligible shoulder. The draft-restored pick must
    # not leave the equipped row unselected on first render.
    hero6 = json.dumps({
        "status": "success",
        "gear_upgrades": {"shoulder": {SHOULDER_ITEM: {"track": "hero", "rank": 6, "item_level": 321}}},
        "two_handed": {},
        "qualities": {},
    })
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        _open_gear(page, app_url)
        # Expand the +N fold (hidden rows refuse real Playwright clicks —
        # expand via the chip's own click handler), then pick the top rung
        # (Myth 6/6) on the equipped shoulder.
        page.evaluate("""() => {
            const chip = document.querySelector('#sec-shoulder .rows .fold');
            if (chip) chip.click();
        }""")
        page.locator('#sec-shoulder .vrow[data-rank="6"]').click()
        page.wait_for_timeout(1200)  # persistDraft debounce (800 ms)
        page.route("**/api/wowhead-upgrades", lambda route: route.fulfill(
            status=200, content_type="application/json", body=hero6))
        _open_gear(page, app_url)  # fresh import; draft restored (same char)
        base = _equipped_row(page)
        expect(base).to_have_attribute("aria-pressed", "true", timeout=5000)
        assert _ghost_sections(page) == []
        browser.close()
