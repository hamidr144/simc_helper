"""Focused browser regression for long gear-grade labels."""

from playwright.sync_api import sync_playwright

from test_mobile_geometry_browser import app_url, FIXTURE


def test_uncommon_grade_and_item_level_do_not_overlap(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(app_url, wait_until="networkidle")
        quality_lookup = {}

        def wowhead_quality(route):
            items = route.request.post_data_json["items_by_slot"]["main_hand"]
            item = next(item for item in items if "id=258951" in item and "bonus_id=13900" in item)
            quality_lookup["item"] = item
            route.fulfill(json={"status": "success", "gear_upgrades": {}, "two_handed": {}, "qualities": {"main_hand": {item: 2}}, "errors": []})

        page.route("**/api/wowhead-upgrades", wowhead_quality)
        page.locator("#addon-input").evaluate(
            "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }",
            FIXTURE.read_text(),
        )
        page.locator("#btn-parse-addon").click()
        page.locator("#gear-grid .slotsec").first.wait_for()
        assert page.locator('link[href*="tokens.css"]').get_attribute("href").endswith("tokens.css?v=red3-5")
        assert page.locator(":root").evaluate("el => getComputedStyle(el).getPropertyValue('--q-uncom').trim()")
        section = page.locator('#gear-grid .slotsec[data-slot="main_hand"]')
        section.locator('.fold').click()
        row = section.locator('.vrow').filter(has_text='Tarnished Dawnlit Shortsword')
        row.wait_for()
        row.locator('.name.q-uncommon').wait_for()
        assert "id=258951" in quality_lookup["item"] and "bonus_id=13900" in quality_lookup["item"]
        assert 'id=258951' in row.get_attribute('data-item')
        assert 'q-uncommon' in row.locator('.name').get_attribute('class')
        name = row.locator('.name')
        assert name.evaluate("el => { const probe = document.createElement('span'); probe.style.color = 'var(--q-uncom)'; document.body.append(probe); const expected = getComputedStyle(probe).color; probe.remove(); return getComputedStyle(el).color === expected; }")
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
