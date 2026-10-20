"""Fighting style selector: UI wiring and generated simc directives.

Design (documented for review):
- ``single_boss`` is the default and fixes the fight at 5 minutes:
  ``duration=300`` (no ``time_to_die`` — the boss must not die early), appended
  after the base profile so it overrides any duration the addon export carried.
- ``dungeon_slice`` models a short Mythic+ pull: ``time_to_die=30`` fixes the
  kill time and ``duration=30`` caps the fight length, both appended after the
  base profile so they override any duration the addon export carried.
"""

import os
import sys

from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import app
from static_assets import read_css, read_js, resp  # t_94a15fe3 split pins

client = TestClient(app)

BASE_PAYLOAD = {
    "char_class": "warrior",
    "char_name": "Test",
    "base_profile": "warrior=Test\nsimulate 10000\n",
    "equipped_gear": {"trinket1": "id=2,ilevel=250"},
    "selected_items": {"trinket": ["id=2,ilevel=250", "id=3,ilevel=252"]},
    "selected_enchants": {},
    "selected_gems": [],
    "gear_upgrades": {},
    "voidforged_items": {},
    "extra_sockets": {},
}


def _generate(**overrides):
    response = client.post("/api/generate-simc", json={**BASE_PAYLOAD, **overrides})
    assert response.status_code == 200, response.text
    with open(response.json()["file_path"], encoding="utf-8") as f:
        return f.read()


def test_dungeon_slice_emits_short_fight_directives():
    generated = _generate(fight_style="dungeon_slice")
    assert "# fighting style: dungeon slice" in generated
    assert "duration=30\n" in generated
    assert "time_to_die=30\n" in generated
    # Directives must come after the base profile so they override the export.
    assert generated.index("simulate 10000") < generated.index("time_to_die=30")
    # ...and before the copy blocks so every candidate inherits them.
    assert generated.index("time_to_die=30") < generated.index('copy="Test_trinket_0')


def test_default_fight_style_emits_single_boss_5min_directive():
    generated = _generate()
    assert "# fighting style: single boss (5 min fixed fight)\n" in generated
    assert "duration=300\n" in generated
    # Directive must come after the base profile so it overrides the export.
    assert generated.index("simulate 10000") < generated.index("duration=300")
    # ...and before the copy blocks so every candidate inherits it.
    assert generated.index("duration=300") < generated.index('copy="Test_trinket_0')
    # Boss must not die early, and this must not be the dungeon-slice directives.
    # (Check "duration=30\n" — plain "duration=30" is a prefix of "duration=300".)
    assert "time_to_die" not in generated
    assert "duration=30\n" not in generated


def test_single_boss_matches_default_output():
    assert _generate(fight_style="single_boss") == _generate()


def test_unknown_fight_style_is_rejected():
    response = client.post("/api/generate-simc", json={**BASE_PAYLOAD, "fight_style": "raid_booter"})
    assert response.status_code == 422
    assert "fight_style" in response.json()["detail"]


def test_run_bar_shows_fighting_style_dropdown_with_two_choices():
    html = client.get("/").text
    assert 'id="fight-style"' in html
    assert '<option value="single_boss" selected>Single boss (5 min)</option>' in html
    assert '<option value="dungeon_slice">Dungeon slice</option>' in html
    # Exactly two choices.
    select_block = html.split('id="fight-style"', 1)[1].split("</select>", 1)[0]
    assert select_block.count("<option") == 2


def test_app_js_sends_fight_style_and_regenerates_on_change():
    js = resp(read_js()).text
    assert "fight_style: document.getElementById('fight-style')?.value || 'single_boss'" in js
    assert "getElementById('fight-style').addEventListener('change', selectionChanged)" in js
