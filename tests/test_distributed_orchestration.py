import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import app, manager


def test_worker_registration_basic():
    # Use direct manager calls instead of full websocket client for unit tests
    manager.active_workers = {}
    mock_ws = MagicMock(spec=["accept", "send_json", "receive_json", "close"])
    mock_ws.accept = AsyncMock()

    # We wrap the connect in a small function since it's async
    async def do_connect():
        return await manager.connect(mock_ws, "TestWorker")

    worker_id = asyncio.run(do_connect())

    assert worker_id in manager.active_workers
    assert manager.active_workers[worker_id].name == "TestWorker"
    assert manager.active_workers[worker_id].status == "Idle"

def test_manager_get_idle_worker():
    manager.active_workers = {}
    w1 = MagicMock(status="Busy")
    w2 = MagicMock(status="Idle")
    manager.active_workers["id1"] = w1
    manager.active_workers["id2"] = w2

    assert manager.get_idle_worker() == "id2"

def test_manager_disconnect():
    manager.active_workers = {"id1": MagicMock(name="N1", current_task=None)}
    manager.disconnect("id1")
    assert "id1" not in manager.active_workers

@pytest.mark.asyncio
async def test_websocket_auth_fail():
    client = TestClient(app)
    with pytest.raises(Exception): # Starlette raises if close(1008)
        with client.websocket_connect("/ws/worker?name=W&secret=wrong"):
            pass
