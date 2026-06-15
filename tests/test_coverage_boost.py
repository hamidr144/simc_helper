import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from cli.sim_helper import filter_best
from web.main import app, manager

client = TestClient(app)

def test_api_run_simulation_no_idle_workers():
    # Ensure no workers
    manager.active_workers = {}
    with patch.object(manager, "get_idle_worker", return_value=None):
        response = client.post("/api/run-simulation", params={"worker_id": "nonexistent"})
        assert response.status_code == 503
        assert "No idle workers available" in response.json()["detail"]

def test_api_run_simulation_worker_busy():
    manager.active_workers["busy_worker"] = MagicMock(status="Busy")
    response = client.post("/api/run-simulation", params={"worker_id": "busy_worker"})
    assert response.status_code == 503
    # Our logic returns "No idle workers available" if the specific worker is busy too
    assert "workers available" in response.json()["detail"]

def test_api_run_simulation_send_task_error():
    manager.active_workers["idle_worker"] = MagicMock(status="Idle")
    with patch.object(manager, "send_task", side_effect=Exception("Failed")):
        response = client.post("/api/run-simulation", params={"worker_id": "idle_worker"})
        assert response.status_code == 500

def test_api_simulation_stream_not_found():
    response = client.get("/api/simulation/stream/notfound?worker_id=w1")
    assert response.status_code == 404

def test_filter_best_empty():
    with patch("cli.sim_helper.os.path.exists", return_value=False):
        assert filter_best("dummy_path", 10, "relative") == []

def test_upload_file_invalid_file(tmp_path):
    from web.main import CLUSTER_SECRET
    response = client.post("/api/worker/upload-file", files={"file": ("test.txt", b"data")}, params={"task_id": "t1", "file_name": "report_1.html", "secret": CLUSTER_SECRET})
    assert response.status_code == 200 # It accepts it and processes it

def test_enforcer_exception():
    from web.main import enforcer, user_last_sim_time
    # Ensure no exception escapes
    user_last_sim_time["test"] = 0
    import asyncio
    
    async def run_enforcer_briefly():
        task = asyncio.create_task(enforcer())
        await asyncio.sleep(0.1)
        task.cancel()
        
    asyncio.run(run_enforcer_briefly())
