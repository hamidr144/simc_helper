import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import app, manager, parse_wowhead_upgrade, wowhead_xml_url

client = TestClient(app)

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert "user_id" in client.cookies

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
            response = client.post("/api/run-simulation")
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
        response = client.post("/api/run-simulation")
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

    assert generated.count("head=,id=1,ilevel=626,bonus_id=100") == 2
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

    assert generated.count("head=,id=1,ilevel=289,bonus_id=100") == 2
    assert "head=,id=1,ilevel=220" not in generated
    assert "trinket1=,id=2,ilevel=298" in generated
    assert "trinket1=,id=20,ilevel=285" in generated


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
    reports_dir = "/tmp/simc_reports"
    os.makedirs(os.path.join(reports_dir, task_id), exist_ok=True)
    with open(os.path.join(reports_dir, task_id, "report_t.html"), "w") as f:
        f.write('<h2 class="toggle">C1&#160;:&#160;100,000 dps</h2>')

    response = client.get(f"/api/get-results?task_id={task_id}")
    assert response.status_code == 200
    assert response.json()["results"][0]["name"] == "C1"

def test_api_upload_file():
    from web.main import CLUSTER_SECRET
    file_content = b"fake data"
    response = client.post(
        f"/api/worker/upload-file?task_id=t1&file_name=test.txt&secret={CLUSTER_SECRET}",
        files={"file": ("test.txt", file_content)}
    )
    assert response.status_code == 200
    assert os.path.exists("/tmp/simc_reports/t1/test.txt")


def test_api_upload_file_rejects_path_traversal_filename():
    from web.main import CLUSTER_SECRET
    response = client.post(
        f"/api/worker/upload-file?task_id=t1&file_name=../evil.txt&secret={CLUSTER_SECRET}",
        files={"file": ("evil.txt", b"bad")}
    )
    assert response.status_code == 400
    assert not os.path.exists("/tmp/simc_reports/evil.txt")


def test_api_upload_file_rejects_path_traversal_task_id():
    from web.main import CLUSTER_SECRET
    outside_path = "/tmp/upload_task_escape.txt"
    if os.path.exists(outside_path):
        os.remove(outside_path)

    response = client.post(
        f"/api/worker/upload-file?task_id=..&file_name=upload_task_escape.txt&secret={CLUSTER_SECRET}",
        files={"file": ("upload_task_escape.txt", b"bad")}
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
        f"/api/worker/upload-file?task_id=tzip&file_name=artifacts.zip&secret={CLUSTER_SECRET}",
        files={"file": ("artifacts.zip", payload.getvalue())}
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
    reports_dir = "/tmp/simc_reports"
    os.makedirs(os.path.join(reports_dir, task_id), exist_ok=True)
    with open(os.path.join(reports_dir, task_id, "report_c.html"), "w") as f:
        f.write('<h2 class="toggle">A&#160;:&#160;1,234,567 dps</h2>\n<h2 class="toggle">B&#160;:&#160;987,654 dps</h2>')

    response = client.get(f"/api/get-results?task_id={task_id}")
    res = {r["name"]: r["dps"] for r in response.json()["results"]}
    assert res["A"] == 1234567
    assert res["B"] == 987654


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

