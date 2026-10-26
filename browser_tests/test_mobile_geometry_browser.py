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
        assert page.locator("#gear-step").is_hidden()
        assert page.locator("#enh-card").is_hidden()
        assert page.locator("#log-card").is_hidden()
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
        assert neck.locator(".vrow").count() > 0
        assert page.locator("#enh-card").is_visible()
        assert page.locator("#log-card").is_visible()
        pressed = page.locator(".vrow[aria-pressed=true]")
        assert pressed.count() > 0
        assert pressed.count() == page.locator(".vrow .tag.eq").count()
        button_heights = page.locator("main button:not(.cand):not(.row-x), .runbar button:not(.cand)").evaluate_all(
            "els => els.filter(el => !el.hidden && el.getBoundingClientRect().height > 0).map(el => [el.id, el.className, el.getBoundingClientRect().height])"
        )
        assert button_heights and max(row[2] for row in button_heights) - min(row[2] for row in button_heights) <= 1, button_heights

        session = page.context.new_cdp_session(page)
        session.send(
            "Emulation.setSafeAreaInsetsOverride",
            {"insets": {"top": 0, "left": 0, "bottom": 34, "right": 0}},
        )
        page.evaluate(
            "() => new Promise(resolve => requestAnimationFrame(() => "
            "requestAnimationFrame(resolve)))"
        )
        # t_d671cd7c directive 5: the fixed bottom run bar is gone; the setup
        # bar is a static first card (mobile) so scrolling never hides controls
        # under a tall sticky overlay.
        assert page.locator(".runbar").evaluate("el => getComputedStyle(el).position") == "static"
        # directive 5: bar first, gear below it; footer metadata last in document order.
        runbar_box = page.locator(".runbar").bounding_box()
        gear_box = page.locator("#gear-step").bounding_box()
        footmeta_box = page.locator(".footmeta").bounding_box()
        assert runbar_box and gear_box and runbar_box["y"] < gear_box["y"], (runbar_box, gear_box)
        assert footmeta_box and runbar_box and footmeta_box["y"] > runbar_box["y"]

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
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


@pytest.mark.parametrize("width, height", [(320, 700), (390, 844)])
def test_mobile_slot_navigation_and_runbar_clearance(app_url, width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(app_url, wait_until="networkidle")
        assert page.locator("#gear-step").is_hidden()
        assert page.locator("#enh-card").is_hidden()
        assert page.locator("#log-card").is_hidden()
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
        assert page.locator("#gear-step").is_hidden()
        assert page.locator("#enh-card").is_hidden()
        assert page.locator("#log-card").is_hidden()
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
            # t_d671cd7c directive 5: desktop bar is main's sticky top card.
            assert page.locator(".runbar").evaluate("el => getComputedStyle(el).position") == "sticky"
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


@pytest.mark.parametrize("width", [430, 850])
def test_runbar_selectors_have_tokenized_vertical_clearance(app_url, width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 477}, device_scale_factor=1)
        page.goto(app_url, wait_until="networkidle")
        assert page.evaluate("innerWidth") == width
        fight = page.locator("#fight-style").bounding_box()
        compare = page.locator("#compare-mode").bounding_box()
        assert fight and compare
        gap = compare["y"] - (fight["y"] + fight["height"])
        token_gap = page.locator("html").evaluate(
            "el => parseFloat(getComputedStyle(el).getPropertyValue('--gap-xs'))"
        )
        assert gap >= token_gap, {"width": width, "gap": gap, "required": token_gap}
        browser.close()


@pytest.fixture(scope="module")
def config_app_url(tmp_path_factory):
    """t_d671cd7c: a server whose config.json is the shipped example, so the
    gem/enchant columns render real entries in geometry checks."""
    import json
    base_dir = tmp_path_factory.mktemp("config-browser-app")
    # The app serves static assets and loads config.json relative to its CWD
    # (= ROOT), so the season config rides a gitignored ROOT/config.json that
    # this fixture owns for its lifetime (worktrees carry no user config.json).
    config_path = ROOT / "config.json"
    created = not config_path.exists()
    config = json.loads((ROOT / "examples" / "config.example.json").read_text(encoding="utf-8"))
    if created:
        config_path.write_text(json.dumps(config), encoding="utf-8")
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
    log = (base_dir / "uvicorn.log").open("w")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.web.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(80):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            process.terminate()
            pytest.fail("uvicorn did not start: " + (base_dir / "uvicorn.log").read_text()[-2000:])
        yield f"http://127.0.0.1:{port}/"
    finally:
        process.terminate()
        process.wait(timeout=10)
        if created:
            config_path.unlink(missing_ok=True)


@pytest.mark.parametrize("width, height", [(320, 660), (430, 844), (1440, 900)])
def test_top_runbar_gem_enchant_columns_and_chevron_fit(config_app_url, width, height):
    """t_d671cd7c directives 3/4/5/7: top run bar above the gear grid, gem
    stat columns + enchant slot columns, normalized chevron inside the
    selects, and no horizontal overflow at phone/tablet/desktop widths."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.goto(config_app_url, wait_until="networkidle")
        page.locator("#addon-input").evaluate(
            "(el, value) => { el.value = value; "
            "el.dispatchEvent(new Event('input', {bubbles:true})); }",
            FIXTURE.read_text(),
        )
        page.locator("#btn-parse-addon").click()
        page.locator("#gear-grid .slotsec").first.wait_for(state="visible", timeout=15000)
        page.locator('#enh-card .enh-columns .enh-entry').first.wait_for(
            state="visible", timeout=15000)

        # directive 5: run bar under the header, above the gear grid.
        # (the parse transition smooth-scrolls main; wait it out, then pin
        # instant scrollTop=0 — document order is only meaningful from there)
        page.wait_for_timeout(600)
        page.evaluate("() => { const m = document.querySelector('main');"
                      " m.style.scrollBehavior = 'auto'; m.scrollTop = 0 }")
        page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        assert page.evaluate("document.querySelector('main').scrollTop") == 0
        runbar = page.locator(".runbar").bounding_box()
        gear = page.locator("#gear-step").bounding_box()
        assert runbar and gear and runbar["y"] + runbar["height"] <= gear["y"] + 1, (runbar, gear)

        # directive 7: chevron INSIDE the control; selects share height, in-bar.
        for sel in ("#fight-style", "#compare-mode"):
            box = page.locator(sel).bounding_box()
            style = page.locator(sel).evaluate(
                "el => { const s = getComputedStyle(el); return [s.appearance,"
                " parseFloat(s.paddingRight), s.backgroundImage.slice(0, 4)]; }"
            )
            assert box and box["width"] > 0, sel
            assert style[0] == "none", (sel, style)
            assert float(style[1]) >= 20.0, (sel, style)
            assert style[2] == "url(", (sel, style)
            assert box["x"] + box["width"] <= runbar["x"] + runbar["width"] + 1, (sel, box, runbar)
        heights = page.locator("#fight-style, #compare-mode").evaluate_all(
            "els => els.map(el => el.getBoundingClientRect().height)")
        assert abs(heights[0] - heights[1]) <= 1, heights

        # directive 3: gems split into one column per secondary stat.
        gem_legends = page.locator('[data-enh-group="Gems"] .enh-columns legend') \
            .evaluate_all("els => els.map(el => el.textContent)")
        for needed in ("Mastery", "Critical Strike", "Versatility", "Haste"):
            assert needed in gem_legends, gem_legends
        # directive 2: grade-colored names on every entry; the Wowhead icon
        # anchor exists in the DOM (the img itself self-removes when the icon
        # proxy is offline, so the anchor is the network-independent fact).
        names = page.evaluate(
            "() => [...document.querySelectorAll('#enh-card .enh-entry .name')]"
            ".map(n => n.className)")
        assert names and all(" q-" in cls for cls in names), names[:6]
        assert page.locator("#enh-card a.enhancement-name-link").count() > 0
        # directive 4: enchantment columns headed by slot names.
        enchant_legends = page.locator('[data-enh-group="Enchantments"] .enh-columns legend') \
            .evaluate_all("els => els.map(el => el.textContent)")
        needed_slots = {"Legs", "Boots", "Chest", "Helm", "Rings", "Shoulders", "Weapon"}
        assert needed_slots <= set(enchant_legends), enchant_legends
        # directive 7: icon/name columns aligned across the rows of a column.
        misaligned = page.evaluate("""() => {
          const grids = [...document.querySelectorAll('#enh-card .enh-columns')];
          let off = 0;
          for (const grid of grids) for (const col of grid.children) {
            const rows = [...col.querySelectorAll('.enh-entry')];
            if (rows.length < 2) continue;
            const base = rows[0].getBoundingClientRect();
            for (const row of rows) {
              const r = row.getBoundingClientRect();
              const icon = row.querySelector('a') ?? row.querySelector('img');
              const chip = row.querySelector('.choice-chip');
              if (icon && Math.abs(icon.getBoundingClientRect().x - base.x) > 1) off++;
              /* 26px icon column + 4px --gap-xs */
              if (Math.abs(chip.getBoundingClientRect().x - (base.x + 30)) > 1) off++;
              if (Math.abs(r.x - base.x) > 1) off++;
            }
          }
          return off;
        }""")
        assert misaligned == 0, misaligned

        # responsive columns + no horizontal overflow.
        layout = page.evaluate("""() => {
          const grid = document.querySelector('#enh-card .enh-columns');
          return [getComputedStyle(grid).gridTemplateColumns.split(' ').length, grid.clientWidth];
        }""")
        if width <= 430:
            assert layout[0] == 1, (width, layout)
        else:
            assert layout[0] >= 2, (width, layout)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        browser.close()
