"""MGE-3 backend regressions (card t_3da0efb2, epic t_890e314f).

Three surfaces, one PR:
1. Midnight catalog load edge — enchant-group keys map to gear-slot keys at
   load_config (MGE-2 design contract §8.3 / G8.5); profession_tool never
   surfaces; the tracked seed (examples/config.example.json) carries the
   full MGE-1 catalog (50 enchants / 8 groups, 35 standard + 4 meta gems).
2. Rule R adaptive stage plan (MGE-1 t_8bfa56f3, leader ruling pinned):
   keep_i = max(K_MIN, ceil(0.25*N_i)) floor, stage-skip at small N, the
   CULL_K band may only ADD survivors; aggressive funnel preserved at large N.
3. GET /api/version serves the pyproject version (MGE-2 §8.1) and the
   FastAPI doc consumes the same constant.
"""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from cli.sim_helper import active_stages, main, min_survivors, select_survivors
from src.cli.generate_input import load_config
from src.web.main import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
client = TestClient(app)

# The 14 paper-doll gear-slot keys /api/config.enchantments may serve (G8.5).
GEAR_SLOTS = {
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist",
    "legs", "feet", "finger", "trinket", "main_hand", "off_hand",
}

# One sentinel entry per MGE-1 source group — all 8 groups, G8.5 pin.
MGE1_GROUPS = {
    "helm": [{"id": 243979, "name": "Enchant Helm - Blessing of Speed"}],
    "shoulders": [{"id": 243963, "name": "Enchant Shoulders - Akil'zon's Swiftness"}],
    "chest": [{"id": 243947, "name": "Enchant Chest - Mark of Nalorakk"}],
    "legs": [{"id": 240157, "name": "Bright Linen Spellthread"}],
    "boots": [{"id": 244009, "name": "Enchant Boots - Farstrider's Hunt"}],
    "rings": [{"id": 243955, "name": "Enchant Ring - Amani Mastery"}],
    "weapon": [{"id": 244031, "name": "Enchant Weapon - Arcanovoid"}],
    "profession_tool": [{"id": 244103, "name": "Enchant Profession Gear - Horizon's Call"}],
}

# Binding mapping (MGE-2 §8.3): group key -> expected gear-slot key.
MAPPED = {
    "head": MGE1_GROUPS["helm"],
    "shoulder": MGE1_GROUPS["shoulders"],
    "chest": MGE1_GROUPS["chest"],
    "legs": MGE1_GROUPS["legs"],
    "feet": MGE1_GROUPS["boots"],
    "finger": MGE1_GROUPS["rings"],
    "main_hand": MGE1_GROUPS["weapon"],
}


# --- 1. catalog load edge ---------------------------------------------------

def test_enchant_group_mapping_pinned_for_all_eight_source_groups(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"enchantments": MGE1_GROUPS, "gems": {}}), encoding="utf-8")
    config = load_config(str(path))
    assert config["enchantments"] == MAPPED
    assert "profession_tool" not in config["enchantments"]


def test_gear_slot_keyed_configs_pass_through_unchanged(tmp_path):
    # Backwards compatibility: the live config.json predates MGE-1 and is
    # already gear-slot keyed — loading it must not touch anything.
    legacy = {
        "enchantments": {
            "head": [{"id": 1}], "neck": [], "back": [{"id": 2}], "wrist": [],
            "hands": [], "waist": [], "off_hand": [], "trinket": [],
        },
        "gems": {},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert load_config(str(path))["enchantments"] == legacy["enchantments"]


def test_seed_example_is_the_full_midnight_catalog():
    config = load_config(os.path.join(_ROOT, "examples", "config.example.json"))
    enchants = config["enchantments"]
    assert set(enchants) == set(MAPPED)  # 7 combat-gear slots after mapping
    # MGE-1 counts per group: helm 6, shoulders 6, chest 4, legs 6, boots 3,
    # rings 9, weapon 10 -> 44 selectable; profession_tool (6) filtered.
    assert {slot: len(entries) for slot, entries in enchants.items()} == {
        "head": 6, "shoulder": 6, "chest": 4, "legs": 6,
        "feet": 3, "finger": 9, "main_hand": 10,
    }
    gems = config["gems"]
    assert len(gems["standard"]) == 35 and len(gems["meta"]) == 4
    assert "method.gg" in config["source"]  # §8.3: source cites the guide
    for entries in list(enchants.values()) + [gems["standard"], gems["meta"]]:
        for entry in entries:
            assert isinstance(entry["id"], int) and entry["name"]
            assert entry["wowhead_url"].endswith(f"item={entry['id']}")


def test_api_config_serves_only_gear_slot_keys(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"enchantments": MGE1_GROUPS,
                    "gems": {"standard": [{"id": 241142}], "meta": [{"id": 240983}]}}),
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    # t_a856571d: /api/config now warms record quality via the cached Wowhead
    # XML path; patch the fetch boundary to stay offline (repo convention).
    with patch("src.web.main.fetch_wowhead_upgrade", new=AsyncMock(return_value=None)):
        body = client.get("/api/config").json()
    assert set(body["enchantments"]) <= GEAR_SLOTS          # G8.5
    assert "profession_tool" not in body["enchantments"]    # G8.5
    assert {"standard", "meta"} <= set(body["gems"])        # G8.5
    # t_a856571d: records gained an additive `quality` key; compare the shape without it.
    assert {slot: [{k: v for k, v in entry.items() if k != "quality"} for entry in entries]
            for slot, entries in body["enchantments"].items()} == MAPPED


# --- 2. rule R: stage plan ----------------------------------------------------

@pytest.mark.parametrize("n,expected", [
    (2, (2,)), (4, (2,)),                     # <= K_MIN: all at final
    (5, (1, 2)), (12, (1, 2)), (16, (1, 2)),  # <= K_MIN/p: skip fast filter
    (17, (0, 1, 2)), (400, (0, 1, 2)), (2000, (0, 1, 2)),  # ladder unchanged
])
def test_active_stages_skip_table(n, expected):
    assert active_stages(n) == expected


@pytest.mark.parametrize("n,expected", [
    (2, 4), (12, 4), (16, 4),   # floor regime: K_MIN binds
    (17, 5), (40, 10), (64, 16), (400, 100), (2000, 500),  # ceil(0.25 n)
])
def test_min_survivors_floor_table(n, expected):
    assert min_survivors(n) == expected


def _spread(n):
    """Widely-separated means with tiny errors: the band keeps exactly one."""
    return [(f"C{i}", 1000.0 - i, 0.01, True) for i in range(n)]


def test_floor_tops_up_top_ranked_in_order(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    out = select_survivors(_spread(20), 5, floor=min_survivors(20))
    assert out == ["C0", "C1", "C2", "C3", "C4"]  # ceil(0.25*20) = 5


def test_floor_never_clips_band_additions(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    s = [(f"C{i}", 100.0 - i * 0.01, 5.0, True) for i in range(20)]  # one wide band
    assert len(select_survivors(s, 5, floor=8)) == 20


def test_no_floor_keeps_legacy_band_behaviour(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    assert select_survivors(_spread(20), 5) == ["C0"]


def _drive_pipeline(tmp_path, monkeypatch, n_combos, stage_summaries, batch=100000):
    """Run main() with a fake engine (house mock pattern) and a cheap plan."""
    input_file = tmp_path / "t.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,T"\n')
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "2:1;3:0.2;4:0.05")
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    summaries = iter(stage_summaries)
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}",
                            "start_server=0"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=[f"C{i}" for i in range(n_combos)]), \
         patch("cli.sim_helper.get_memory_based_batch_size", return_value=batch), \
         patch("cli.sim_helper.run_simc", return_value=0) as run, \
         patch("cli.sim_helper.prepare_stage") as prep, \
         patch("cli.sim_helper.get_actor_summaries", side_effect=lambda *a, **k: next(summaries)):
        main()
    return [c.args[2] for c in run.call_args_list], [c.args[1] for c in prep.call_args_list]


def test_two_combos_run_final_stage_only(tmp_path, monkeypatch, capsys):
    run_args, prep_combos = _drive_pipeline(tmp_path, monkeypatch, 2, [])
    assert run_args == ["iterations=4 target_error=0.05% single_actor_batch=1"]
    assert sorted(prep_combos[-1]) == ["C0", "C1"]
    assert "STAGE 1: skipped" in capsys.readouterr().out


def test_twelve_combos_skip_stage1_and_keep_four_finalists(tmp_path, monkeypatch):
    run_args, prep_combos = _drive_pipeline(tmp_path, monkeypatch, 12, [_spread(12)])
    assert run_args == ["iterations=3 target_error=0.2% single_actor_batch=1",
                        "iterations=4 target_error=0.05% single_actor_batch=1"]
    finals = prep_combos[-1]
    assert finals == ["C0", "C1", "C2", "C3"]  # acceptance: > 1 finalist
    assert len(finals) > 1


def test_forty_combos_ladder_floors_ten_then_four(tmp_path, monkeypatch):
    run_args, prep_combos = _drive_pipeline(
        tmp_path, monkeypatch, 40, [_spread(40), _spread(10)])
    assert len(run_args) == 3  # full ladder
    assert len(prep_combos[0]) == 10  # stage 2 keeps max(4, ceil(0.25*40))
    assert len(prep_combos[1]) == 4   # final keeps max(4, ceil(0.25*10))


def test_four_hundred_combos_stays_aggressive(tmp_path, monkeypatch):
    run_args, prep_combos = _drive_pipeline(
        tmp_path, monkeypatch, 400, [_spread(400), _spread(100)])
    assert len(run_args) == 3
    assert len(prep_combos[0]) == 100  # the 25% funnel, not softened
    assert len(prep_combos[1]) == 25


def test_stage_plan_override_flows_and_floor_respects_percent_override(tmp_path, monkeypatch):
    # SIMC_HELPER_STAGE_PLAN is honored by every _drive_pipeline test above
    # (they pin the overridden 2/3/4-iteration args). Here: an explicit
    # stage1_percent_best opts that stage out of the floor (manual knob).
    input_file = tmp_path / "t.simc"
    input_file.write_text('paladin="Test"\ncopy="C1,T"\n')
    monkeypatch.setenv("SIMC_HELPER_STAGE_PLAN", "2:1;3:0.2;4:0.05")
    monkeypatch.delenv("SIMC_HELPER_CULL_K", raising=False)
    with patch("sys.argv", ["sim_helper.py", "simc_path=s", f"input_file={input_file}",
                            "start_server=0", "stage1_percent_best=1"]), \
         patch("cli.sim_helper.get_character_name", return_value="Test"), \
         patch("cli.sim_helper.get_all_combos", return_value=[f"C{i}" for i in range(20)]), \
         patch("cli.sim_helper.get_memory_based_batch_size", return_value=100000), \
         patch("cli.sim_helper.run_simc", return_value=0), \
         patch("cli.sim_helper.prepare_stage") as prep, \
         patch("cli.sim_helper.get_actor_summaries", return_value=_spread(20)):
        main()
    assert len(prep.call_args_list[0].args[1]) == 1  # override wins over floor


# --- 3. version exposure ------------------------------------------------------

def test_version_endpoint_matches_package_version():
    import re
    response = client.get("/api/version")
    assert response.status_code == 200
    version = response.json()["version"]
    with open(os.path.join(_ROOT, "pyproject.toml"), encoding="utf-8") as f:
        pinned = re.search(r'^version = "([^"]+)"', f.read(), re.MULTILINE).group(1)
    assert version == pinned
    assert app.version == version  # FastAPI doc consumes the same constant
