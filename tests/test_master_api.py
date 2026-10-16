import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import (
    app,
    manager,
    parse_wowhead_icon_name,
    parse_wowhead_upgrade,
    wowhead_xml_url,
)
from web.main import REPORTS_DIR as MASTER_REPORTS_DIR

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "user_id" in client.cookies


def test_disabled_auth_serves_app_without_login(monkeypatch):
    monkeypatch.setenv("AUTHENTICATION_ENABLED", "false")
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 200
    assert "user_id" in response.cookies or "user_id" in client.cookies

    login_page = client.get("/login", follow_redirects=False)
    assert login_page.status_code == 303
    assert login_page.headers["location"] == "dashboard"

    register = client.post("/register", data={"username": "unused", "password": "unused"})
    assert register.status_code == 403

def test_api_state():
    response = client.get("/api/state")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "workers" in data


def test_wowhead_xml_url_uses_item_id_and_bonus_ids():
    url = wowhead_xml_url("id=251157,enchant_id=8001,bonus_id=13440/6652/13340/13574/12806")
    assert url == "https://www.wowhead.com/item=251157?xml=&bonus=13440%3A6652%3A13340%3A13574%3A12806"


def test_parse_wowhead_upgrade_extracts_track_rank_and_item_level():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <wowhead><item id="251157"><level>289</level><htmlTooltip><![CDATA[
    <table><tr><td><span class="q"><br>Item Level <!--ilvl-->289</span>
    <br><span class="q">Upgrade Level: Myth <!--uindex-->6/6</span></td></tr></table>
    ]]></htmlTooltip></item></wowhead>"""

    assert parse_wowhead_upgrade(xml) == {"track": "myth", "rank": 6, "item_level": 289}


def test_parse_wowhead_icon_name_accepts_only_safe_icon_names():
    xml = '<wowhead><item><icon displayId="0">inv_helmet_204_plate_raidpaladin</icon></item></wowhead>'
    assert parse_wowhead_icon_name(xml) == "inv_helmet_204_plate_raidpaladin"
    assert parse_wowhead_icon_name("<wowhead><item><icon>../secret</icon></item></wowhead>") is None


def test_wowhead_upgrades_endpoint_maps_exact_item_back_to_slot():
    item = "id=251157,bonus_id=13440/6652/13340/13574/12806"
    with patch("web.main.fetch_wowhead_upgrade", new=AsyncMock(return_value={"track": "myth", "rank": 6, "item_level": 289})):
        response = client.post("/api/wowhead-upgrades", json={"items_by_slot": {"shoulder": [item]}})

    assert response.status_code == 200
    assert response.json()["gear_upgrades"] == {"shoulder": {item: {"track": "myth", "rank": 6, "item_level": 289}}}

def test_parse_addon():
    addon_text = "paladin=Test\nhead=id=123"
    response = client.post("/api/parse-addon", json={"addon_text": addon_text})
    assert response.status_code == 200
    data = response.json()
    assert data["char_name"] == "Test"
    assert data["equipped_gear"]["head"] == "id=123"
    assert data["base_profile"].splitlines() == ["paladin=Test"]


def test_parse_addon_returns_upgrade_levels():
    addon_text = (
        "paladin=Test\n"
        "# Sword (337)\n"
        "# upgrade_levels=2:4:c#3047#40#0:/3:8:c#3047#80#0:\n"
        "head=id=123"
    )
    response = client.post("/api/parse-addon", json={"addon_text": addon_text})
    assert response.status_code == 200
    data = response.json()
    assert data["item_upgrades"]["id=123"]["levels"][0] == {
        "upgrade_level": 2,
        "ilvl_increment": 4,
        "currency_costs": [{"id": 3047, "count": 40, "discounted": False}],
        "item_costs": [],
    }
    assert data["item_upgrades"]["id=123"]["levels"][1]["upgrade_level"] == 3


def test_parse_addon_without_upgrade_levels_returns_empty_dict():
    response = client.post("/api/parse-addon", json={"addon_text": "paladin=Test\nhead=id=123"})
    assert response.status_code == 200
    assert response.json()["item_upgrades"] == {}


def test_parse_addon_preserves_base_profile_line_breaks_from_api_payload():
    addon_text = "paladin=Test\nlevel=90\nrace=blood_elf\nhead=id=123"
    response = client.post("/api/parse-addon", json={"addon_text": addon_text})
    assert response.status_code == 200

    base_profile = response.json()["base_profile"]
    assert "paladin=Test\nlevel=90\nrace=blood_elf" in base_profile
    assert "paladin=Testlevel=90" not in base_profile


def test_rate_limit():
    from web.main import user_last_sim_time
    # Get user_id cookie
    client.get("/")
    user_id = client.cookies.get("user_id")
    assert user_id is not None
    
    # Clear any existing state for this user
    if user_id in user_last_sim_time:
        del user_last_sim_time[user_id]
    
    with patch.object(manager, "get_idle_worker", return_value=None):
        # 1. First run: should be 503 (no workers) but NOT rate limited yet
        response = client.post("/api/run-simulation")
        assert response.status_code == 503
        
        # 2. Mock a worker and start successfully
        with patch.object(manager, "get_idle_worker", return_value="worker1"), \
             patch.object(manager, "send_task", return_value=None):
            manager.active_workers["worker1"] = MagicMock(status="Idle")
            # SEC-6: explicit input_id (fake worker never fetches it)
            response = client.post("/api/run-simulation", params={"input_id": "qa-ratelimit"})
            assert response.status_code == 200
            assert "task_id" in response.json()
            
        # 3. Third run: should be 429 (Rate limited)
        response = client.post("/api/run-simulation")
        assert response.status_code == 429

def test_api_run_simulation_endpoint():
    from src.core.db import session_cleanup_older_than
    from web.main import user_last_sim_time
    user_last_sim_time.clear()
    session_cleanup_older_than(0, time.time())
    with patch.object(manager, "get_idle_worker", return_value="worker1"), \
         patch.object(manager, "send_task", return_value=None):
        manager.active_workers["worker1"] = MagicMock(status="Idle")
        # SEC-6: explicit input_id (fake worker never fetches it)
        response = client.post("/api/run-simulation", params={"input_id": "qa-endpoint"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "task_id" in data
        assert "worker_id" in data

def test_api_generate_simc():
    payload = {
        "base_profile": "paladin=Test\nhead=id=1",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"head": "id=1"},
        "selected_items": {"head": ["id=1"]},
        "selected_enchants": {},
        "selected_gems": []
    }
    response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_generate_simc_default_selection_reports_zero_combinations():
    """t_4485565b: selecting only equipped gear yields 0 candidate copies and an
    honest combinations=0 (no max(1, ...) fudge) — the run becomes a baseline
    current-gear report instead of a doomed comparison job."""
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"head": "id=1"},
        "selected_items": {"head": ["id=1"]},
        "selected_enchants": {},
        "selected_gems": [],
    }
    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["combinations"] == 0
    with open("char_simc_addon.txt") as generated_file:
        assert 'copy="' not in generated_file.read()


def test_api_generate_simc_deduplicates_equivalent_item_field_order():
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"head": "id=1"},
        "selected_items": {
            "head": ["id=2,bonus_id=4,enchant_id=3", "bonus_id=4,enchant_id=3,id=2"]
        },
        "selected_enchants": {},
        "selected_gems": [],
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)

    assert response.status_code == 200
    assert response.json()["combinations"] == 1
    with open("char_simc_addon.txt") as generated_file:
        assert generated_file.read().count('copy="Test_head_') == 1

def test_api_generate_simc_applies_item_level_overrides_to_equipped_and_selected_items():
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"head": "id=1,bonus_id=100", "chest": "id=2"},
        "selected_items": {"head": ["id=1,bonus_id=100"], "chest": ["id=20,ilevel=430"]},
        "selected_enchants": {},
        "selected_gems": [],
        "item_levels": {
            "head": {"id=1,bonus_id=100": 626},
            "chest": {"id=20,ilevel=430": 640},
        },
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    assert generated.count("head=,id=1,ilevel=626,bonus_id=100") == 1
    assert "chest=,id=20,ilevel=640" in generated
    assert "ilevel=430" not in generated


def test_api_generate_simc_applies_midnight_track_rank_upgrades():
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"head": "id=1,bonus_id=100", "trinket1": "id=2,ilevel=276"},
        "selected_items": {"head": ["id=1,bonus_id=100"], "trinket": ["id=20,ilevel=276"]},
        "selected_enchants": {},
        "selected_gems": [],
        "upgrade_season": "midnight-s1",
        "gear_upgrades": {
            "head": {"id=1,bonus_id=100": {"track": "myth", "rank": 6}},
            "trinket": {
                "id=2,ilevel=276": {"track": "myth", "rank": 6},
                "id=20,ilevel=276": {"track": "hero", "rank": 6},
            },
        },
        "voidforged_items": {"trinket": {"id=2,ilevel=276": True, "id=20,ilevel=276": True}},
        "item_levels": {"head": {"id=1,bonus_id=100": 220}},
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    assert generated.count("head=,id=1,ilevel=289,bonus_id=100") == 1
    assert "head=,id=1,ilevel=220" not in generated
    assert "trinket1=,id=2,ilevel=298" in generated
    assert "trinket1=,id=20,ilevel=285" in generated


def test_user_selected_upgrade_upgrades_candidate_but_not_baseline():
    """t_ef33100b: a user-chosen rank must move the candidate copy only.

    The baseline must stay the character's current gear, otherwise the
    candidate equals the baseline, is filtered as an equipped variation,
    and the upgrade UI can never produce a diff.
    """
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"back": "id=1,ilevel=291"},
        "selected_items": {"back": ["id=1,ilevel=291"]},
        "selected_enchants": {},
        "selected_gems": [],
        "upgrade_season": "midnight-s2",
        "gear_upgrades": {
            "back": {"id=1,ilevel=291": {"track": "myth", "rank": 6, "user_selected": True}},
        },
        "voidforged_items": {},
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    # Baseline keeps the current ilvl...
    assert "back=,id=1,ilevel=291" in generated
    # ...and the myth rank-6 upgrade (Season 2 ladder top = 334) lands in a
    # copy block instead.
    assert generated.count('copy="Test_back_') == 1
    assert generated.count("back=,id=1,ilevel=334") == 1
    assert response.json()["combinations"] >= 1


def test_user_selected_upgrade_at_current_rank_produces_no_duplicate_copy():
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"back": "id=1,ilevel=291"},
        "selected_items": {"back": ["id=1,ilevel=291"]},
        "selected_enchants": {},
        "selected_gems": [],
        "upgrade_season": "midnight-s2",
        "gear_upgrades": {
            "back": {
                "id=1,ilevel=291": {
                    "source": "export",
                    "rank": 0,
                    "item_level": 291,
                    "user_selected": True,
                }
            },
        },
        "voidforged_items": {},
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    assert 'copy="' not in generated
    assert generated.count("back=,id=1,ilevel=291") == 1


def test_inferred_upgrade_entry_still_describes_the_baseline():
    """Unmarked (inferred-current) entries keep applying to the baseline."""
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"back": "id=1,ilevel=291"},
        "selected_items": {"back": ["id=1,ilevel=291"]},
        "selected_enchants": {},
        "selected_gems": [],
        "upgrade_season": "midnight-s2",
        "gear_upgrades": {"back": {"id=1,ilevel=291": {"track": "myth", "rank": 6}}},
        "voidforged_items": {},
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    assert "back=,id=1,ilevel=334" in generated
    assert 'copy="' not in generated


def test_api_generate_simc_applies_voidforge_only_to_selected_weapons_and_trinkets():
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {
            "trinket1": "id=1,ilevel=276",
            "main_hand": "id=2,ilevel=289",
            "head": "id=3,ilevel=276",
        },
        "selected_items": {
            "trinket": ["id=10,ilevel=276"],
            "main_hand": ["id=20,ilevel=289"],
            "head": ["id=30,ilevel=276"],
        },
        "selected_enchants": {},
        "selected_gems": [],
        "upgrade_season": "midnight-s1",
        "voidforged_items": {
            "trinket": {"id=10,ilevel=276": True, "id=1,ilevel=276": True},
            "main_hand": {"id=20,ilevel=289": True, "id=2,ilevel=289": True},
            "head": {"id=30,ilevel=276": True, "id=3,ilevel=276": True},
        },
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    assert "trinket1=,id=1,ilevel=285" in generated
    assert "trinket1=,id=10,ilevel=285" in generated
    assert "main_hand=,id=2,ilevel=298" in generated
    assert "main_hand=,id=20,ilevel=298" in generated
    assert generated.count("head=,id=3,ilevel=276") == 1
    assert "head=,id=30,ilevel=276" in generated


def test_api_generate_simc_filters_meta_gems_out_of_item_variations():
    meta_gem = 240967
    standard_gem = 240888
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"head": "id=1,gem_id=240888", "chest": "id=2", "legs": "id=3"},
        "selected_items": {"head": ["id=10,gem_id=240888"], "chest": ["id=20"], "legs": ["id=30"]},
        "selected_enchants": {},
        "selected_gems": [meta_gem, standard_gem],
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={
            "gems": {"meta": [meta_gem], "standard": []},
            "enchantments": {},
        },
    ):
        response = client.post("/api/generate-simc", json=payload)

    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    assert f"head=,id=10,gem_id={standard_gem}" in generated
    assert f"gem_id={meta_gem}" not in generated


def test_api_generate_simc_does_not_add_standard_gems_to_unsocketed_items():
    standard_gem = 240908
    payload = {
        "base_profile": "paladin=Test",
        "char_class": "paladin",
        "char_name": "Test",
        "equipped_gear": {"chest": "id=1", "trinket1": "id=2", "head": "id=3"},
        "selected_items": {"chest": ["id=10"], "trinket": ["id=20"], "head": ["id=30"]},
        "selected_enchants": {},
        "selected_gems": [standard_gem],
        "extra_sockets": {"head": True, "wrist": False, "waist": False},
    }

    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    with open("char_simc_addon.txt") as f:
        generated = f.read()

    variant_lines = []
    prev_copy = False
    for line in generated.splitlines():
        if line.startswith("copy="):
            prev_copy = True
        elif prev_copy and line.strip():
            variant_lines.append(line)
            prev_copy = False

    assert "head=,id=30,gem_id=240908" in variant_lines
    assert "chest=,id=10,gem_id=240908" not in variant_lines
    assert "trinket1=,id=20,gem_id=240908" not in variant_lines
    assert "chest=,id=10" in variant_lines
    assert "trinket1=,id=20" in variant_lines


def test_api_get_results(tmp_path):
    task_id = "test-task"
    task_dir = os.path.join(MASTER_REPORTS_DIR, "testuser", task_id)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "report_t.html"), "w") as f:
        f.write('<h2 class="toggle">C1&#160;:&#160;100,000 dps</h2>')

    response = client.get(f"/api/get-results?task_id={task_id}")
    assert response.status_code == 200
    assert response.json()["results"][0]["name"] == "C1"

def test_api_upload_file():
    from web.main import CLUSTER_SECRET
    file_content = b"fake data"
    response = client.post(
        "/api/worker/upload-file?task_id=t1&file_name=test.txt",
        files={"file": ("test.txt", file_content)},
        headers={"X-Cluster-Secret": CLUSTER_SECRET}
    )
    assert response.status_code == 200
    # t_c968bf8d: uploads land under the owner's user directory; tasks with no
    # entry in task_user_map (e.g. after a master restart) go to "anonymous".
    assert os.path.exists(os.path.join(MASTER_REPORTS_DIR, "anonymous", "t1", "test.txt"))


def test_api_upload_file_lands_in_owner_directory():
    """t_c968bf8d: the report-write path is per-user: REPORTS_DIR/<user_id>/<task_id>/."""
    import web.main as m
    from web.main import CLUSTER_SECRET
    m.task_user_map["towner"] = "u-alice"
    try:
        response = client.post(
            "/api/worker/upload-file?task_id=towner&file_name=report_1.html",
            files={"file": ("report_1.html", b"<html/>")},
            headers={"X-Cluster-Secret": CLUSTER_SECRET}
        )
        assert response.status_code == 200
        assert os.path.isdir(os.path.join(MASTER_REPORTS_DIR, "u-alice", "towner"))
        assert not os.path.exists(os.path.join(MASTER_REPORTS_DIR, "anonymous", "towner"))
    finally:
        m.task_user_map.pop("towner", None)


def test_api_upload_file_sanitizes_user_directory():
    """t_c968bf8d: hostile user ids (e.g. the ip_<host> fallback) cannot escape REPORTS_DIR."""
    import web.main as m
    from web.main import CLUSTER_SECRET
    m.task_user_map["tsanit"] = "../evil"
    try:
        response = client.post(
            "/api/worker/upload-file?task_id=tsanit&file_name=test.txt",
            files={"file": ("test.txt", b"x")},
            headers={"X-Cluster-Secret": CLUSTER_SECRET}
        )
        assert response.status_code == 200
        assert os.path.isdir(os.path.join(MASTER_REPORTS_DIR, "___evil", "tsanit"))
        assert not os.path.exists(os.path.join(os.path.dirname(MASTER_REPORTS_DIR), "evil", "tsanit"))
    finally:
        m.task_user_map.pop("tsanit", None)


def test_api_upload_file_prunes_oldest_runs_beyond_cap():
    """t_c968bf8d: per-user retention cap — the oldest run dirs are pruned on insert."""
    import shutil

    import web.main as m
    from web.main import CLUSTER_SECRET

    user = "u-prune"
    base = os.path.join(MASTER_REPORTS_DIR, user)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    # Seed 3 old runs with staggered mtimes, cap at 3.
    for i in range(3):
        d = os.path.join(base, f"oldrun{i}")
        os.makedirs(d)
        os.utime(d, (1_000_000 + i * 100, 1_000_000 + i * 100))
    m.task_user_map["tnew"] = user
    monkey_cap = m.REPORT_RETENTION
    m.REPORT_RETENTION = 3
    try:
        response = client.post(
            "/api/worker/upload-file?task_id=tnew&file_name=report_9.html",
            files={"file": ("report_9.html", b"<html/>")},
            headers={"X-Cluster-Secret": CLUSTER_SECRET}
        )
        assert response.status_code == 200
        remaining = sorted(os.listdir(base))
        assert len(remaining) == 3
        assert "tnew" in remaining
        assert "oldrun0" not in remaining  # oldest pruned
        assert "oldrun2" in remaining
    finally:
        m.REPORT_RETENTION = monkey_cap
        m.task_user_map.pop("tnew", None)
        shutil.rmtree(base, ignore_errors=True)


def test_report_url_endpoint():
    """t_c968bf8d: /api/report-url resolves the per-user static report URL."""
    task_id = "turl"
    task_dir = os.path.join(MASTER_REPORTS_DIR, "u-url", task_id)
    os.makedirs(task_dir, exist_ok=True)
    report = os.path.join(task_dir, "report_5.html")
    with open(report, "w") as f:
        f.write("<html/>")

    response = client.get(f"/api/report-url?task_id={task_id}")
    assert response.status_code == 200
    assert response.json()["url"] == f"reports/u-url/{task_id}/report_5.html"

    missing = client.get("/api/report-url?task_id=nope-missing")
    assert missing.status_code == 404


def test_get_results_latest_spans_user_directories():
    """t_c968bf8d: task_id=latest globs the new <user>/<task> layout."""
    task_dir = os.path.join(MASTER_REPORTS_DIR, "u-latest", "latest-task")
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "report_latest.html"), "w") as f:
        f.write('<h2 class="toggle">Latest&#160;:&#160;4242 dps</h2>')
    os.utime(task_dir, None)  # bump mtime so it is the newest report

    response = client.get("/api/get-results?task_id=latest")
    assert response.status_code == 200
    assert response.json()["results"][0]["name"] == "Latest"


def test_api_upload_file_rejects_path_traversal_filename():
    from web.main import CLUSTER_SECRET
    response = client.post(
        "/api/worker/upload-file?task_id=t1&file_name=../evil.txt",
        files={"file": ("evil.txt", b"bad")},
        headers={"X-Cluster-Secret": CLUSTER_SECRET}
    )
    assert response.status_code == 400
    assert not os.path.exists(os.path.join(MASTER_REPORTS_DIR, "anonymous", "evil.txt"))


def test_api_upload_file_rejects_path_traversal_task_id():
    from web.main import CLUSTER_SECRET
    outside_path = "/tmp/upload_task_escape.txt"
    if os.path.exists(outside_path):
        os.remove(outside_path)

    response = client.post(
        "/api/worker/upload-file?task_id=..&file_name=upload_task_escape.txt",
        files={"file": ("upload_task_escape.txt", b"bad")},
        headers={"X-Cluster-Secret": CLUSTER_SECRET}
    )

    assert response.status_code == 400
    assert not os.path.exists(outside_path)


def test_api_upload_file_rejects_zip_slip_members(tmp_path):
    import io
    import zipfile

    from web.main import CLUSTER_SECRET

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../../evil.txt", "bad")
    payload.seek(0)

    response = client.post(
        "/api/worker/upload-file?task_id=tzip&file_name=artifacts.zip",
        files={"file": ("artifacts.zip", payload.getvalue())},
        headers={"X-Cluster-Secret": CLUSTER_SECRET}
    )
    assert response.status_code == 400
    assert not os.path.exists("/tmp/evil.txt")

def test_api_get_results_rejects_path_traversal_task_id(tmp_path):
    outside_dir = "/tmp/simc_results_escape"
    os.makedirs(outside_dir, exist_ok=True)
    with open(os.path.join(outside_dir, "report_escape.html"), "w") as f:
        f.write('<h2 class="toggle">Escaped&#160;:&#160;1 dps</h2>')

    response = client.get("/api/get-results?task_id=../simc_results_escape")

    assert response.status_code == 400



def test_api_get_results_complex_html(tmp_path):
    task_id = "test-complex"
    task_dir = os.path.join(MASTER_REPORTS_DIR, "testuser", task_id)
    os.makedirs(task_dir, exist_ok=True)
    with open(os.path.join(task_dir, "report_c.html"), "w") as f:
        f.write('<h2 class="toggle">A&#160;:&#160;1,234,567 dps</h2>\n<h2 class="toggle">B&#160;:&#160;987,654 dps</h2>')

    response = client.get(f"/api/get-results?task_id={task_id}")
    res = {r["name"]: r["dps"] for r in response.json()["results"]}
    assert res["A"] == 1234567
    assert res["B"] == 987654


def test_api_get_results_nightly_report_format():
    """Regression (t_fdd385ef): SimC nightly emits player headers as
    <h2 id="player1toggle" class="toggle""> — with a stray double-quote
    before '>' — which the old split regex never matched, so the results
    page showed an empty list. Fixture is a trimmed snippet of the real
    nightly report from task e4c3035c."""
    import shutil

    task_id = "test-nightly-fixture"
    task_dir = os.path.join(MASTER_REPORTS_DIR, "testuser", task_id)
    os.makedirs(task_dir, exist_ok=True)
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "simc_report_nightly_snippet.html")
    shutil.copy(fixture, os.path.join(task_dir, "report_nightly.html"))

    response = client.get(f"/api/get-results?task_id={task_id}")
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 3
    by_name = {r["name"]: r for r in results}
    assert by_name["Hamidriel"]["dps"] == 18820
    assert by_name["Hamidriel_back_12"]["dps"] == 19872
    assert by_name["Fluffy_Pillow"]["dps"] == 0
    # Non-player headers (Table of Contents, apm-summary) are not results.
    assert set(by_name) == {"Hamidriel", "Hamidriel_back_12", "Fluffy_Pillow"}
    head = by_name["Hamidriel"]["gear"]["head"]
    assert head.startswith("id=271465")
    assert "enchant_id=8017" in head
    assert "bonus_id=6652/12850" in head


def test_input_serving_allows_generated_simc_file_only():
    with open("char_simc_addon.txt", "w") as f:
        f.write("paladin=Test\n")

    allowed = client.get("/inputs/char_simc_addon.txt")
    blocked = client.get("/inputs/README.md")

    assert allowed.status_code == 200
    assert blocked.status_code == 404

def test_parse_addon_edge_cases():
    # Empty text
    response = client.post("/api/parse-addon", json={"addon_text": ""})
    assert response.status_code == 200
    
    # No items
    response = client.post("/api/parse-addon", json={"addon_text": "paladin=Test"})
    assert response.json()["char_name"] == "Test"

@pytest.mark.asyncio
async def test_api_update_simc_flow():
    from web.main import manager
    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    mock_ws.send_json = AsyncMock()
    wid = await manager.connect(mock_ws, "UpdateNode")
    
    with patch.object(manager, "get_idle_worker", return_value=wid):
        # 1. Trigger Update
        response = client.post("/api/update-simc")
        assert response.status_code == 200
        task_id = response.json()["task_id"]
        assert task_id.startswith("upd-")
        
    manager.disconnect(wid)

def test_api_get_results_error():
    # Test with non-existent task
    response = client.get("/api/get-results?task_id=nonexistent-task-id-that-really-should-not-exist")
    assert response.json()["status"] == "error"


# ===== Task Status API tests =====

def test_api_task_status_no_params():
    response = client.get("/api/task-status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "tasks" in data
    assert "total" in data

def test_api_task_status_specific_task():
    # First populate the store (use the same import path as the app)
    from src.worker import get_or_create_task_status, task_status_store
    task_status_store.clear()
    ts = get_or_create_task_status("api-test-1", max_retries=3)
    ts.status = "running"
    ts.retry_count = 1
    
    response = client.get("/api/task-status?task_id=api-test-1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["task_id"] == "api-test-1"
    assert data["task"]["status"] == "running"
    assert data["task"]["retry_count"] == 1

def test_api_task_status_not_found():
    response = client.get("/api/task-status?task_id=nonexistent-task")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "not_found"


def test_task_status_populated_by_worker_ws_push():
    """t_14e40e6c regression: /api/task-status must reflect statuses the
    worker pushes over /ws/worker (the only cross-process writer), not just
    in-process writes to task_status_store. Red before the fix: the WS
    handler forwarded to SSE queues but never stored, so master always
    returned not_found mid-run."""
    from src.worker import task_status_store
    task_status_store.pop("ws-push-t1", None)
    ws_client = TestClient(app, client=("203.0.113.9", 1))
    with ws_client.websocket_connect(
        "/ws/worker?name=push-ws-worker",
        headers={"X-Cluster-Secret": master.CLUSTER_SECRET},
    ) as ws:
        ws.send_json({"type": "task_status_update", "task_id": "ws-push-t1",
                      "status": {"task_id": "ws-push-t1", "status": "running",
                                 "retry_count": 0, "max_retries": 3,
                                 "exit_code": None, "error": None,
                                 "updated_at": 1.0}})
        # Second push exercises the upsert (update, not create) path.
        ws.send_json({"type": "task_status_update", "task_id": "ws-push-t1",
                      "status": {"task_id": "ws-push-t1", "status": "done",
                                 "retry_count": 1, "max_retries": 3,
                                 "exit_code": 0, "error": None,
                                 "updated_at": 2.0}})
    try:
        data = client.get("/api/task-status?task_id=ws-push-t1").json()
        assert data["status"] == "ok"
        assert data["task"]["status"] == "done"
        assert data["task"]["exit_code"] == 0
        assert data["task"]["retry_count"] == 1
        listing = client.get("/api/task-status").json()
        assert "ws-push-t1" in listing["tasks"]
    finally:
        task_status_store.pop("ws-push-t1", None)


# =========================================================================
# P0 security gate (audit t_0fef205c): session auth on state-changing APIs,
# settings admin-token auth, PBKDF2 hashing with legacy upgrade, rate limits.
# The suite-wide conftest disables auth (kill switch); these tests opt back in.
# =========================================================================

import hashlib
import uuid

import web.main as master
from src.core import security
from src.core.db import user_create, user_get


def _auth_on(monkeypatch):
    monkeypatch.setattr(master, "authentication_enabled", lambda: True)
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)


def _settings_payload(**overrides):
    payload = {
        "master_url": "",
        "log_level": "INFO",
        "sim_cooldown_seconds": 300,
        "cors_enabled": False,
        "cors_allowed_origins": "",
        "ws_max_size": 1048576,
    }
    payload.update(overrides)
    return payload


def _generate_payload():
    return {
        "char_class": "paladin",
        "char_name": "Test",
        "base_profile": "paladin=Test",
        "equipped_gear": {},
        "selected_items": {},
    }


def test_run_simulation_unauthenticated_returns_401(monkeypatch):
    _auth_on(monkeypatch)
    anon = TestClient(app)
    response = anon.post("/api/run-simulation")
    assert response.status_code == 401


def test_invalid_session_cookie_returns_401(monkeypatch):
    _auth_on(monkeypatch)
    anon = TestClient(app)
    anon.cookies.set("session_id", "user-id-that-does-not-exist")
    response = anon.post("/api/parse-addon", json={"addon_text": "paladin=Test\nhead=id=123"})
    assert response.status_code == 401


def test_dev_mode_never_bypasses_api_session_gate(monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")
    anon = TestClient(app)
    assert anon.post("/api/run-simulation").status_code == 401
    assert anon.post("/api/parse-addon", json={"addon_text": "paladin=Test"}).status_code == 401
    assert anon.post("/api/generate-simc", json=_generate_payload()).status_code == 401
    assert anon.post("/api/armory-load", json={"name": "X-Y"}).status_code == 401
    assert anon.post("/session/some-user/update", json={"user_id": "some-user", "sim_time": 1.0}).status_code == 401
    assert anon.post("/api/update-simc").status_code == 401


def test_valid_session_passes_gate_run_simulation(monkeypatch):
    _auth_on(monkeypatch)
    username = f"sec-{uuid.uuid4().hex[:8]}"
    user_id = user_create(username, security.hash_password("pw-not-used"))
    monkeypatch.setattr(master.manager, "get_idle_worker", lambda: None)
    authed = TestClient(app)
    authed.cookies.set("session_id", master._issue_session(user_id))
    response = authed.post("/api/run-simulation")
    # Past the auth gate; fails later only because no workers are connected.
    assert response.status_code == 503


def test_settings_post_requires_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("WS_MAX_SIZE", "67108864")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    response = client.post("/api/settings", json=_settings_payload())
    assert response.status_code == 403
    ok = client.post(
        "/api/settings", json=_settings_payload(), headers={"X-Admin-Token": "test-admin-token"}
    )
    assert ok.status_code == 200


def test_settings_post_cannot_toggle_dev_mode(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "0")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("WS_MAX_SIZE", "67108864")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    response = client.post(
        "/api/settings",
        # Extra dev-mode field must be ignored (removed from the model).
        json=_settings_payload(simc_helper_dev_mode=True),
        headers={"X-Admin-Token": "test-admin-token"},
    )
    assert response.status_code == 200
    assert os.environ["SIMC_HELPER_DEV_MODE"] == "0"
    body = response.json()
    assert "simc_helper_dev_mode" not in body
    assert "ws_max_size" not in body


def test_settings_get_strips_sensitive_fields(monkeypatch):
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")
    body = client.get("/api/settings").json()
    assert set(body) == {
        "master_url",
        "log_level",
        "sim_cooldown_seconds",
        "cors_enabled",
        "cors_allowed_origins",
    }


def test_login_with_legacy_sha256_hash_succeeds_and_upgrades(monkeypatch):
    _auth_on(monkeypatch)
    master._login_failures.reset()
    username = f"legacy-{uuid.uuid4().hex[:8]}"
    password = "legacy-password-123"
    user_create(username, hashlib.sha256(password.encode()).hexdigest())

    anon = TestClient(app)
    response = anon.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )
    assert response.status_code == 303
    assert anon.cookies.get("session_id")

    stored = user_get(username)["password_hash"]
    assert stored.startswith("pbkdf2_sha256$")
    assert security.verify_password(password, stored)

    # Second login verifies against the upgraded hash...
    again = TestClient(app)
    response2 = again.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )
    assert response2.status_code == 303
    # ...and the issued session cookie passes the API gate (UI keeps working).
    gated = again.post("/api/parse-addon", json={"addon_text": "paladin=Test\nhead=id=123"})
    assert gated.status_code == 200
    master._login_failures.reset()


def test_register_stores_pbkdf2_hash(monkeypatch):
    _auth_on(monkeypatch)
    master._registrations.reset()
    username = f"reg-{uuid.uuid4().hex[:8]}"
    anon = TestClient(app)
    response = anon.post(
        "/register", data={"username": username, "password": "pw-123456"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert user_get(username)["password_hash"].startswith("pbkdf2_sha256$")
    master._registrations.reset()


def test_register_form_redirects_and_logs_in(monkeypatch):
    """t_e4d97db9: browser registration flow — GET page, 303 + session cookie,
    duplicate username still errors."""
    _auth_on(monkeypatch)
    master._registrations.reset()
    username = f"flow-{uuid.uuid4().hex[:8]}"
    anon = TestClient(app)

    page = anon.get("/register")
    assert page.status_code == 200
    assert 'action="register"' in page.text

    response = anon.post(
        "/register", data={"username": username, "password": "pw-123456"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "dashboard"
    # SEC-7 (t_0e328148): the cookie is an opaque token, not the user_id;
    # it must resolve to the new user through the server-side session store.
    from src.core.db import auth_session_user
    token = anon.cookies.get("session_id")
    assert token
    resolved = auth_session_user(token, time.time())
    assert resolved and resolved["user_id"] == user_get(username)["user_id"]
    assert anon.get("/dashboard").status_code == 200
    # The issued session passes the API gate, same as login's does.
    gated = anon.post("/api/parse-addon", json={"addon_text": "paladin=Test\nhead=id=123"})
    assert gated.status_code == 200

    # t_6f351b30 regression: browser form error 303s back to the register
    # page with the message as ?error= (styled error box), not raw JSON.
    dup = TestClient(app).post(
        "/register",
        data={"username": username, "password": "pw-123456"},
        follow_redirects=False,
    )
    assert dup.status_code == 303
    assert dup.headers["location"].startswith("register?error=")
    assert "Username%20already%20exists" in dup.headers["location"]
    assert "application/json" not in dup.headers.get("content-type", "")
    # API clients that explicitly ask for JSON keep the 400 status code.
    dup_api = TestClient(app).post(
        "/register",
        data={"username": username, "password": "pw-123456"},
        headers={"Accept": "application/json"},
    )
    assert dup_api.status_code == 400
    master._registrations.reset()


def test_session_cookie_secure_flag_follows_env(monkeypatch):
    """TLS front (t_d034f7e9): SIMC_COOKIE_SECURE=1 adds the Secure attribute."""
    _auth_on(monkeypatch)
    master._login_failures.reset()
    username = f"sec-{uuid.uuid4().hex[:8]}"
    user_create(username, security.hash_password("pw-123456"))

    monkeypatch.setattr(master, "COOKIE_SECURE", True)
    anon = TestClient(app)
    response = anon.post(
        "/login", data={"username": username, "password": "pw-123456"}, follow_redirects=False
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

    # Without the TLS front, loopback HTTP must keep working: no Secure.
    monkeypatch.setattr(master, "COOKIE_SECURE", False)
    anon2 = TestClient(app)
    response2 = anon2.post(
        "/login", data={"username": username, "password": "pw-123456"}, follow_redirects=False
    )
    assert response2.status_code == 303
    assert "Secure" not in response2.headers["set-cookie"]
    master._login_failures.reset()


def test_login_rate_limited_after_repeated_failures(monkeypatch):
    _auth_on(monkeypatch)
    master._login_failures.reset()
    username = f"rl-{uuid.uuid4().hex[:8]}"
    user_create(username, security.hash_password("correct-horse-battery"))
    anon = TestClient(app)
    json_headers = {"Accept": "application/json"}
    for _ in range(5):
        bad = anon.post("/login", data={"username": username, "password": "wrong"},
                        headers=json_headers)
        assert bad.status_code == 401
    limited = anon.post("/login", data={"username": username, "password": "wrong"},
                        headers=json_headers)
    assert limited.status_code == 429
    # While limited, even the correct password is refused (lockout by IP).
    blocked = anon.post("/login", data={"username": username, "password": "correct-horse-battery"},
                        headers=json_headers)
    assert blocked.status_code == 429
    # t_6f351b30: the browser form path gets 303 -> login?error= instead of
    # the raw JSON 429 document.
    form = anon.post(
        "/login", data={"username": username, "password": "wrong"}, follow_redirects=False
    )
    assert form.status_code == 303
    assert form.headers["location"].startswith("login?error=")
    master._login_failures.reset()


def test_login_form_error_redirects_with_error_param(monkeypatch):
    """t_6f351b30 regression: browser form login errors render as a styled
    error box on the login page (303 + ?error=), not a raw JSON document;
    JSON clients keep the 401 status code."""
    _auth_on(monkeypatch)
    master._login_failures.reset()
    username = f"formerr-{uuid.uuid4().hex[:8]}"
    user_create(username, security.hash_password("correct-horse-battery"))
    anon = TestClient(app)
    bad = anon.post(
        "/login", data={"username": username, "password": "wrong"}, follow_redirects=False
    )
    assert bad.status_code == 303
    assert bad.headers["location"].startswith("login?error=")
    assert "Invalid%20username%20or%20password" in bad.headers["location"]
    assert "application/json" not in bad.headers.get("content-type", "")
    api = anon.post(
        "/login",
        data={"username": username, "password": "wrong"},
        headers={"Accept": "application/json"},
    )
    assert api.status_code == 401
    master._login_failures.reset()


# =========================================================================
# P1 security (audit t_622b11ac): session IDOR scoping, secrets out of URLs,
# Wowhead proxy lockdown, metrics/health/state info-disclosure gating.
# =========================================================================


def _authed_client(user_id):
    authed = TestClient(app)
    authed.cookies.set("session_id", master._issue_session(user_id))
    return authed


# --- 1. Session IDOR (MEDIUM-1) -----------------------------------------

def test_get_session_route_requires_auth(monkeypatch):
    _auth_on(monkeypatch)
    anon = TestClient(app)
    assert anon.get("/session/whatever").status_code == 401


def test_get_session_foreign_user_id_returns_403(monkeypatch):
    _auth_on(monkeypatch)
    me = user_create(f"idor-a-{uuid.uuid4().hex[:8]}", security.hash_password("pw"))
    other = user_create(f"idor-b-{uuid.uuid4().hex[:8]}", security.hash_password("pw"))
    authed = _authed_client(me)
    assert authed.get(f"/session/{other}").status_code == 403
    own = authed.get(f"/session/{me}")
    assert own.status_code == 200
    assert own.json()["user_id"] == me


def test_update_session_foreign_user_id_returns_403(monkeypatch):
    _auth_on(monkeypatch)
    me = user_create(f"idor-c-{uuid.uuid4().hex[:8]}", security.hash_password("pw"))
    other = user_create(f"idor-d-{uuid.uuid4().hex[:8]}", security.hash_password("pw"))
    authed = _authed_client(me)
    response = authed.post(f"/session/{other}/update", json={"user_id": other, "sim_time": 1.0})
    assert response.status_code == 403
    # The victim's cooldown timestamp must be untouched.
    assert master.session_get(other) in (None, 0.0)
    ok = authed.post(f"/session/{me}/update", json={"user_id": me, "sim_time": 123.0})
    assert ok.status_code == 200
    assert master.session_get(me) == 123.0


def test_session_routes_open_under_auth_kill_switch(monkeypatch):
    # conftest already disables auth (require_session -> "anonymous"); the
    # own-session check must not break the login-free deployment mode.
    anon = TestClient(app)
    assert anon.get("/session/anyone").status_code == 200


# --- 2. Secrets out of URLs (MEDIUM-2) ----------------------------------

def test_admin_token_query_param_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "tok-123")
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("WS_MAX_SIZE", "67108864")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    response = client.post(f"/api/settings?admin_token=tok-123", json=_settings_payload())
    assert response.status_code == 403
    ok = client.post(
        "/api/settings", json=_settings_payload(), headers={"X-Admin-Token": "tok-123"}
    )
    assert ok.status_code == 200


def test_admin_token_query_param_allowed_in_dev_mode(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "tok-123")
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("WS_MAX_SIZE", "67108864")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    response = client.post(f"/api/settings?admin_token=tok-123", json=_settings_payload())
    assert response.status_code == 200


def test_upload_file_query_secret_rejected_in_production(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    response = client.post(
        f"/api/worker/upload-file?task_id=t1&file_name=q.txt&secret={master.CLUSTER_SECRET}",
        files={"file": ("q.txt", b"x")},
    )
    assert response.status_code == 403


def test_upload_file_query_secret_allowed_in_dev_mode(monkeypatch):
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")
    response = client.post(
        f"/api/worker/upload-file?task_id=t1&file_name=q2.txt&secret={master.CLUSTER_SECRET}",
        files={"file": ("q2.txt", b"x")},
    )
    assert response.status_code == 200


def test_worker_websocket_rejects_query_secret_in_production(monkeypatch):
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    ws_client = TestClient(app, client=("203.0.113.9", 1))
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(
            f"/ws/worker?name=w1&secret={master.CLUSTER_SECRET}"
        ):
            pass


def test_worker_websocket_accepts_cluster_secret_header(monkeypatch):
    ws_client = TestClient(app, client=("203.0.113.9", 1))
    with ws_client.websocket_connect(
        "/ws/worker?name=hdr-worker", headers={"X-Cluster-Secret": master.CLUSTER_SECRET}
    ):
        pass  # accepted; context manager closes cleanly


# --- 3. Wowhead proxy lockdown (MEDIUM-3) -------------------------------

def test_wowhead_proxy_rejects_traversal():
    response = client.get("/api/wowhead-nether/%2e%2e/%2e%2e/etc/passwd")
    assert response.status_code == 400


def test_wowhead_proxy_rejects_foreign_prefix():
    response = client.get("/api/wowhead-nether/admin/secret")
    assert response.status_code == 403


def test_wowhead_proxy_allows_tooltip_prefix(monkeypatch):
    seen = {}

    async def fake_fetch(url):
        seen["url"] = url
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"id": 1}',
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(master, "_nether_fetch", fake_fetch)
    response = client.get("/api/wowhead-nether/tooltip/item/123?dataEnv=1")
    assert response.status_code == 200
    assert seen["url"] == "https://nether.wowhead.com/tooltip/item/123?dataEnv=1"


# --- 4. Info disclosure gating (LOW-1) ----------------------------------

def test_metrics_requires_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "tok-metrics")
    anon = TestClient(app)
    assert anon.get("/metrics").status_code == 403
    ok = anon.get("/metrics", headers={"X-Admin-Token": "tok-metrics"})
    assert ok.status_code == 200
    assert "simc_requests_total" in ok.text


def test_health_trims_details_for_remote_caller():
    remote = TestClient(app, client=("203.0.113.9", 1))
    response = remote.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"} or set(response.json()) == {"status"}


def test_health_keeps_details_for_localhost():
    local = TestClient(app, client=("127.0.0.1", 4321))
    body = local.get("/health").json()
    assert "details" in body and "timestamp" in body
    assert "workers" in body["details"]


def test_health_keeps_details_for_admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "tok-health")
    remote = TestClient(app, client=("203.0.113.9", 1))
    body = remote.get("/health", headers={"X-Admin-Token": "tok-health"}).json()
    assert "details" in body


def test_api_state_requires_session(monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.setattr(master.manager, "active_workers", {})
    anon = TestClient(app)
    assert anon.get("/api/state").status_code == 401
    me = user_create(f"state-{uuid.uuid4().hex[:8]}", security.hash_password("pw"))
    authed = _authed_client(me)
    response = authed.get("/api/state")
    assert response.status_code == 200
    assert "workers" in response.json()


# =========================================================================
# t_ef8682a4: page auth must read the users table, not the purged
# user_sessions cooldown table; login must not seed the sim-run cooldown.
# =========================================================================

from src.core.db import session_cleanup_older_than, session_get


def _pages_under_auth(monkeypatch):
    """Auth on, and hide pytest so the page gates' dev bypass is inactive."""
    _auth_on(monkeypatch)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)


def _login_client(username: str, password: str) -> TestClient:
    c = TestClient(app)
    resp = c.post(
        "/login", data={"username": username, "password": password}, follow_redirects=False
    )
    assert resp.status_code == 303
    master._login_failures.reset()
    return c


def test_dashboard_survives_cooldown_purge(monkeypatch):
    """P0: users must not be logged out when the 300s cooldown purge runs."""
    _pages_under_auth(monkeypatch)
    username = f"purge-{uuid.uuid4().hex[:8]}"
    user_create(username, security.hash_password("pw-123456"))
    authed = _login_client(username, "pw-123456")

    # The enforcer's periodic purge, forced to delete every cooldown row.
    session_cleanup_older_than(0, time.time())

    assert authed.get("/dashboard", follow_redirects=False).status_code == 200
    assert authed.get("/results", follow_redirects=False).status_code == 200
    root = authed.get("/", follow_redirects=False)
    assert root.status_code == 303 and root.headers["location"] == "dashboard"
    login_page = authed.get("/login", follow_redirects=False)
    assert login_page.status_code == 303 and login_page.headers["location"] == "dashboard"


def test_page_gates_reject_unknown_session_cookie(monkeypatch):
    """The session-store check must still bounce forged/stale cookies."""
    _pages_under_auth(monkeypatch)
    anon = TestClient(app)
    anon.cookies.set("session_id", "user-id-that-does-not-exist")
    dash = anon.get("/dashboard", follow_redirects=False)
    assert dash.status_code == 303 and dash.headers["location"] == "login"
    assert anon.get("/results", follow_redirects=False).status_code == 303
    # Unauthenticated root serves the login page.
    assert anon.get("/", follow_redirects=False).status_code == 200


def test_login_does_not_seed_run_cooldown(monkeypatch):
    """P0: login -> immediate run-simulation is 200, not a bogus 429."""
    _auth_on(monkeypatch)
    username = f"cool-{uuid.uuid4().hex[:8]}"
    user_id = user_create(username, security.hash_password("pw-123456"))
    authed = _login_client(username, "pw-123456")
    # Login must not write cooldown state (user_create seeds 0.0 = ancient).
    assert session_get(user_id) in (None, 0.0)

    monkeypatch.setattr(master.manager, "get_idle_worker", lambda: "worker1")
    monkeypatch.setattr(master.manager, "send_task", AsyncMock(return_value=None))
    monkeypatch.setitem(master.manager.active_workers, "worker1", MagicMock(status="Idle"))
    try:
        # SEC-6: explicit input_id (fake worker never fetches it)
        first = authed.post("/api/run-simulation", params={"input_id": "qa-cooldown"})
        assert first.status_code == 200, first.text
        task_id = first.json()["task_id"]
        # The real cooldown still applies once a sim actually started.
        second = authed.post("/api/run-simulation")
        assert second.status_code == 429
    finally:
        master.manager.active_workers.pop("worker1", None)
        master.manager.task_queues.pop(task_id, None)


# ---------------------------------------------------------------------------
# t_b3b78acd — run_history table + task-done insert hook
# ---------------------------------------------------------------------------

def _rh_user(tag):
    """Create a throwaway registered user and return its user_id."""
    return user_create(f"rh-{tag}-{uuid.uuid4().hex[:8]}", security.hash_password("pw"))


def test_run_history_table_and_index_exist():
    """t_b3b78acd: init_db creates run_history and the (user_id, created_at DESC) index."""
    import sqlite3

    from src.core.db import get_db_path

    conn = sqlite3.connect(get_db_path())
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(run_history)")}
        assert {
            "run_id", "user_id", "created_at", "fighting_style", "spec",
            "source", "char_name", "realm_slug", "region", "top_dps",
            "report_path", "status",
        } <= cols
        idx = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' "
            "AND name='idx_run_history_user_created'"
        ).fetchone()
        assert idx and "created_at DESC" in idx[0]
    finally:
        conn.close()


def test_run_history_insert_list_and_cascade():
    """t_b3b78acd: rows insert, list newest-first, and vanish with the user (FK CASCADE)."""
    from src.core.db import run_history_insert, run_history_list

    uid = _rh_user("cascade")
    base = time.time()
    run_ids = [f"rh-casc-{uuid.uuid4().hex[:8]}-{i}" for i in range(2)]
    for i, dps in enumerate((100, 200)):
        run_history_insert({
            "run_id": run_ids[i], "user_id": uid, "created_at": base + i,
            "fighting_style": "single_target", "spec": "ret", "source": "armory",
            "char_name": "Casc", "realm_slug": "rerun", "region": "eu",
            "top_dps": dps, "report_path": f"{uid}/t{dps}/report_{dps}.html",
            "status": "success",
        })
    rows = run_history_list(uid)
    assert [r["top_dps"] for r in rows] == [200, 100]  # newest first
    assert rows[0]["realm_slug"] == "rerun"

    from src.core.db import user_delete
    user_delete(uid)
    assert run_history_list(uid) == []


def test_run_history_fk_rejects_unknown_user():
    """t_b3b78acd: user_id is a real FK — rows for unknown users are refused."""
    import sqlite3

    from src.core.db import run_history_insert

    with pytest.raises(sqlite3.IntegrityError):
        run_history_insert({
            "run_id": "rh-orphan", "user_id": "no-such-user",
            "created_at": time.time(), "status": "success",
        })


def test_record_run_history_success_extracts_top_dps():
    """t_b3b78acd: the done hook writes a row with top_dps from the report parser
    and report_path relative to REPORTS_DIR."""
    import shutil

    import web.main as m
    from src.core.db import run_history_list

    uid = _rh_user("hist1")
    task = "thist1"
    user_dir = m._user_report_dir(uid)
    task_dir = os.path.join(MASTER_REPORTS_DIR, user_dir, task)
    shutil.rmtree(task_dir, ignore_errors=True)
    os.makedirs(task_dir)
    with open(os.path.join(task_dir, "report_1.html"), "w") as f:
        f.write(
            '<h2 class="toggle">Base&#160;:&#160;1000 dps</h2>'
            '<h2 id="player2toggle" class="toggle"">Winner&#160;:&#160;2500 dps</h2>'
        )
    m.task_user_map[task] = uid
    m.task_meta_map[task] = {
        "fighting_style": "aoe", "spec": "fire", "source": "armory",
        "char_name": "Zed", "realm_slug": "dragonblight", "region": "eu",
    }
    try:
        m._record_run_history(task, "success")
        rows = run_history_list(uid)
        assert len(rows) == 1
        row = rows[0]
        assert row["top_dps"] == 2500
        assert row["status"] == "success"
        assert row["report_path"] == os.path.join(user_dir, task, "report_1.html")
        assert row["fighting_style"] == "aoe"
        assert row["spec"] == "fire"
        assert row["source"] == "armory"
        assert row["char_name"] == "Zed"
        assert row["realm_slug"] == "dragonblight"
        assert row["region"] == "eu"
        assert task not in m.task_meta_map  # snapshot consumed
    finally:
        m.task_user_map.pop(task, None)
        m.task_meta_map.pop(task, None)
        shutil.rmtree(task_dir, ignore_errors=True)
        from src.core.db import user_delete as _ud
        _ud(uid)


def test_record_run_history_failed_without_report():
    """t_b3b78acd: a failed run still lands in history with null dps/path."""
    import web.main as m
    from src.core.db import run_history_list

    uid = _rh_user("hist2")
    task = "thist2"
    m.task_user_map[task] = uid
    m.task_meta_map[task] = {"source": "addon", "char_name": "Fails"}
    try:
        m._record_run_history(task, "failed")
        rows = run_history_list(uid)
        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert rows[0]["top_dps"] is None
        assert rows[0]["report_path"] is None
        assert rows[0]["char_name"] == "Fails"
    finally:
        m.task_user_map.pop(task, None)
        m.task_meta_map.pop(task, None)
        from src.core.db import user_delete as _ud
        _ud(uid)


def test_record_run_history_swallows_fk_violation():
    """t_b3b78acd: anonymous/ip owners (no users row) must not raise from the SSE hook."""
    import web.main as m
    from src.core.db import run_history_list

    task = "thist3"
    m.task_user_map[task] = f"ip_10_0_0_{uuid.uuid4().hex[:6]}"
    try:
        m._record_run_history(task, "success")  # must not raise
        assert run_history_list(m.task_user_map[task]) == []
    finally:
        m.task_user_map.pop(task, None)
        m.task_meta_map.pop(task, None)


def test_generate_simc_captures_run_metadata():
    """t_b3b78acd: generate-simc snapshots fighting_style/spec/char_name and
    defaults source to 'addon' when no load step ran."""
    import web.main as m

    before = {k: dict(v) for k, v in m.run_meta_by_user.items()}
    payload = {
        "base_profile": "mage=Histy\nspec=fire",
        "char_class": "mage",
        "char_name": "Histy",
        "equipped_gear": {"head": "id=1"},
        "selected_items": {"head": ["id=1", "id=2"]},
        "selected_enchants": {},
        "selected_gems": [],
    }
    with patch(
        "src.cli.generate_input.load_config",
        return_value={"gems": {"meta": [], "standard": []}, "enchantments": {}},
    ):
        response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200

    fresh = {k: v for k, v in m.run_meta_by_user.items() if before.get(k) != v}
    assert fresh, "generate-simc did not record run metadata"
    meta = next(iter(fresh.values()))
    assert meta["char_name"] == "Histy"
    assert meta["spec"] == "fire"
    assert meta["source"] == "addon"
    assert meta["fighting_style"] == master.FIGHT_STYLE_SINGLE_BOSS


def test_run_simulation_snapshots_task_metadata(monkeypatch):
    """t_b3b78acd: run_simulation freezes the user's run metadata per task."""
    import web.main as m
    from src.core.db import session_cleanup_older_than

    _auth_on(monkeypatch)  # real session -> current_user is the created user
    uid = _rh_user("snap")
    m.run_meta_by_user[uid] = {"source": "armory", "char_name": "Snap"}
    m.user_last_sim_time.pop(uid, None)
    session_cleanup_older_than(0, time.time())
    task_id = None
    try:
        with patch.object(manager, "get_idle_worker", return_value="worker-snap"), \
             patch.object(manager, "send_task", return_value=None):
            manager.active_workers["worker-snap"] = MagicMock(status="Idle")
            authed = _authed_client(uid)
            # SEC-6: explicit input_id (fake worker never fetches it)
            response = authed.post("/api/run-simulation", params={"input_id": "qa-snap"})
            assert response.status_code == 200
            task_id = response.json()["task_id"]
        assert m.task_meta_map[task_id] == {"source": "armory", "char_name": "Snap"}
    finally:
        if task_id:
            m.task_meta_map.pop(task_id, None)
        m.run_meta_by_user.pop(uid, None)
        manager.active_workers.pop("worker-snap", None)
        from src.core.db import user_delete as _ud
        _ud(uid)
