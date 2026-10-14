"""Fighting style selector: UI wiring and generated simc directives.

Design (documented for review):
- ``single_boss`` is the default and appends NOTHING, so profiles stay
  byte-identical to the pre-feature behaviour for existing users.
- ``dungeon_slice`` models a short Mythic+ pull: ``time_to_die=30`` fixes the
  kill time and ``duration=30`` caps the fight length, both appended after the
  base profile so they override any duration the addon export carried.
"""

import os
import sys

from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import app

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


def test_default_fight_style_keeps_behaviour_unchanged():
    generated = _generate()
    assert "time_to_die" not in generated
    assert "duration=30" not in generated
    assert "fighting style" not in generated


def test_single_boss_matches_default_output():
    assert _generate(fight_style="single_boss") == _generate()


def test_unknown_fight_style_is_rejected():
    response = client.post("/api/generate-simc", json={**BASE_PAYLOAD, "fight_style": "raid_booter"})
    assert response.status_code == 422
    assert "fight_style" in response.json()["detail"]


def test_run_bar_shows_fighting_style_dropdown_with_two_choices():
    html = client.get("/").text
    assert 'id="fight-style"' in html
    assert '<option value="single_boss" selected>Single boss</option>' in html
    assert '<option value="dungeon_slice">Dungeon slice</option>' in html
    # Exactly two choices.
    select_block = html.split('id="fight-style"', 1)[1].split("</select>", 1)[0]
    assert select_block.count("<option") == 2


def test_app_js_sends_fight_style_and_regenerates_on_change():
    js = client.get("/static/app.js").text
    assert "fight_style: document.getElementById('fight-style')?.value || 'single_boss'" in js
    assert "getElementById('fight-style').addEventListener('change', selectionChanged)" in js
