"""t_01eaf932 browser regression: equipped enchants/gems/meta must pre-select
after a fresh import (user report: "also enchants and gems should be also
auto selected that are already used").

The seed lives in the SHARED initializeSelections (js/core/state.js), so the
addon-paste flow and the Armory flow run the same loops. RED defects fixed
here, green only on this branch:

- the meta scan read ONLY the head line, so the equipped Eversong Diamond
  240983 carried by the neck (the live Midnight export shape, fixture
  mobile_neck_export.simc) was never pre-checked;
- the gem/enchant match never stripped pair-form socket/effect suffixes
  ("240892:0", "8017:8017"), so pair-form exports pre-selected nothing.

Armory coverage asserts the enchant seed via the committed real model.json
fixture; Blizzard's model.json reports gems: null on every slot (verified
against the live API 2026-11-01), so no gem data ships for the Armory path.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from test_mobile_geometry_browser import FIXTURE, config_app_url  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

# Enchant ids equipped by the paste fixture (mobile_neck_export.simc) whose
# ids the shipped example config lacks — the season overlay adds them.
PASTE_ENCHANTS = {
    "head": (8017, "Enchant Helm - Empowered Rune of Avoidance"),
    "shoulder": (8001, "Enchant Shoulders - Amirdrassil's Grace"),
    "chest": (7987, "Enchant Chest - Mark of the Worldsoul"),
    "legs": (8159, "Forest Hunter's Armor Kit"),
    "feet": (7963, "Enchant Boots - Lynx's Dexterity"),
    "finger": (7967, "Enchant Ring - Eyes of the Eagle"),
    "main_hand": (7983, "Enchant Weapon - Berserker's Rage"),
}
NECK_META = "240983"     # Indecipherable Eversong Diamond, socketed in the neck
STANDARD_GEM = "240892"  # flawless lapis worn by both rings


@pytest.fixture(scope="module")
def season_config_app_url(tmp_path_factory):
    """Example config + the season enchant entries the paste fixture wears.
    config.json loads relative to the server CWD, so the server runs from a
    tmp dir with src symlinked (sparse_gem_config_app_url precedent);
    ROOT/config.json stays untouched."""
    base_dir = tmp_path_factory.mktemp("season-config-app")
    config = json.loads((ROOT / "examples" / "config.example.json").read_text(encoding="utf-8"))
    for slot, (eid, name) in PASTE_ENCHANTS.items():
        config["enchantments"][slot] = [
            {"id": eid, "name": name, "wowhead_url": f"https://www.wowhead.com/enchant={eid}"}
        ]
    (base_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    os.symlink(ROOT / "src", base_dir / "src")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = os.environ.copy()
    env.update(
        BASE_DIR=str(base_dir),
        REPORTS_DIR=str(base_dir / "reports"),
        AUTHENTICATION_ENABLED="false",
        PYTHONPATH=os.pathsep.join((str(ROOT), str(ROOT / "src"))),
    )
    log = (base_dir / "uvicorn.log").open("w")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.web.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(base_dir), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:
        process.terminate()
        pytest.fail("uvicorn did not start: " + (base_dir / "uvicorn.log").read_text()[-2000:])
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        process.terminate()
        process.wait(timeout=10)


def _open_gear(page, url, text=None):
    page.goto(url, wait_until="networkidle")
    page.locator("#addon-input").evaluate(
        "(el, value) => { el.value = value; "
        "el.dispatchEvent(new Event('input', {bubbles:true})); }",
        text if text is not None else FIXTURE.read_text(),
    )
    page.locator("#btn-parse-addon").click()
    page.locator("#gear-grid .slotsec").first.wait_for(state="visible", timeout=15000)


def _selected(page, section, chip_id):
    # A chip shows its seeded state: pressed class inside its own section.
    return page.evaluate(
        "([section, chipId]) => { const el = document.querySelector("
        "`#enhancement-options [data-enh-group=\"${section}\"] "
        ".choice-chip[data-id=\"${chipId}\"]`); "
        "return el !== null && el.classList.contains('selected'); }",
        [section, chip_id],
    )


def _read_state(page):
    return page.evaluate("""async () => {
        const mod = await import('/static/js/core/state.js');
        const s = mod.state;
        return {
            selectedEnchants: Object.fromEntries(Object.entries(s.selectedEnchants)
                .filter(([k, v]) => v.size).map(([k, v]) => [k, [...v]])),
            selectedGems: [...s.selectedGems],
            selectedMetaGems: [...s.selectedMetaGems],
        };
    }""")


def _generate(page):
    page.evaluate("""async () => {
        const mod = await import('/static/js/setup/payload.js');
        await mod.generateInput(true);
    }""")


def test_paste_preselects_equipped_enchants_gems_and_neck_meta(season_config_app_url):
    # RED on dev tip: the neck-worn meta 240983 is never pre-selected
    # (the old scan reads only the head line).
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, season_config_app_url)
        state = _read_state(page)
        for slot, (eid, _name) in PASTE_ENCHANTS.items():
            assert state["selectedEnchants"].get(slot) == [str(eid)], slot
        assert state["selectedGems"] == [STANDARD_GEM]
        assert state["selectedMetaGems"] == [NECK_META]
        # the panel reflects the seeded state (chips pressed)
        for slot, (eid, _name) in PASTE_ENCHANTS.items():
            assert _selected(page, "Enchantments", str(eid)), f"{slot} {eid} chip"
        assert _selected(page, "Gems", STANDARD_GEM)
        assert _selected(page, "Gems", NECK_META)
        browser.close()


def test_pair_form_ids_preselect(config_app_url):
    # RED on dev tip: "240983:0"/"240892:1" socket-suffixed pair form matches
    # no configured id, so nothing pre-checks.
    pair_form = FIXTURE.read_text()
    pair_form = pair_form.replace("gem_id=240983/240892", "gem_id=240983:0/240892:1")
    pair_form = pair_form.replace("gem_id=240892", "gem_id=240892:0")
    assert "gem_id=240983:0" in pair_form
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, config_app_url, pair_form)
        state = _read_state(page)
        assert state["selectedGems"] == [STANDARD_GEM]
        assert state["selectedMetaGems"] == [NECK_META]
        assert _selected(page, "Gems", NECK_META)
        browser.close()


def test_head_meta_gem_preselects_plain_form(config_app_url):
    # The DoD's head case: meta worn on the HEAD, plain form. Dev tip passes
    # this — regression pin: the paperdoll scan keeps the head first.
    head_meta = re.sub(
        r"^(neck=.*?),gem_id=240983/240892",
        r"\1,gem_id=240892",
        FIXTURE.read_text(), flags=re.MULTILINE,
    )
    head_meta = re.sub(
        r"^head=(,id=271465)",
        r"head=\1,gem_id=240983",
        head_meta, flags=re.MULTILINE,
    )
    assert "head=,id=271465,gem_id=240983" in head_meta
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        _open_gear(page, config_app_url, head_meta)
        state = _read_state(page)
        assert state["selectedMetaGems"] == [NECK_META]
        assert _selected(page, "Gems", NECK_META)
        browser.close()


def test_auto_selection_payload_equals_manual_selection(season_config_app_url):
    # DoD: the auto-selected state serializes into the run payload exactly
    # like a manual selection (payload.js frozen — no payload-shape drift).
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        payloads = []
        page.on("request", lambda req: (
            req.method == "POST" and "generate-simc" in req.url
            and payloads.append(req.post_data)
        ))
        _open_gear(page, season_config_app_url)
        _generate(page)
        page.wait_for_function(
            "() => document.getElementById('combo-count').textContent.trim() !== '0'",
            timeout=15000)
        auto = payloads[-1]
        assert auto
        # manual: toggle the helm enchant chip off and back on — the final
        # state is the seeded state, rebuilt by hand.
        chip = page.locator(f'.choice-chip[data-id="{PASTE_ENCHANTS["head"][0]}"]')

        def chip_pressed(pressed):
            page.wait_for_function(
                "([chipId, pressed]) => document.querySelector(`.choice-chip[data-id=\"${chipId}\"]`)"
                ".classList.contains('selected') === pressed",
                arg=[str(PASTE_ENCHANTS["head"][0]), pressed], timeout=5000)

        chip.click()
        chip_pressed(False)
        chip.click()
        chip_pressed(True)
        page.wait_for_timeout(400)  # let the debounced auto-generation land
        payloads.clear()
        _generate(page)
        page.wait_for_timeout(500)
        assert payloads and payloads[-1] == auto
        browser.close()


def test_armory_import_preselects_equipped_enchants(season_config_app_url):
    # Armory flow through the committed REAL model.json fixture (Blizzard
    # live is not hit). The payload's gems: null on every slot — verified
    # against the live API 2026-11-01 — so enchants are all the Armory seed
    # can carry.
    sys.path.insert(0, str(ROOT))
    from src.core.armory import parse_armory_model

    payload = json.loads((ROOT / "tests" / "fixtures" / "armory"
                          / "armory_model_hamidriel_eu.json").read_text(encoding="utf-8"))
    parsed = parse_armory_model(payload)
    expected = {}
    for slot, (eid, _name) in PASTE_ENCHANTS.items():
        match = re.search(r"enchant_id=(\d+)", parsed["equipped_gear"].get(slot, ""))
        if match:
            expected[slot] = (eid, match.group(1))
    assert len(expected) >= 3
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("**/api/armory-load*",
                   lambda route: route.fulfill(status=200, content_type="application/json",
                                               body=json.dumps(parsed)))
        page.goto(season_config_app_url, wait_until="networkidle")
        page.locator("#armory-input").evaluate(
            "(el) => { el.value = 'https://worldofwarcraft.blizzard.com/en-gb/character/"
            "eu/draenor/Hamidriel'; el.dispatchEvent(new Event('input', {bubbles:true})); }")
        page.locator("#btn-armory-load").click()
        page.locator("#gear-grid .slotsec").first.wait_for(state="visible", timeout=15000)
        state = _read_state(page)
        for slot, (_eid, fixture_id) in expected.items():
            assert state["selectedEnchants"].get(slot) == [fixture_id], slot
            assert _selected(page, "Enchantments", fixture_id), f"{slot} {fixture_id} chip"
        browser.close()
