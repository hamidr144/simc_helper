"""Regression for fixed Results action-bar clearance on short desktop screens."""

from playwright.sync_api import sync_playwright

from test_mobile_geometry_browser import app_url


def test_results_content_clears_fixed_runbar_at_1280x577(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 577})
        page.goto(f"{app_url}/results", wait_until="networkidle")
        page.locator("#results-runbar").evaluate("el => el.hidden = false")
        page.locator("#recos-slot").evaluate("el => el.hidden = false")
        page.locator("#recos-slot .upgrid").evaluate("el => el.style.height = '700px'")

        metrics = page.evaluate("""() => {
          const bar = document.querySelector('#results-runbar').getBoundingClientRect();
          return {documentHeight: document.documentElement.scrollHeight,
            viewportHeight: innerHeight, barTop: bar.top};
        }""")
        assert metrics["documentHeight"] > metrics["viewportHeight"], metrics

        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(50)
        content = page.locator(".footmeta").bounding_box()
        bar_top = page.locator("#results-runbar").bounding_box()["y"]
        assert content and content["y"] + content["height"] <= bar_top, {"content": content, "bar_top": bar_top}
        assert page.locator("#btn-review-gear").is_visible()
        assert page.locator("#btn-apply-all-bar").is_visible()
        browser.close()