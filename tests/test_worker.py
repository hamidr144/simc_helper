import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from worker import (
    TaskStatus,
    _calculate_retry_backoff,
    download_input_file,
    get_or_create_task_status,
    process_logs,
    run_worker,
    task_status_store,
)


def test_simc_update_due_on_startup_and_after_interval():
    from worker import should_update_simc

    assert should_update_simc(last_update_time=None, now=1000, interval_seconds=86400)
    assert not should_update_simc(last_update_time=1000, now=2000, interval_seconds=86400)
    assert should_update_simc(last_update_time=1000, now=87400, interval_seconds=86400)
    assert not should_update_simc(last_update_time=None, now=1000, interval_seconds=0)


@pytest.mark.asyncio
async def test_worker_runs_simc_update_before_connecting():
    mock_ws = AsyncMock()
    mock_ws.recv.side_effect = Exception("Stop")

    with patch("worker.run_manage_simc_update", new_callable=AsyncMock) as mock_update, \
         patch("worker.websockets.connect") as mock_connect, \
         patch("worker.aiohttp.ClientSession"), \
         patch("worker.asyncio.sleep", side_effect=Exception("Stop")):
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try:
            await run_worker()
        except Exception:
            pass

    assert mock_update.await_count == 1
    assert mock_connect.called


@pytest.mark.asyncio
async def test_download_input_file():
    mock_session = MagicMock()
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_content = MagicMock()
    async def mock_iter(n): yield b"test content"
    mock_content.iter_chunked.side_effect = mock_iter
    mock_response.content = mock_content
    mock_session.get.return_value.__aenter__.return_value = mock_response
    dest = "test_input.simc"
    try:
        success = await download_input_file(mock_session, "/inputs/test.simc", dest)
        assert success is True
        with open(dest) as f: assert f.read() == "test content"
    finally:
        if os.path.exists(dest): os.remove(dest)

@pytest.mark.asyncio
async def test_process_logs_direct():
    mock_ws = AsyncMock()
    # Mock recv to return a string, using asyncio.wait_for timeout
    mock_ws.recv.side_effect = asyncio.TimeoutError
    master_fd = 10
    mock_proc = MagicMock()
    mock_proc.poll.side_effect = [None, 0]
    mock_proc.pid = 123
    
    full_log = []
    last_send_ref = [0]
    
    with patch("worker.select.select", return_value=([master_fd], [], [])), \
         patch("worker.os.read", side_effect=[b"Log line\n", b""]):
        res = await process_logs(master_fd, mock_proc, mock_ws, "t1", full_log, last_send_ref, 1.0)
        assert res == "done"
        assert "Log line" in full_log[0]


# ===== TaskStatus tests =====

def test_task_status_creation():
    ts = TaskStatus("test-123", max_retries=3)
    assert ts.task_id == "test-123"
    assert ts.status == "pending"
    assert ts.retry_count == 0
    assert ts.max_retries == 3
    assert ts.exit_code is None
    assert ts.error is None

def test_task_status_to_dict():
    ts = TaskStatus("test-456", max_retries=2)
    ts.status = "running"
    ts.retry_count = 1
    ts.exit_code = 1
    ts.error = "test error"
    d = ts.to_dict()
    assert d["task_id"] == "test-456"
    assert d["status"] == "running"
    assert d["retry_count"] == 1
    assert d["max_retries"] == 2
    assert d["exit_code"] == 1
    assert d["error"] == "test error"
    assert "updated_at" in d

def test_get_or_create_task_status():
    task_status_store.clear()
    ts1 = get_or_create_task_status("t1", 3)
    ts2 = get_or_create_task_status("t1", 3)
    assert ts1 is ts2  # same object

def test_get_or_create_task_status_new():
    task_status_store.clear()
    ts1 = get_or_create_task_status("t1", 3)
    ts2 = get_or_create_task_status("t2", 5)
    assert ts1.task_id == "t1"
    assert ts2.task_id == "t2"


# ===== Retry backoff tests =====

def test_calculate_retry_backoff_exponential():
    assert _calculate_retry_backoff(0) == pytest.approx(2.0 ** 0, abs=0.01)
    assert _calculate_retry_backoff(1) == pytest.approx(2.0 ** 1, abs=0.01)
    assert _calculate_retry_backoff(2) == pytest.approx(2.0 ** 2, abs=0.01)

def test_calculate_retry_backoff_max_cap():
    # Default base=2.0, max=60.0. 2^7 = 128 > 60
    assert _calculate_retry_backoff(7) == 60.0


# ===== Worker retry loop tests (mock _execute_task) =====

@pytest.mark.asyncio
async def test_worker_start_command():
    mock_ws = AsyncMock()
    mock_ws.open = True
    mock_ws.recv.side_effect = [json.dumps({"type": "start", "task_id": "t1", "input_url": "/in"}), Exception("Break")]

    async def fake_execute(session, task_id, input_file, websocket):
        return 0, "report.html", None

    with patch("worker.websockets.connect") as mock_connect, \
         patch("worker.aiohttp.ClientSession"), \
         patch("worker.asyncio.sleep", side_effect=[None, Exception("Stop")]), \
         patch("worker.download_input_file", return_value=True), \
         patch("worker.os.makedirs"), \
         patch("worker._execute_task", side_effect=fake_execute) as mock_execute:
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try: await run_worker()
        except: pass
        assert mock_execute.called
        assert mock_execute.call_count >= 1

@pytest.mark.asyncio
async def test_worker_stop_command():
    mock_ws = AsyncMock()
    mock_ws.open = True
    # Simulate _execute_task returning "stopped" on first call
    stop_called = [False]
    call_count = [0]

    async def fake_execute(session, task_id, input_file, websocket):
        call_count[0] += 1
        return 1, None, "Task was stopped by user"

    mock_ws.recv.side_effect = [json.dumps({"type": "start", "task_id": "t1", "input_url": "/in"}), json.dumps({"type": "stop", "task_id": "t1"}), Exception("Break")]

    with patch("worker.websockets.connect") as mock_connect, \
         patch("worker.aiohttp.ClientSession"), \
         patch("worker.should_update_simc", return_value=False), \
         patch("worker.asyncio.sleep", side_effect=[None, None, Exception("Stop")]), \
         patch("worker.download_input_file", return_value=True), \
         patch("worker.os.makedirs"), \
         patch("worker._execute_task", side_effect=fake_execute) as mock_execute, \
         patch("worker.os.killpg") as mock_killpg, \
         patch("worker.os.getpgid", return_value=777):
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try: await run_worker()
        except: pass
        assert mock_execute.called

@pytest.mark.asyncio
async def test_process_logs_batching_logic():
    # Direct test of process_logs
    mock_ws = AsyncMock()
    master_fd = 10
    mock_proc = MagicMock()
    mock_proc.poll.side_effect = [None, None, 0]
    
    full_log = []
    last_send_ref = [0]
    
    # Mocking 60 lines of output (should trigger at least one batch of 50)
    lines = [b"Line\n"] * 60 + [b""]
    
    with patch("worker.select.select", return_value=([master_fd], [], [])), \
         patch("worker.os.read", side_effect=lines), \
         patch("worker.time.time", side_effect=[1000, 1000.01, 1000.2, 1000.3, 1000.4]):
        
        # We need to mock websocket.recv to avoid hanging
        mock_ws.recv.side_effect = asyncio.TimeoutError
        
        res = await process_logs(master_fd, mock_proc, mock_ws, "t1", full_log, last_send_ref, 1.0)
        assert res == "done"
        
        # Verify a log_batch was sent
        sent_types = [json.loads(c.args[0])["type"] for c in mock_ws.send.call_args_list]
        assert "log_batch" in sent_types

@pytest.mark.asyncio
async def test_worker_update_command_streaming():
    mock_ws = AsyncMock()
    mock_ws.open = True
    
    mock_ws.recv.side_effect = [
        json.dumps({"type": "update", "task_id": "u1"}),
        Exception("Break")
    ]
    
    with patch("worker.websockets.connect") as mock_connect, \
         patch("worker.aiohttp.ClientSession"), \
         patch("worker.should_update_simc", return_value=False), \
         patch("worker.asyncio.sleep", side_effect=[None, None, Exception("Stop")]), \
         patch("worker.run_manage_simc_update", new_callable=AsyncMock):
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try:
            await run_worker()
        except: pass

@pytest.mark.asyncio
async def test_worker_retry_on_failure():
    """Test that worker retries when _execute_task fails (exit != 0) up to MAX_RETRY_COUNT."""
    mock_ws = AsyncMock()
    mock_ws.open = True
    call_count = [0]

    async def fake_execute(session, task_id, input_file, websocket):
        call_count[0] += 1
        if call_count[0] < 3:
            return 1, None, "temporary failure"
        return 0, "report.html", None

    mock_ws.recv.side_effect = [json.dumps({"type": "start", "task_id": "t1", "input_url": "/in"}), Exception("Break")]

    with patch("worker.websockets.connect") as mock_connect, \
         patch("worker.aiohttp.ClientSession"), \
         patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
         patch("worker.download_input_file", return_value=True), \
         patch("worker.os.makedirs"), \
         patch("worker._execute_task", side_effect=fake_execute) as mock_execute:
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try: await run_worker()
        except: pass
        assert call_count[0] == 3  # 2 failures + 1 success
        assert mock_execute.call_count == 3

@pytest.mark.asyncio
async def test_worker_retry_exhausted():
    """Test that worker gives up after MAX_RETRY_COUNT failures."""
    mock_ws = AsyncMock()
    mock_ws.open = True

    async def fake_execute(session, task_id, input_file, websocket):
        return 1, None, "persistent failure"

    mock_ws.recv.side_effect = [json.dumps({"type": "start", "task_id": "t1", "input_url": "/in"}), Exception("Break")]

    with patch("worker.websockets.connect") as mock_connect, \
         patch("worker.aiohttp.ClientSession"), \
         patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
         patch("worker.download_input_file", return_value=True), \
         patch("worker.os.makedirs"), \
         patch("worker._execute_task", side_effect=fake_execute) as mock_execute, \
         patch.dict(os.environ, {"MAX_RETRY_COUNT": "2"}, clear=False):
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try: await run_worker()
        except: pass
        assert mock_execute.call_count == 3  # 1 initial + 2 retries (with MAX_RETRY_COUNT=2)


# ===== Upload/Download tests =====

@pytest.mark.asyncio
async def test_upload_file_direct():
    from worker import upload_file
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.json.return_value = {"status": "success"}
    mock_session.post.return_value.__aenter__.return_value = mock_resp
    
    # Create fake file
    with open("fake.zip", "w") as f: f.write("data")
    try:
        res = await upload_file(mock_session, "t1", "fake.zip")
        assert res["status"] == "success"
    finally:
        if os.path.exists("fake.zip"): os.remove("fake.zip")

@pytest.mark.asyncio
async def test_upload_file_error():
    from worker import upload_file
    mock_session = MagicMock()
    mock_session.post.side_effect = Exception("Upload error")
    with open("fake_error.zip", "w") as f: f.write("data")
    try:
        res = await upload_file(mock_session, "t1", "fake_error.zip")
        assert res is None
    finally:
        if os.path.exists("fake_error.zip"): os.remove("fake_error.zip")

@pytest.mark.asyncio
async def test_download_input_file_error():
    from worker import download_input_file
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 404
    mock_session.get.return_value.__aenter__.return_value = mock_resp
    success = await download_input_file(mock_session, "/inputs/not_found.simc", "dest.simc")
    assert success is False
    
    mock_session.get.side_effect = Exception("Download error")
    success = await download_input_file(mock_session, "/inputs/err.simc", "dest2.simc")
    assert success is False
