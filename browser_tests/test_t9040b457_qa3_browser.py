"""t_9040b457 — browser acceptance for the QA round 3 bugfixes.

Geometry/scroll-padding regression for t_6732b9de at 1280 and 800 (the
defect card's acceptance formula: after scrollIntoView/anchor jump,
legend.rect.top > .runbar-top/#qj rect.bottom), the computed-style chevron
assertion for t_66acf0b2 (getComputedStyle(select).backgroundImage must
carry the SVG on EVERY select incl. slot-sort), and the Start over counter
reset for t_ca74bb9c (0/0, run disabled, import band re-opened).
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "addon_export_canonical.simc"


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    base_dir = tmp_path_factory.mktemp("qa3-browser-app")
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
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.web.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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


def _import_character(page, url):
    page.goto(url, wait_until="networkidle")
    page.locator("#addon-input").evaluate(
        "(el, value) => { el.value = value; "
        "el.dispatchEvent(new Event('input', {bubbles:true})); }",
        FIXTURE.read_text(),
    )
    page.locator("#btn-parse-addon").click()
    page.locator("#gear-step").wait_for(state="visible", timeout=15000)


def _scroll_first_legend(page):
    """Open the first enhancement section that has a rendered legend
    (fieldset legend, else summary), scrollIntoView it, and return the
    measured rects (defect card repro)."""
    return page.evaluate("""() => {
      const sec = [...document.querySelectorAll('.enh-section')]
        .find((s) => s.querySelector('fieldset legend') || s.querySelector('summary'));
      if (!sec) return null;
      sec.open = true;
      const legend = sec.querySelector('fieldset legend') || sec.querySelector('summary');
      sec.scrollIntoView();
      const bar = document.querySelector('.runbar-top').getBoundingClientRect();
      const qj = document.querySelector('.qj').getBoundingClientRect();
      return {
        legendTop: legend.getBoundingClientRect().top,
        barBottom: bar.bottom,
        barSticky: getComputedStyle(document.querySelector('.runbar-top')).position,
        qjBottom: qj.bottom,
        scrollPad: getComputedStyle(document.querySelector('main')).scrollPaddingTop,
      };
    }""")


def test_start_over_resets_counters_and_selections(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 577})
        _import_character(page, app_url)
        # Start over must clear a POPULATED state — the canonical fixture is
        # baseline-equip (combo estimate floor 1), so drive real selections
        # first: select-all on every slot section.
        toggles = page.locator("#gear-grid .slotsec .slot-toggle-all")
        assert toggles.count() >= 1
        for i in range(toggles.count()):
            toggles.nth(i).click(timeout=2000)
        page.wait_for_timeout(800)
        items = int(page.locator("#selected-item-count").inner_text().replace(",", ""))
        assert items >= 2, f"select-all should leave a populated counter (got {items})"
        # Start over's "visible" semantics = the hidden attribute is off
        # (the band collapses on import, R7 ruling D-4; QA's CDP flow acts on
        # the control via JS click — a real click can't target a collapsed
        # details body).
        page.locator("#btn-new-export").evaluate("el => el.click()")
        assert page.locator("#combo-count").inner_text() == "0"
        assert page.locator("#selected-item-count").inner_text() == "0"
        assert not page.locator("#btn-run").is_enabled()
        assert page.locator("#btn-new-export").evaluate("el => el.hidden")
        # hidden-until-gear state: views cleared, import band re-opened
        # (t_ca74bb9c acceptance)
        assert page.locator("#gear-step").is_hidden()
        assert page.locator("#enh-card").is_hidden()
        assert page.locator("#log-card").is_hidden()
        assert page.locator("#addon-input").is_visible()
        assert page.locator("#import-details").evaluate("el => el.open")
        # a subsequent import starts clean
        _import_character(page, app_url)
        assert int(page.locator("#selected-item-count").inner_text()) >= 1
        browser.close()


def test_headings_clear_the_sticky_runbar_at_1280(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 577})
        _import_character(page, app_url)
        page.locator("#gear-step").wait_for(state="visible")
        m = _scroll_first_legend(page)
        assert m, "fixture renders at least one legend-bearing enh-section"
        assert int(m["scrollPad"].rstrip("px")) >= 12
        assert m["legendTop"] > m["barBottom"], (
            f"legend top {m['legendTop']} must clear sticky runbar bottom {m['barBottom']}")
        # anchor jump through a #qj pill must land the same way
        page.locator("#qj a").first.click()
        page.wait_for_timeout(400)
        anchor_top = page.evaluate("""() => {
          const target = document.querySelector(
            document.querySelector('#qj a').getAttribute('href'));
          const bar = document.querySelector('.runbar-top').getBoundingClientRect();
          return {top: target.getBoundingClientRect().top, barBottom: bar.bottom};
        }""")
        assert anchor_top["top"] >= anchor_top["barBottom"] - 1, (
            f"anchor target top {anchor_top['top']} vs runbar bottom {anchor_top['barBottom']}")
        browser.close()


def test_headings_clear_the_sticky_qj_strip_at_800(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 477})
        _import_character(page, app_url)
        page.locator("#gear-step").wait_for(state="visible")
        m = _scroll_first_legend(page)
        assert m, "fixture renders at least one legend-bearing enh-section"
        assert m["legendTop"] > m["qjBottom"], (
            f"legend top {m['legendTop']} must clear sticky #qj bottom {m['qjBottom']}")
        browser.close()


def test_every_select_on_the_page_keeps_the_chevron(app_url):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 577})
        _import_character(page, app_url)
        page.locator("#gear-step").wait_for(state="visible")
        report = page.evaluate("""() => {
          const selects = [...document.querySelectorAll('select')];
          const bad = selects.filter((s) => {
            const cs = getComputedStyle(s);
            return cs.appearance === 'none' && !cs.backgroundImage.includes('svg');
          }).map((s) => s.className + '#' + s.id);
          return {total: selects.length, bad,
                  slots: selects.filter((s) => s.classList.contains('slot-sort-select')).length};
        }""")
        assert report["slots"] >= 1, "slot-sort selects must exist after import"
        assert report["bad"] == [], f"selects without chevron: {report['bad']}"
        browser.close()
