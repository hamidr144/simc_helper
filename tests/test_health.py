import datetime
import os
import sys
import time
from unittest.mock import MagicMock, patch

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
from fastapi.testclient import TestClient

from web.main import app, manager

client = TestClient(app)


# ---------------------------------------------------------------------------
# Basic health endpoint
# ---------------------------------------------------------------------------

def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200


def test_health_json_structure():
    response = client.get("/health")
    data = response.json()

    assert "status" in data
    assert "timestamp" in data
    assert "details" in data


def test_health_status_field():
    response = client.get("/health")
    data = response.json()
    assert data["status"] in ("ok", "degraded")


def test_health_timestamp_is_iso8601():
    response = client.get("/health")
    data = response.json()
    ts = data["timestamp"]
    # Should parse without error
    datetime.datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# Worker connectivity details
# ---------------------------------------------------------------------------

def test_health_details_has_workers():
    response = client.get("/health")
    data = response.json()
    assert "workers" in data["details"]
    workers = data["details"]["workers"]
    assert "connected" in workers
    assert "idle" in workers
    assert "busy" in workers


def test_health_worker_counts_match_manager():
    response = client.get("/health")
    data = response.json()
    actual_workers = list(manager.active_workers.values())
    assert data["details"]["workers"]["connected"] == len(actual_workers)
    assert data["details"]["workers"]["idle"] == sum(
        1 for w in actual_workers if w.status == "Idle"
    )
    assert data["details"]["workers"]["busy"] == sum(
        1 for w in actual_workers if w.status == "Busy"
    )


def test_health_with_idle_workers():
    # Create a mock idle worker
    mock_ws = MagicMock()
    mock_ws.accept = MagicMock()
    wid = manager.active_workers["test-idle-ws"] = MagicMock()
    wid.id = "test-wid"
    wid.name = "TestWorker"
    wid.status = "Idle"
    wid.ws = mock_ws
    wid.last_ping = time.time()

    try:
        response = client.get("/health")
        data = response.json()
        workers = data["details"]["workers"]
        assert workers["connected"] == 1
        assert workers["idle"] == 1
        assert workers["busy"] == 0
    finally:
        del manager.active_workers["test-idle-ws"]


def test_health_with_busy_worker():
    mock_ws = MagicMock()
    mock_ws.accept = MagicMock()
    busy = MagicMock()
    busy.id = "busy-wid"
    busy.name = "BusyWorker"
    busy.status = "Busy"
    busy.ws = mock_ws
    busy.last_ping = time.time()
    manager.active_workers["test-busy-ws"] = busy

    try:
        response = client.get("/health")
        data = response.json()
        workers = data["details"]["workers"]
        assert workers["connected"] == 1
        assert workers["idle"] == 0
        assert workers["busy"] == 1
    finally:
        del manager.active_workers["test-busy-ws"]


# ---------------------------------------------------------------------------
# Disk space check
# ---------------------------------------------------------------------------

def test_health_details_has_disk_space():
    response = client.get("/health")
    data = response.json()
    assert "disk_space" in data["details"]
    disk = data["details"]["disk_space"]
    assert "total_bytes" in disk
    assert "used_bytes" in disk
    assert "free_bytes" in disk
    assert "free_percent" in disk
    assert "inputs_dir" in disk


def test_health_disk_space_values_are_positive():
    response = client.get("/health")
    data = response.json()
    disk = data["details"]["disk_space"]
    assert disk["total_bytes"] > 0
    assert disk["free_bytes"] >= 0


def test_health_disk_inputs_dir_points_to_actual_dir():
    response = client.get("/health")
    data = response.json()
    disk = data["details"]["disk_space"]
    assert disk["inputs_dir"].endswith("inputs")
    assert os.path.isdir(disk["inputs_dir"])
