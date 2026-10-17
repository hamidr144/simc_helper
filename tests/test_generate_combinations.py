"""TG2-B combinations mode: shared product fn, budget cap, mode selector.

Design contract t_0fbfd0bd §4.1-4.2, gates §6 generation tests. TestClient
payload skeleton and file assertions follow tests/test_fight_style.py (assert
on the file at ``response.json()["file_path"]``).
"""

import os
import re
import sys

from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
import web.main as master
from cli.generate_input import build_combination_copies
from web.main import app

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
    # Pools: chest:2, head:2, trinket:2 -> C(2,2)=1 pair, finger:1 -> 4 combos.
    "selected_items": {
        "chest": ["id=201,ilevel=252", "id=202,ilevel=252"],
        "head": ["id=203,ilevel=252", "id=204,ilevel=252"],
        "trinket": ["id=205,ilevel=252", "id=206,ilevel=252"],
        "finger": ["id=207,ilevel=252"],
    },
    "selected_enchants": {},
    "selected_gems": [],
    "gear_upgrades": {},
    "voidforged_items": {},
    "extra_sockets": {},
}

COMBINATIONS = {"mode": "combinations"}


def _generate(**overrides):
    response = client.post("/api/generate-simc", json={**BASE_PAYLOAD, **overrides})
    assert response.status_code == 200, response.text
    with open(response.json()["file_path"], encoding="utf-8") as f:
        return response.json(), f.read()


def _copy_blocks(text):
    return re.split(r'(?=copy=")', text)[1:]


# ---------------------------------------------------------------- §6.1 product

def test_combinations_product_math_headers_and_estimate():
    data, text = _generate(mode="combinations")
    assert data["combinations"] == 4  # 2 chest x 2 head x 1 trinket pair x 1 finger
    assert data["mode"] == "combinations"
    # Stage-1-only lower bound: 4 * 200 iters / 1 it/s / 60 = 13.3 min.
    assert data["work_estimate_minutes"] == 13.3
    assert re.findall(r'copy="Test_Combo_(\d+),Test"', text) == ["1", "2", "3", "4"]
    blocks = _copy_blocks(text)
    assert len(blocks) == 4
    for block in blocks:
        assert ',Test"' in block  # every block clones the baseline actor
    joined = "".join(blocks)
    assert "trinket1=,id=205,ilevel=252" in joined
    assert "trinket2=,id=206,ilevel=252" in joined
    assert "finger1=,id=207,ilevel=252" in joined


def test_combinations_directive_before_copy_blocks():
    _, text = _generate(mode="combinations", fight_style="dungeon_slice")
    assert text.index("time_to_die=30") < text.index('copy="Test_Combo_1,Test"')


# ------------------------------------------------- §6.2 pair semantics (CLI)

def test_finger_and_trinket_pools_pair_unordered_no_self_pair():
    for slot, first_key, second_key in (("finger", "finger1", "finger2"),
                                        ("trinket", "trinket1", "trinket2")):
        blocks, n = build_combination_copies(
            {slot: ["id=1,ilevel=252", "id=2,ilevel=252", "id=3,ilevel=252"]},
            {},
            {first_key: "id=8,ilevel=250", second_key: "id=9,ilevel=250"},
            "X",
        )
        assert n == 3  # C(3,2), unordered, no self-pair
        pairs = set()
        for block in blocks:
            assert re.search(r'copy="X_Combo_\d,X"', block)
            first = re.search(rf"^{first_key}=(\S+)", block, re.M).group(1).lstrip(",")
            second = re.search(rf"^{second_key}=(\S+)", block, re.M).group(1).lstrip(",")
            assert first != second
            pairs.add(frozenset((first, second)))
        assert pairs == {
            frozenset(("id=1,ilevel=252", "id=2,ilevel=252")),
            frozenset(("id=1,ilevel=252", "id=3,ilevel=252")),
            frozenset(("id=2,ilevel=252", "id=3,ilevel=252")),
        }


# ------------------------------------------------------ §6.3 baseline skipping

def test_all_equipped_product_skipped_count_is_real_alternatives():
    data, text = _generate(**COMBINATIONS, selected_items={
        "chest": [EQUIPPED["chest"], "id=201,ilevel=252"],
    })
    # Products: (equipped chest) == baseline -> skipped; (201 chest) -> kept.
    assert data["combinations"] == 1
    assert len(_copy_blocks(text)) == 1
    assert "chest=,id=201,ilevel=252" in text


def test_empty_selection_zero_combinations_baseline_only():
    data, text = _generate(**COMBINATIONS, selected_items={})
    assert data["combinations"] == 0  # t_4485565b honest-zero contract intact
    assert "copy=" not in text
    assert "head=,id=100,ilevel=250" in text  # baseline gear block present


# ------------------------------------------------------------ §6.4 mode guards

def test_unknown_mode_is_rejected_outside_broad_try():
    response = client.post("/api/generate-simc", json={**BASE_PAYLOAD, "mode": "raid_booter"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "single_swap" in detail and "combinations" in detail


def test_enchants_multiply_pool_as_generate_variations_intends():
    # 2 items x 2 enchants -> 4 pool members -> 4 combinations.
    data, text = _generate(**COMBINATIONS,
                           selected_items={"chest": ["id=201,ilevel=252", "id=202,ilevel=252"]},
                           selected_enchants={"chest": [6611, 6612]})
    assert data["combinations"] == 4
    assert "enchant_id=6611" in text and "enchant_id=6612" in text
    assert len(_copy_blocks(text)) == 4


# ----------------------------------------------------------- §6.5 budget guard

def test_budget_cap_rejects_before_file_write(monkeypatch):
    monkeypatch.setattr(master, "TG_MAX_COMBINATIONS", 1)
    inputs_dir = master.INPUTS_DIR
    files_before = set(os.listdir(inputs_dir)) if os.path.isdir(inputs_dir) else set()
    record_before = dict(master.generated_inputs_by_user)

    response = client.post("/api/generate-simc", json={**BASE_PAYLOAD, **COMBINATIONS})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "4 combinations" in detail  # {count}
    assert "(budget 1)" in detail      # {budget}
    assert "one swap at a time" in detail
    files_after = set(os.listdir(inputs_dir)) if os.path.isdir(inputs_dir) else set()
    assert files_after == files_before
    assert dict(master.generated_inputs_by_user) == record_before


def test_budget_env_wiring_defaults(monkeypatch):
    # Production wiring: SIMC_TG_MAX_COMBINATIONS/SIMC_TG_ITERS_PER_SEC feed
    # the module constants at import (env-only knobs, TG2-ACCEPT Q1).
    assert master.TG_MAX_COMBINATIONS == int(os.environ.get("SIMC_TG_MAX_COMBINATIONS", "5000"))
    assert master.TG_WORK_ESTIMATE_ITERS_PER_SEC == float(os.environ.get("SIMC_TG_ITERS_PER_SEC", "1"))


# --------------------------------------------------------- §6.6 single_swap pin

GOLDEN_SINGLE_SWAP = '''warrior=Test
simulate 10000

# fighting style: single boss (5 min fixed fight)
duration=300

head=,id=100,ilevel=250
chest=,id=101,ilevel=250
finger1=,id=102,ilevel=250
finger2=,id=103,ilevel=250
trinket1=,id=104,ilevel=250
trinket2=,id=105,ilevel=250

copy="Test_chest_0,Test"
chest=,id=101,enchant_id=6611,ilevel=250

copy="Test_chest_1,Test"
chest=,id=201,enchant_id=6611,ilevel=252

copy="Test_trinket_2,Test"
trinket1=,id=205,ilevel=252

'''


def test_default_mode_byte_identical_golden():
    # Snapshot captured on the pre-TG2-B branch tip (feature/t_5e099a0a-
    # enh-chips @ 96f7958) — guards D2: default behavior must not drift.
    payload = {
        **BASE_PAYLOAD,
        "selected_items": {
            "chest": [EQUIPPED["chest"], "id=201,ilevel=252"],
            "trinket": [EQUIPPED["trinket1"], "id=205,ilevel=252"],
        },
        "selected_enchants": {"chest": [6611]},
    }
    response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["mode"] == "single_swap"
    assert data["work_estimate_minutes"] is None
    with open(data["file_path"], encoding="utf-8") as f:
        assert f.read() == GOLDEN_SINGLE_SWAP


# ------------------------------------------------------------------- §6 UI

def test_run_bar_shows_compare_mode_dropdown_with_two_choices():
    html = client.get("/").text
    assert 'id="compare-mode"' in html
    assert '<option value="single_swap" selected>one swap at a time</option>' in html
    assert '<option value="combinations">all combinations (Top Gear)</option>' in html
    assert "Combination mode simulates every selected item of every slot " \
        "together, like Raidbots Top Gear." in html
    select_block = html.split('id="compare-mode"', 1)[1].split("</select>", 1)[0]
    assert select_block.count("<option") == 2
    assert 'id="work-estimate"' in html


def test_app_js_sends_mode_and_replaces_estimate_with_server_count():
    js = client.get("/static/app.js").text
    assert "mode: document.getElementById('compare-mode')?.value || 'single_swap'" in js
    assert "getElementById('compare-mode').addEventListener('change', selectionChanged)" in js
    # Server count replaces the client estimate in combinations mode.
    assert "generatedInput?.mode === 'combinations'" in js
    assert "count === null ? '…'" in js
    assert "min stage 1 (est.)" in js
