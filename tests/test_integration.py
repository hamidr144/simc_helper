"""Integration (end-to-end) tests for the FastAPI application.

These tests exercise the full request → handler → response cycle using
FastAPI's TestClient, simulating how a real client would interact with
the master server across multiple related endpoints.

Each test group represents a realistic user workflow:
  1. Parse an addon export → generate a SimC profile
  2. Run a simulation and retrieve results (mocking workers)
  3. Task status tracking
  4. Health, config, and state endpoints
"""

import json
import os
import sqlite3
import sys
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure the project src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Re-import after sys.path is set so all modules use the right path
from src.web.main import app, manager, CLUSTER_SECRET  # noqa: E402
from src.web.main import user_last_sim_time  # noqa: E402

# Fix deprecation warning from starlette
import warnings  # noqa: E402
warnings.filterwarnings("ignore", category=DeprecationWarning, module="starlette")


def _clear_db_sessions():
    """Clear the user_sessions table to reset rate limits."""
    db_path = os.path.join("data", "master", "simc_helper.sqlite")
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM user_sessions")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_state():
    """Clean up rate limit and worker state between tests."""
    # Clear before each test
    user_last_sim_time.clear()
    _clear_db_sessions()
    for wid in list(manager.active_workers.keys()):
        try:
            manager.disconnect(wid)
        except RuntimeError:
            # No event loop - skip disconnect
            pass
    yield
    # Cleanup after each test
    for wid in list(manager.active_workers.keys()):
        try:
            manager.disconnect(wid)
        except RuntimeError:
            # No event loop - skip disconnect
            pass
    user_last_sim_time.clear()
    _clear_db_sessions()


@pytest.fixture
def client():
    """FastAPI TestClient with a fresh app."""
    return TestClient(app)


# ===================================================================
# 1. Parse Addon → Generate Profile workflow
# ===================================================================

SAMPLE_ADDON = """\
paladin=TestPaladin
level=90
race=blood_elf
classid=2
spec=1
talents=0-0-531
# Head
# Neck
# Shoulder
# Back
# Chest
# Wrist
# Hands
# Waist
# Legs
# Feet
# Finger1
# Finger2
# Trinket1
# Trinket2
# Main Hand
# Off Hand
### Gear from Bags
# head=id=100100
# Should of Valor
# shoulder=id=100200
# Neck of Valor
# neck=id=100300
# Back of Valor
# back=id=100400
# Chest of Valor
# chest=id=100500
# Wrist of Valor
# wrist=id=100600
# Hands of Valor
# hands=id=100700
# Waist of Valor
# waist=id=100800
# Legs of Valor
# legs=id=100900
# Feet of Valor
# feet=id=101000
# Ring of Valor 1
# finger1=id=101100
# Ring of Valor 2
# finger2=id=101200
# Trinket of Valor 1
# trinket1=id=101300
# Trinket of Valor 2
# trinket2=id=101400
# Sword of Valor
# main_hand=id=101500
# Off-hand of Valor
# off_hand=id=101600
### Additional Character Info
"""


class TestParseAddonE2E:
    """End-to-end: parse an addon text via the API."""

    def test_parse_addon_returns_structured_data(self, client):
        """POST /api/parse-addon should return parsed character data."""
        response = client.post(
            "/api/parse-addon",
            json={"addon_text": SAMPLE_ADDON},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["char_name"] == "TestPaladin"
        assert data["char_class"] == "paladin"
        assert data["equipped_gear"] == {}
        # Bag items should be in items_by_slot
        assert "head" in data["items_by_slot"]
        assert "id=100100" in data["items_by_slot"]["head"]
        assert "id=100200" in data["items_by_slot"]["shoulder"]
        # Item names from comments
        assert data["item_names"].get("id=100200") == "Should of Valor"
        assert data["item_names"].get("id=100300") == "Neck of Valor"

    def test_parse_addon_with_empty_text(self, client):
        """Parsing empty addon text should return defaults."""
        response = client.post(
            "/api/parse-addon",
            json={"addon_text": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["char_name"] == "Unknown"
        assert data["char_class"] == "Unknown"

    def test_parse_addon_invalid_payload_returns_422(self, client):
        """Sending non-dict body should return 422 validation error."""
        response = client.post("/api/parse-addon", json="not a dict")
        assert response.status_code == 422

    def test_parse_addon_finger_trinket_slots_merged(self, client):
        """Finger1/Finger2 and Trinket1/Trinket2 should be merged."""
        addon = "rogue=Test\n### Gear from Bags\n# finger1=id=1\n# finger2=id=2\n# trinket1=id=3\n# trinket2=id=4\n### Additional Character Info"
        response = client.post("/api/parse-addon", json={"addon_text": addon})
        assert response.status_code == 200
        data = response.json()
        assert "finger" in data["items_by_slot"]
        assert "id=1" in data["items_by_slot"]["finger"]
        assert "id=2" in data["items_by_slot"]["finger"]
        assert "trinket" in data["items_by_slot"]
        assert "id=3" in data["items_by_slot"]["trinket"]
        assert "id=4" in data["items_by_slot"]["trinket"]


class TestGenerateSimcProfileE2E:
    """End-to-end: generate a SimC profile."""

    def test_generate_simc_creates_file(self, client):
        """POST /api/generate-simc should write a .simc file."""
        payload = {
            "char_class": "warrior",
            "char_name": "TestWarrior",
            "base_profile": "warrior=TestWarrior\nlevel=90\nrace=goblin",
            "equipped_gear": {"head": "id=100", "chest": "id=200"},
            "selected_items": {"head": ["id=100"], "chest": ["id=200"]},
            "selected_enchants": {},
            "selected_gems": [],
            "selected_meta_gems": [],
            "item_levels": {},
            "gear_upgrades": {},
            "voidforged_items": {},
            "extra_sockets": {},
        }
        response = client.post(
            "/api/generate-simc",
            json=payload,
            headers={"X-User-ID": "test-user-1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "input_id" in data
        assert "input_url" in data
        assert "file_path" in data
        assert data["file_path"].endswith(".simc")
        # The file should actually exist on disk
        assert os.path.isfile(data["file_path"])

    def test_generate_simc_returns_combinations(self, client):
        """POST /api/generate-simc should return a combinations count."""
        payload = {
            "char_class": "mage",
            "char_name": "ComboMage",
            "base_profile": "mage=ComboMage\nlevel=90",
            "equipped_gear": {},
            "selected_items": {},
            "selected_enchants": {},
            "selected_gems": [],
            "selected_meta_gems": [],
            "item_levels": {},
            "gear_upgrades": {},
            "voidforged_items": {},
            "extra_sockets": {},
        }
        response = client.post(
            "/api/generate-simc",
            json=payload,
            headers={"X-User-ID": "combo-user"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "combinations" in data
        assert isinstance(data["combinations"], int)


# ===================================================================
# 2. Health, Config, and State endpoints
# ===================================================================

class TestHealthEndpointE2E:
    """End-to-end: health check."""

    def test_health_returns_ok(self, client):
        """GET /health should return status + details."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("ok", "degraded")
        assert "timestamp" in data
        assert "details" in data
        assert "workers" in data["details"]
        assert "disk_space" in data["details"]
        assert "connected" in data["details"]["workers"]
        assert "idle" in data["details"]["workers"]
        assert "busy" in data["details"]["workers"]

    def test_health_disk_space_has_inputs_dir(self, client):
        """Disk space details should include inputs_dir path."""
        response = client.get("/health")
        data = response.json()
        assert "inputs_dir" in data["details"]["disk_space"]
        assert isinstance(data["details"]["disk_space"]["total_bytes"], int)
        assert isinstance(data["details"]["disk_space"]["free_bytes"], int)


class TestConfigAndStateE2E:
    """End-to-end: config and state endpoints."""

    def test_get_config_returns_json(self, client):
        """GET /api/config should return config.json content."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_state_returns_ready_status(self, client):
        """GET /api/state should return current state."""
        response = client.get("/api/state")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "workers" in data
        assert isinstance(data["workers"], list)
        assert "active_input" in data

    def test_task_status_list(self, client):
        """GET /api/task-status without task_id should list all tasks."""
        response = client.get("/api/task-status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "tasks" in data
        assert "total" in data
        assert isinstance(data["total"], int)


# ===================================================================
# 3. Task status tracking
# ===================================================================

class TestTaskStatusTrackingE2E:
    """End-to-end: task status through the system."""

    def test_create_and_track_task(self, client):
        """Creating a task should make it visible in task-status."""
        # First create an input file
        payload = {
            "char_class": "druid",
            "char_name": "TaskTestDruid",
            "base_profile": "druid=TaskTestDruid\nlevel=90",
            "equipped_gear": {},
            "selected_items": {},
            "selected_enchants": {},
            "selected_gems": [],
            "selected_meta_gems": [],
            "item_levels": {},
            "gear_upgrades": {},
            "voidforged_items": {},
            "extra_sockets": {},
        }
        gen_response = client.post(
            "/api/generate-simc",
            json=payload,
            headers={"X-User-ID": "task-user"},
        )
        assert gen_response.status_code == 200

        # Mock a worker and run the simulation
        with patch.object(manager, "get_idle_worker", return_value="worker1"), \
             patch.object(manager, "send_task", return_value=MagicMock()):
            manager.active_workers["worker1"] = MagicMock(status="Idle")
            run_response = client.post(
                "/api/run-simulation",
                json={"input_id": gen_response.json()["input_id"]},
                headers={"X-User-ID": "task-user"},
            )
            assert run_response.status_code == 200
            task_id = run_response.json()["task_id"]

        # Check task status - the task is tracked via task_queues, not task_status_store
        # until the worker sends results back
        assert task_id in manager.task_queues

    def test_task_status_for_unknown_task(self, client):
        """Requesting a non-existent task should return 'not_found'."""
        fake_id = f"fake-{uuid.uuid4().hex}"
        response = client.get(f"/api/task-status?task_id={fake_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"
        assert data["task_id"] == fake_id


# ===================================================================
# 4. Results pipeline
# ===================================================================

class TestResultsPipelineE2E:
    """End-to-end: write results and retrieve them."""

    def test_get_results_returns_empty_when_none(self, client):
        """GET /api/get-results for unknown task_id should return error."""
        response = client.get("/api/get-results?task_id=unknown-task-xyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "message" in data

    def test_get_results_with_real_file(self, client):
        """Writing a result file then fetching it should work."""
        task_id = f"results-test-{uuid.uuid4().hex}"
        results_dir = f"/tmp/simc_reports/{task_id}"
        os.makedirs(results_dir, exist_ok=True)

        result_file = os.path.join(results_dir, "report_1.html")
        with open(result_file, "w") as f:
            f.write('<h2 class="toggle">Test&#160;:&#160;1234 dps</h2>')

        response = client.get(f"/api/get-results?task_id={task_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "results" in data
        assert len(data["results"]) >= 1
        # Clean up
        os.remove(result_file)
        os.rmdir(results_dir)

    def test_get_results_rejects_path_traversal(self, client):
        """Task IDs with path traversal should be rejected."""
        evil_id = "../etc/passwd"
        response = client.get(f"/api/get-results?task_id={evil_id}")
        assert response.status_code == 400


# ===================================================================
# 5. Full workflow: addon → generate → task → results
# ===================================================================

class TestFullWorkflowE2E:
    """Complete end-to-end: parse addon → generate profile → run → results."""

    def test_parse_to_results_pipeline(self, client):
        """A user parses an addon, generates a profile, runs a sim, gets results."""
        # Step 1: Parse addon
        parse_resp = client.post(
            "/api/parse-addon",
            json={"addon_text": SAMPLE_ADDON},
        )
        assert parse_resp.status_code == 200
        parsed = parse_resp.json()
        assert parsed["char_name"] == "TestPaladin"
        assert parsed["char_class"] == "paladin"
        assert len(parsed["items_by_slot"]) > 0

        # Step 2: Generate SimC profile (using parsed data)
        generate_payload = {
            "char_class": parsed["char_class"],
            "char_name": parsed["char_name"],
            "base_profile": parsed["base_profile"],
            "equipped_gear": parsed["equipped_gear"],
            "selected_items": parsed["items_by_slot"],
            "selected_enchants": {},
            "selected_gems": [],
            "selected_meta_gems": [],
            "item_levels": {},
            "gear_upgrades": {},
            "voidforged_items": {},
            "extra_sockets": {},
        }
        gen_resp = client.post(
            "/api/generate-simc",
            json=generate_payload,
            headers={"X-User-ID": "pipeline-user"},
        )
        assert gen_resp.status_code == 200
        assert gen_resp.json()["status"] == "success"
        file_path = gen_resp.json()["file_path"]

        # Step 3: Verify the input file exists
        assert os.path.exists(file_path)

        # Step 4: Run simulation (mock worker since none are available)
        with patch.object(manager, "get_idle_worker", return_value="worker-pipeline"), \
             patch.object(manager, "send_task", return_value=MagicMock()):
            manager.active_workers["worker-pipeline"] = MagicMock(status="Idle")
            run_resp = client.post(
                "/api/run-simulation",
                json={"input_id": gen_resp.json()["input_id"]},
                headers={"X-User-ID": "pipeline-user"},
            )
            assert run_resp.status_code == 200
            task_id = run_resp.json()["task_id"]

        # Step 5: Verify task is tracked in task_queues (task_status_store is populated
        # only when the worker sends results back via WebSocket)
        assert task_id in manager.task_queues

        # Step 6: Simulate worker completing the task
        from src.worker import task_status_store

        status = task_status_store.get(task_id)
        if status:
            status.status = "complete"
            status.exit_code = 0
            status.updated_at = time.time()

        # Step 7: Write a fake result
        task_dir = f"/tmp/simc_reports/{task_id}"
        os.makedirs(task_dir, exist_ok=True)
        result_file = os.path.join(task_dir, "report_1.html")
        with open(result_file, "w") as f:
            f.write('<h2 class="toggle">Test&#160;:&#160;5678 dps</h2>')

        # Step 8: Retrieve results
        results_resp = client.get(f"/api/get-results?task_id={task_id}")
        assert results_resp.status_code == 200
        results_data = results_resp.json()
        assert results_data["status"] == "success"
        assert "results" in results_data
        assert len(results_data["results"]) >= 1

        # Cleanup
        if os.path.exists(task_dir):
            import shutil
            shutil.rmtree(task_dir, ignore_errors=True)

    def test_health_before_and_after_workflow(self, client):
        """Health endpoint should show consistent state through workflow."""
        health_before = client.get("/health").json()
        assert health_before["status"] in ("ok", "degraded")
        # Run a simple request
        client.post(
            "/api/parse-addon",
            json={"addon_text": "mage=Test"},
        )
        health_after = client.get("/health").json()
        assert health_after["status"] in ("ok", "degraded")
        # Disk space should still be reported
        assert health_after["details"]["disk_space"]["total_bytes"] > 0


# ===================================================================
# 6. Worker file upload
# ===================================================================

class TestWorkerFileUploadE2E:
    """End-to-end: worker file upload endpoint."""

    def test_worker_upload_file_succeeds(self, client):
        """POST /api/worker/upload-file should store the uploaded file."""
        task_id = f"upload-{uuid.uuid4().hex}"
        file_content = b"test file content for upload"
        response = client.post(
            f"/api/worker/upload-file?task_id={task_id}&file_name=test.txt&secret={CLUSTER_SECRET}",
            files={"file": ("test.txt", file_content, "text/plain")},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_worker_upload_file_rejects_traversal(self, client):
        """Filename with path traversal should be rejected."""
        response = client.post(
            "/api/worker/upload-file?task_id=test-traversal&file_name=../etc/evil.txt&secret=CLUSTER_SECRET",
            files={"file": ("evil.txt", b"bad", "text/plain")},
        )
        assert response.status_code in (400, 403)
