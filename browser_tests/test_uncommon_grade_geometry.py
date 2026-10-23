"""Focused browser regression for long gear-grade labels."""

from playwright.sync_api import sync_playwright

from test_mobile_geometry_browser import app_url, FIXTURE


def test_uncommon_grade_and_item_level_do_not_overlap(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(app_url, wait_until="networkidle")
        page.locator("#addon-input").evaluate(
            "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }",
            FIXTURE.read_text(),
        )
        page.locator("#btn-parse-addon").click()
        page.locator("#gear-grid .slotsec").first.wait_for()
        assert page.locator('link[href*="tokens.css"]').get_attribute("href").endswith("tokens.css?v=red3-3")
        assert page.locator(":root").evaluate("el => getComputedStyle(el).getPropertyValue('--q-uncom').trim()")
        page.evaluate("""() => {
          const rows = document.querySelector('#gear-grid .slotsec[data-slot="main_hand"] .rows');
          const row = document.createElement('button');
          row.className = 'cand vrow';
          row.innerHTML = '<span class="ic">T</span><span class="name q-uncommon">Tarnished Dawnlit Shortsword</span>' +
            '<span class="il num">253</span><span class="grd uncommon">Uncommon</span>' +
            '<span class="d eq">base</span>';
          rows.append(row);
        }""")
        row = page.locator('#gear-grid .slotsec[data-slot="main_hand"] .vrow').last
        name = row.locator('.name')
        grade = row.locator('.grd').bounding_box()
        ilvl = row.locator('.il').bounding_box()
        assert name.evaluate("el => getComputedStyle(el).color === getComputedStyle(el.parentElement.querySelector('.grd')).color")
        assert grade and ilvl and grade["x"] - (ilvl["x"] + ilvl["width"]) > 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        bounds = row.bounding_box()
        assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
        browser.close()
