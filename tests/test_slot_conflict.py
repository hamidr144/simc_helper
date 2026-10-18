"""TG3-C slot-conflict guard: two-handed weapon + off-hand is rejected (400).

Live repro at :8001 (t_8d577e52): generation accepted a 2H main_hand
(id=251117, Wowhead inventorySlot 17) together with an off-hand shield; SimC
then silently dropped the shield, so the "upgrade" Combo reported the
baseline's DPS. The guard in generate-simc now rejects before any file write;
valid combinations (1H + off-hand, 2H alone, ranged selections) still
generate. Payload skeleton follows tests/test_generate_combinations.py.
"""

import os
import re
import sys

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
import web.main as master
from web.main import app, parse_wowhead_inventory_slot

client = TestClient(app)

EQUIPPED = {
    "head": "id=100,ilevel=250",
    "chest": "id=101,ilevel=250",
    "finger1": "id=102,ilevel=250",
    "finger2": "id=103,ilevel=250",
    "trinket1": "id=104,ilevel=250",
    "trinket2": "id=105,ilevel=250",
}

BASE_PAYLOAD = {
    "char_class": "warrior",
    "char_name": "Test",
    "base_profile": "warrior=Test\nsimulate 10000\n",
    "equipped_gear": EQUIPPED,
    "selected_items": {},
    "selected_enchants": {},
    "selected_gems": [],
    "gear_upgrades": {},
    "voidforged_items": {},
    "extra_sockets": {},
}

# Fake Wowhead inventorySlot map. 251117 -> 17 is the real Wowhead value from
# the live :8001 repro (verified via item=251117?xml); the other ids are fake
# fixtures exercising the non-17 branches (1H = 21, shield = 22, ranged = 15);
# unlisted ids resolve to None (unresolved-item fail-open).
INV_SLOTS = {251117: 17, 198426: 21, 120002: 22, 260567: 15}

TWO_HANDED = "id=251117,ilevel=298"
ONE_HANDED = "id=198426,ilevel=298"
SHIELD = "id=120002,ilevel=297"
RANGED = "id=260567,ilevel=298"


async def fake_inventory_slot(item):
    match = re.match(r'id=(\d+)', item)
    return INV_SLOTS.get(int(match.group(1))) if match else None


def _generate(selected_items):
    return client.post("/api/generate-simc", json={**BASE_PAYLOAD, "selected_items": selected_items})


@pytest.fixture()
def wowhead_slots():
    with patch("web.main.fetch_wowhead_inventory_slot", new=fake_inventory_slot):
        yield


# ---------------------------------------------------------------- rejection

def test_two_hand_main_hand_with_off_hand_is_rejected(wowhead_slots):
    response = _generate({"main_hand": [TWO_HANDED], "off_hand": [SHIELD]})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    # Names both conflicting slots and the offending item (spec: clear message).
    assert "main_hand" in detail and "off_hand" in detail
    assert "two-handed" in detail
    assert "251117" in detail
    assert "file_path" not in response.json()


def test_two_hand_off_hand_selection_is_rejected_symmetrically(wowhead_slots):
    response = _generate({"main_hand": [ONE_HANDED], "off_hand": [TWO_HANDED]})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "main_hand" in detail and "off_hand" in detail
    assert "251117" in detail


def test_rejection_writes_no_input_file(wowhead_slots):
    before = set(os.listdir(master.INPUTS_DIR))
    response = _generate({"main_hand": [TWO_HANDED], "off_hand": [SHIELD]})
    assert response.status_code == 400
    assert set(os.listdir(master.INPUTS_DIR)) == before


# ------------------------------------------------------- accepted combos

def test_one_hand_with_off_hand_still_generates(wowhead_slots):
    response = _generate({"main_hand": [ONE_HANDED], "off_hand": [SHIELD]})
    assert response.status_code == 200, response.text
    assert response.json()["combinations"] >= 1


def test_two_hand_alone_still_generates(wowhead_slots):
    response = _generate({"main_hand": [TWO_HANDED]})
    assert response.status_code == 200, response.text
    assert response.json()["combinations"] >= 1


def test_ranged_selection_is_not_treated_as_two_handed(wowhead_slots):
    # inventorySlot 15 (ranged) must not trip the guard next to an off-hand —
    # pins the check to id 17, not "any weapon-ish invslot".
    response = _generate({"main_hand": [RANGED], "off_hand": [SHIELD]})
    assert response.status_code == 200, response.text


def test_unresolved_item_fails_open(wowhead_slots):
    # Wowhead errors/unresolved ids must never block a valid selection.
    response = _generate({"main_hand": ["id=999999,ilevel=298"], "off_hand": [SHIELD]})
    assert response.status_code == 200, response.text


# ------------------------------------------------------------ parsing

def test_parse_wowhead_inventory_slot():
    xml = '<wowhead><item><inventorySlot id="17">Two-Hand</inventorySlot></item></wowhead>'
    assert parse_wowhead_inventory_slot(xml) == 17
    xml = '<wowhead><item><inventorySlot id="21">One-Hand</inventorySlot></item></wowhead>'
    assert parse_wowhead_inventory_slot(xml) == 21
    assert parse_wowhead_inventory_slot("<wowhead><item></item></wowhead>") is None
    assert parse_wowhead_inventory_slot('<wowhead><item><inventorySlot>?</inventorySlot></item></wowhead>') is None
    assert parse_wowhead_inventory_slot("not xml") is None


def test_upgrades_endpoint_lists_two_handed_items(monkeypatch):
    item = TWO_HANDED
    other = ONE_HANDED
    monkeypatch.setattr(master, "wowhead_invslot_cache", {
        master.wowhead_xml_url(item): 17,
        master.wowhead_xml_url(other): 21,
    })
    with patch("web.main.fetch_wowhead_upgrade", new=AsyncMock(return_value={"track": "myth", "rank": 6, "item_level": 289})):
        response = client.post("/api/wowhead-upgrades", json={"items_by_slot": {"main_hand": [item, other]}})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["two_handed"] == {"main_hand": [item]}
    assert data["gear_upgrades"]["main_hand"]  # upgrade mapping unchanged


# ------------------------------------------------------------ client hint

def test_app_js_surfaces_slot_conflict_hint():
    root = os.path.join(os.path.dirname(__file__), '..', 'src', 'web', 'static')
    with open(os.path.join(root, "app.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(root, "style.css"), encoding="utf-8") as f:
        css = f.read()
    assert "twoHandedItems.add(item)" in js          # hydrated from two_handed
    assert "renderSlotConflict" in js
    assert "setAttribute('role', 'alert')" in js     # inline hint is announced
    assert "gear-conflict" in js
    assert ".gear-conflict" in css                    # inline row grows the card only while shown
