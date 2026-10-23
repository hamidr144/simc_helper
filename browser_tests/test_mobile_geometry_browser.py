"""Browser-level mobile geometry regression for the populated setup workflow."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mobile_neck_export.simc"


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    base_dir = tmp_path_factory.mktemp("mobile-browser-app")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env.update(
        BASE_DIR=str(base_dir),
        REPORTS_DIR=str(base_dir / "reports"),
        AUTHENTICATION_ENABLED="false",
        PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / "src"), env.get("PYTHONPATH", ""))),
    )
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "src.web.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail("test app exited before becoming ready")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("test app did not become ready")
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("width", [320, 390])
def test_populated_mobile_setup_geometry_and_safe_area(app_url, width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        viewport_height = 700 if width == 320 else 844
        page = browser.new_page(viewport={"width": width, "height": viewport_height}, device_scale_factor=1)
        page.goto(app_url, wait_until="networkidle")
        page.locator("#addon-input").evaluate(
            "(el, value) => { el.value = value; "
            "el.dispatchEvent(new Event('input', {bubbles:true})); }",
            FIXTURE.read_text(),
        )
        page.locator("#btn-parse-addon").click()
        neck = page.locator("#sec-neck")
        neck.locator(".slot-toggle-all").wait_for(state="visible", timeout=15000)
        for selector in ("#sec-neck .slot-toggle-all", "#sec-neck .lock"):
            box = page.locator(selector).bounding_box()
            assert box and box["width"] > 0 and box["height"] > 0
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
            overlap, bounds = page.evaluate(
                "([selector, bar]) => {"
                "const a=document.querySelector(selector).getBoundingClientRect();"
                "const b=document.querySelector(bar).getBoundingClientRect();"
                "const m=document.querySelector('main').getBoundingClientRect();"
                "const visible={left:Math.max(a.left,m.left,0),right:Math.min(a.right,m.right,innerWidth),"
                "top:Math.max(a.top,m.top,0),bottom:Math.min(a.bottom,m.bottom,innerHeight)};"
                "return [visible.left < b.right && visible.right > b.left && "
                "visible.top < b.bottom && visible.bottom > b.top,"
                "{control:{top:a.top,bottom:a.bottom},visible,main:{top:m.top,bottom:m.bottom},"
                "runbar:{top:b.top,bottom:b.bottom}}]; }",
                [selector, ".runbar"],
            )
            assert not overlap, f"{selector}'s painted region intersects the runbar at initial scroll position: {bounds}"
        assert neck.locator(".lock").is_visible()
        assert neck.locator(".eqc, .vrow").count() > 0

        session = page.context.new_cdp_session(page)
        session.send(
            "Emulation.setSafeAreaInsetsOverride",
            {"insets": {"top": 0, "left": 0, "bottom": 34, "right": 0}},
        )
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => "
            "requestAnimationFrame(resolve)))"
        )
        padding = page.locator(".runbar").evaluate("el => getComputedStyle(el).paddingBottom")
        assert padding == "34px"

        main = page.locator("main")
        assert main.evaluate("el => el.scrollHeight > el.clientHeight")
        page.evaluate("() => document.querySelector('#sec-neck').scrollIntoView({block:'center'})")
        for selector in ("#sec-neck .slot-toggle-all", "#sec-neck .lock"):
            box = page.locator(selector).bounding_box()
            assert box and box["width"] > 0 and box["height"] > 0
            assert box["x"] >= 0 and box["x"] + box["width"] <= width
            assert not page.evaluate(
                "([selector, bar]) => {"
                "const a=document.querySelector(selector).getBoundingClientRect();"
                "const b=document.querySelector(bar).getBoundingClientRect();"
                "return a.left < b.right && a.right > b.left && "
                "a.top < b.bottom && a.bottom > b.top; }",
                [selector, ".runbar"],
            )

        page.evaluate("""() => new Promise(resolve => {
          const main = document.querySelector('main');
          let previous = main.scrollTop;
          let stableFrames = 0;
          const check = () => {
            if (main.scrollTop === previous) stableFrames++;
            else stableFrames = 0;
            previous = main.scrollTop;
            if (stableFrames >= 4) resolve();
            else requestAnimationFrame(check);
          };
          requestAnimationFrame(check);
        })""")
        main_box = main.bounding_box()
        page.mouse.move(width / 2, main_box["y"] + main_box["height"] / 2)
        # A single wheel event is intentionally bounded by browser input handling;
        # use repeated real wheel input rather than assigning scrollTop.
        metrics = main.evaluate("el => [el.scrollTop, el.clientHeight, el.scrollHeight]")
        for _ in range(40):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(50)
            metrics = main.evaluate("el => [el.scrollTop, el.clientHeight, el.scrollHeight]")
            if metrics[0] + metrics[1] >= metrics[2] - 1:
                break
        assert metrics[0] + metrics[1] >= metrics[2] - 1, metrics
        last_content = page.locator(".footmeta").bounding_box()
        runbar = page.locator(".runbar").bounding_box()
        assert last_content and runbar and last_content["y"] + last_content["height"] <= runbar["y"]
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


@pytest.mark.parametrize("width, height", [(320, 700), (390, 844)])
def test_mobile_slot_navigation_and_runbar_clearance(app_url, width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(app_url, wait_until="networkidle")
        page.locator("#addon-input").evaluate(
            "(el, value) => { el.value = value; "
            "el.dispatchEvent(new Event('input', {bubbles:true})); }",
            FIXTURE.read_text(),
        )
        page.locator("#btn-parse-addon").click()
        links = page.locator(".qjin a")
        links.last.wait_for(state="visible", timeout=15000)
        nav = page.locator(".qjin")
        nav_metrics = nav.evaluate("el => [el.clientWidth, el.scrollWidth]")
        assert nav_metrics[1] > nav_metrics[0], nav_metrics
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        nav.evaluate("el => el.scrollLeft = el.scrollWidth")
        last_link = links.last.bounding_box()
        nav_box = nav.bounding_box()
        assert last_link and nav_box and nav_box["x"] <= last_link["x"]
        assert last_link["x"] + last_link["width"] <= nav_box["x"] + nav_box["width"]
        status = page.locator(".workflow-status").bounding_box()
        assert status and status["y"] + status["height"] <= height - 8
        browser.close()


def test_populated_desktop_setup_rows_clear_runbar_initial_and_running(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page.goto(app_url, wait_until="networkidle")
        page.locator("#addon-input").evaluate(
            "(el, value) => { el.value = value; "
            "el.dispatchEvent(new Event('input', {bubbles:true})); }",
            FIXTURE.read_text(),
        )
        page.locator("#btn-parse-addon").click()
        page.locator("#sec-neck .vrow").first.wait_for(state="visible", timeout=15000)

        for running in (False, True):
            if running:
                page.locator("#run-progress").evaluate("el => el.hidden = false")
            assert page.locator("#btn-run").is_visible()
            assert page.locator(".runbar").evaluate("el => getComputedStyle(el).position") == "static"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            overlaps = page.evaluate("""() => {
              const bar = document.querySelector('.runbar').getBoundingClientRect();
              const main = document.querySelector('main').getBoundingClientRect();
              return [...document.querySelectorAll('.vrow')].filter(row => {
                const r = row.getBoundingClientRect();
                const top = Math.max(r.top, main.top, 0);
                const bottom = Math.min(r.bottom, main.bottom, innerHeight);
                return top < bottom && r.left < bar.right && r.right > bar.left &&
                  top < bar.bottom && bottom > bar.top;
              }).map(row => row.textContent.trim());
            }""")
            assert not overlaps, {"running": running, "overlapping_rows": overlaps}
            assert page.locator(".runbar").bounding_box()["y"] >= page.locator("main").bounding_box()["y"]
        browser.close()
