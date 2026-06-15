"""Comprehensive test coverage for worker retry logic, task metadata, and task-status API.

Covers all 5 implementation points from the retry-logic task:
  1. Exponential backoff retry logic in src/worker.py
  2. Retry count tracking in task metadata
  3. Final failure reporting to master node
  4. /api/task-status REST endpoint in src/web/main.py
  5. Edge cases and configuration variations
"""

import json
import os
import sys
import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

import worker
from web.main import app
from worker import (
    TaskStatus,
    _calculate_retry_backoff,
    _push_task_status,
    get_or_create_task_status,
    run_worker,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_task_stores():
    """Clear task status stores before each test (setup only, not teardown)."""
    worker.task_status_store.clear()
    # Ensure web.main also sees the cleared store (it imports from worker)
    import web.main as main_mod
    main_mod.task_status_store.clear()
    yield
    # No teardown clear needed — the next test's setup clears again


# ---------------------------------------------------------------------------
# 1. Exponential backoff retry logic
# ---------------------------------------------------------------------------

class TestExponentialBackoff:
    """Tests for _calculate_retry_backoff and backoff configuration."""

    def test_base_case_zero_retries(self):
        """Attempt 0 → backoff = base^0 = 1.0."""
        assert _calculate_retry_backoff(0) == pytest.approx(1.0, abs=0.01)

    def test_base_case_one_retry(self):
        """Attempt 1 → backoff = base^1 = 2.0."""
        assert _calculate_retry_backoff(1) == pytest.approx(2.0, abs=0.01)

    def test_base_case_two_retries(self):
        """Attempt 2 → backoff = base^2 = 4.0."""
        assert _calculate_retry_backoff(2) == pytest.approx(4.0, abs=0.01)

    def test_exponential_growth(self):
        """Each attempt doubles the backoff (base=2)."""
        for attempt, expected in [(0, 1), (1, 2), (2, 4), (3, 8), (4, 16)]:
            assert _calculate_retry_backoff(attempt) == pytest.approx(expected, abs=0.01)

    def test_max_cap_enforced(self):
        """Backoff never exceeds RETRY_BACKOFF_MAX (default 60s)."""
        # 2^6 = 64 > 60 → should cap at 60
        assert _calculate_retry_backoff(6) == 60.0
        assert _calculate_retry_backoff(10) == 60.0
        assert _calculate_retry_backoff(100) == 60.0

    def test_backoff_respects_env_config(self):
        """RETRY_BACKOFF_BASE and RETRY_BACKOFF_MAX are configurable via env."""
        import importlib
        with patch.dict(os.environ, {"RETRY_BACKOFF_BASE": "3.0", "RETRY_BACKOFF_MAX": "100.0"}):
            importlib.reload(worker)
            assert worker._calculate_retry_backoff(1) == pytest.approx(3.0, abs=0.01)
        importlib.reload(worker)

    def test_backoff_env_max_cap(self):
        """Custom RETRY_BACKOFF_MAX caps the exponential growth."""
        import importlib
        with patch.dict(os.environ, {"RETRY_BACKOFF_BASE": "5.0", "RETRY_BACKOFF_MAX": "25.0"}):
            importlib.reload(worker)
            assert worker._calculate_retry_backoff(2) == pytest.approx(25.0, abs=0.01)
            assert worker._calculate_retry_backoff(3) == pytest.approx(25.0, abs=0.01)
        importlib.reload(worker)


# ---------------------------------------------------------------------------
# 2. Retry count tracking in task metadata
# ---------------------------------------------------------------------------

class TestTaskMetadata:
    """Tests for TaskStatus and metadata tracking."""

    def test_initial_state(self):
        """TaskStatus starts in 'pending' state with zero retry count."""
        ts = TaskStatus("task-1", max_retries=3)
        assert ts.status == "pending"
        assert ts.retry_count == 0
        assert ts.max_retries == 3
        assert ts.exit_code is None
        assert ts.error is None
        assert isinstance(ts.updated_at, float)

    def test_update_after_failure(self):
        """Status and metadata update correctly after a failed attempt."""
        ts = TaskStatus("task-2", max_retries=3)
        ts.status = "running"
        ts.retry_count = 1
        ts.exit_code = 1
        ts.error = "Connection timeout"
        ts.updated_at = time.time()

        d = ts.to_dict()
        assert d["status"] == "running"
        assert d["retry_count"] == 1
        assert d["exit_code"] == 1
        assert d["error"] == "Connection timeout"
        assert d["max_retries"] == 3

    def test_to_dict_has_all_fields(self):
        """to_dict() returns all expected fields."""
        ts = TaskStatus("task-3", max_retries=2)
        d = ts.to_dict()
        expected_keys = {"task_id", "status", "retry_count", "max_retries", "exit_code", "error", "updated_at"}
        assert set(d.keys()) == expected_keys

    def test_store_get_or_create_returns_same_object(self):
        """get_or_create_task_status returns the same object for the same task_id."""
        ts1 = get_or_create_task_status("same-task", 3)
        ts2 = get_or_create_task_status("same-task", 5)  # max_retries arg ignored after first
        assert ts1 is ts2
        assert ts1.task_id == "same-task"

    def test_store_multiple_tasks(self):
        """Store can hold multiple distinct tasks."""
        t1 = get_or_create_task_status("t1", 2)
        t2 = get_or_create_task_status("t2", 5)
        t3 = get_or_create_task_status("t1", 2)  # should return t1
        assert t1 is not t2
        assert t1 is t3
        assert len(worker.task_status_store) == 2

    def test_retry_count_increments_on_each_failure(self):
        """Simulate the worker's retry loop: retry_count should increment."""
        ts = TaskStatus("increment-task", max_retries=3)
        ts.status = "running"

        for attempt in range(1, 4):
            ts.status = "retrying"
            ts.retry_count = attempt
            ts.updated_at = time.time()

        assert ts.retry_count == 3
        assert ts.to_dict()["retry_count"] == 3


# ---------------------------------------------------------------------------
# 3. Final failure reporting to master
# ---------------------------------------------------------------------------

class TestFailureReporting:
    """Tests that failed tasks are properly reported to the master."""

    @pytest.mark.asyncio
    async def test_push_task_status_sends_json(self):
        """_push_task_status sends a JSON message to the websocket."""
        mock_ws = AsyncMock()
        ts = TaskStatus("report-task", max_retries=2)
        ts.status = "failed"
        ts.retry_count = 2
        ts.exit_code = 1
        ts.error = "simulated failure"

        await _push_task_status(mock_ws, "report-task", ts)

        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent["type"] == "task_status_update"
        assert sent["task_id"] == "report-task"
        assert sent["status"]["status"] == "failed"
        assert sent["status"]["retry_count"] == 2
        assert sent["status"]["error"] == "simulated failure"

    @pytest.mark.asyncio
    async def test_push_task_status_handles_send_failure(self):
        """_push_task_status silently ignores websocket send failures."""
        mock_ws = AsyncMock()
        mock_ws.send.side_effect = Exception("Connection lost")
        ts = TaskStatus("fail-task", max_retries=1)
        ts.status = "failed"

        await _push_task_status(mock_ws, "fail-task", ts)

    @pytest.mark.asyncio
    async def test_worker_reports_final_failure_after_retries_exhausted(self):
        """Worker sends final 'done' message with retry metadata after all retries exhausted."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        async def fake_execute(session, task_id, input_file, websocket):
            return 1, None, "persistent error"

        mock_ws.recv.side_effect = [
            json.dumps({"type": "start", "task_id": "t-final", "input_url": "/in"}),
            Exception("Break"),
        ]

        with patch("worker.websockets.connect") as mock_connect, \
             patch("worker.aiohttp.ClientSession"), \
             patch("worker.should_update_simc", return_value=False), \
             patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
             patch("worker.download_input_file", return_value=True), \
             patch("worker.os.makedirs"), \
             patch("worker._execute_task", side_effect=fake_execute) as mock_execute, \
             patch("worker.MAX_RETRY_COUNT", 2):
            mock_connect.return_value.__aenter__.return_value = mock_ws
            try:
                await run_worker()
            except:
                pass

        assert mock_execute.call_count == 3  # 1 initial + 2 retries
        done_calls = [
            c for c in mock_ws.send.call_args_list
            if json.loads(c.args[0]).get("type") == "done"
        ]
        assert len(done_calls) == 1
        final_msg = json.loads(done_calls[-1].args[0])
        assert final_msg["task_id"] == "t-final"
        assert final_msg["code"] == 1
        assert final_msg["error"] == "persistent error"
        assert final_msg["retry_count"] == 3
        assert final_msg["max_retries"] == 2

    @pytest.mark.asyncio
    async def test_worker_reports_success_with_retry_count(self):
        """Worker sends 'done' with retry_count > 0 when task succeeds after failures."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        call_count = [0]

        async def fake_execute(session, task_id, input_file, websocket):
            call_count[0] += 1
            if call_count[0] < 2:
                return 1, None, "transient error"
            return 0, "report.html", None

        mock_ws.recv.side_effect = [
            json.dumps({"type": "start", "task_id": "t-succeeds", "input_url": "/in"}),
            Exception("Break"),
        ]

        with patch("worker.websockets.connect") as mock_connect, \
             patch("worker.aiohttp.ClientSession"), \
             patch("worker.should_update_simc", return_value=False), \
             patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
             patch("worker.download_input_file", return_value=True), \
             patch("worker.os.makedirs"), \
             patch("worker._execute_task", side_effect=fake_execute) as mock_execute, \
             patch("worker.MAX_RETRY_COUNT", 3):
            mock_connect.return_value.__aenter__.return_value = mock_ws
            try:
                await run_worker()
            except:
                pass

        assert mock_execute.call_count == 2  # 1 failure + 1 success
        done_calls = [
            c for c in mock_ws.send.call_args_list
            if json.loads(c.args[0]).get("type") == "done"
        ]
        assert len(done_calls) == 1
        final_msg = json.loads(done_calls[-1].args[0])
        assert final_msg["code"] == 0
        assert final_msg["retry_count"] == 1


# ---------------------------------------------------------------------------
# 4. /api/task-status REST endpoint
# ---------------------------------------------------------------------------

class TestTaskStatusEndpoint:
    """Tests for the GET /api/task-status endpoint."""

    def _make_client(self):
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.asyncio
    async def test_task_status_returns_not_found(self):
        """Requesting a non-existent task returns status='not_found'."""
        async with self._make_client() as client:
            resp = await client.get("/api/task-status", params={"task_id": "nonexistent"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "not_found"
            assert data["task_id"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_task_status_returns_single_task(self):
        """Requesting an existing task returns its status dict."""
        # Populate the store that main.py reads from
        import web.main as main_mod
        ts = TaskStatus("api-task-1", max_retries=3)
        ts.status = "running"
        ts.retry_count = 1
        ts.exit_code = 1
        ts.error = "test error"
        main_mod.task_status_store["api-task-1"] = ts

        async with self._make_client() as client:
            resp = await client.get("/api/task-status", params={"task_id": "api-task-1"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["task_id"] == "api-task-1"
            assert data["task"]["task_id"] == "api-task-1"
            assert data["task"]["status"] == "running"
            assert data["task"]["retry_count"] == 1
            assert data["task"]["max_retries"] == 3
            assert data["task"]["error"] == "test error"

    @pytest.mark.asyncio
    async def test_task_status_list_all(self):
        """Omitting task_id returns all tasks."""
        import web.main as main_mod
        main_mod.task_status_store["list-1"] = TaskStatus("list-1", max_retries=2)
        main_mod.task_status_store["list-2"] = TaskStatus("list-2", max_retries=5)

        async with self._make_client() as client:
            resp = await client.get("/api/task-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "tasks" in data
            assert data["total"] == 2
            assert "list-1" in data["tasks"]
            assert "list-2" in data["tasks"]

    @pytest.mark.asyncio
    async def test_task_status_list_empty(self):
        """No tasks → empty dict with total=0."""
        async with self._make_client() as client:
            resp = await client.get("/api/task-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["tasks"] == {}
            assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_task_status_no_params_lists_all(self):
        """GET /api/task-status with no query params lists all tasks."""
        import web.main as main_mod
        main_mod.task_status_store["no-param-1"] = TaskStatus("no-param-1", max_retries=1)

        async with self._make_client() as client:
            resp = await client.get("/api/task-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 1


# ---------------------------------------------------------------------------
# 5. Worker retry loop integration tests
# ---------------------------------------------------------------------------

class TestWorkerRetryLoop:
    """Integration-level tests for the retry loop in run_worker()."""

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_success(self):
        """Worker retries on failure, eventually succeeds."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        attempts = [0]

        async def fake_execute(session, task_id, input_file, websocket):
            attempts[0] += 1
            if attempts[0] < 3:
                return 1, None, f"failure attempt {attempts[0]}"
            return 0, "report.html", None

        async def fake_simc_update(*args, **kwargs):
            return 0

        mock_ws.recv.side_effect = [
            json.dumps({"type": "start", "task_id": "t-retry-ok", "input_url": "/in"}),
            Exception("Break"),
        ]

        with patch("worker.websockets.connect") as mock_connect, \
             patch("worker.aiohttp.ClientSession"), \
             patch("worker.should_update_simc", return_value=False), \
             patch("worker.run_manage_simc_update", side_effect=fake_simc_update), \
             patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
             patch("worker.download_input_file", return_value=True), \
             patch("worker.os.makedirs"), \
             patch("worker._execute_task", side_effect=fake_execute), \
             patch("worker.MAX_RETRY_COUNT", 5):
            mock_connect.return_value.__aenter__.return_value = mock_ws
            try:
                await run_worker()
            except:
                pass

        assert attempts[0] == 3  # 2 failures + 1 success
        assert worker.task_status_store["t-retry-ok"].retry_count == 2
        assert worker.task_status_store["t-retry-ok"].status == "done"

    @pytest.mark.asyncio
    async def test_retry_exhausted_gives_up(self):
        """Worker stops retrying after MAX_RETRY_COUNT is exceeded."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        async def fake_execute(session, task_id, input_file, websocket):
            return 1, None, "permanent failure"

        async def fake_simc_update(*args, **kwargs):
            return 0

        mock_ws.recv.side_effect = [
            json.dumps({"type": "start", "task_id": "t-exhaust", "input_url": "/in"}),
            Exception("Break"),
        ]

        with patch("worker.websockets.connect") as mock_connect, \
             patch("worker.aiohttp.ClientSession"), \
             patch("worker.should_update_simc", return_value=False), \
             patch("worker.run_manage_simc_update", side_effect=fake_simc_update), \
             patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
             patch("worker.download_input_file", return_value=True), \
             patch("worker.os.makedirs"), \
             patch("worker._execute_task", side_effect=fake_execute) as mock_execute, \
             patch("worker.MAX_RETRY_COUNT", 2):
            mock_connect.return_value.__aenter__.return_value = mock_ws
            try:
                await run_worker()
            except:
                pass

        assert mock_execute.call_count == 3  # 1 initial + 2 retries
        assert worker.task_status_store["t-exhaust"].status == "failed"
        assert worker.task_status_store["t-exhaust"].retry_count == 3

    @pytest.mark.asyncio
    async def test_unlimited_retries(self):
        """MAX_RETRY_COUNT=0 means unlimited retries."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        attempts = [0]

        async def fake_execute(session, task_id, input_file, websocket):
            attempts[0] += 1
            if attempts[0] < 4:
                return 1, None, "temporary issue"
            return 0, "report.html", None

        async def fake_simc_update(*args, **kwargs):
            return 0

        mock_ws.recv.side_effect = [
            json.dumps({"type": "start", "task_id": "t-unlimited", "input_url": "/in"}),
            Exception("Break"),
        ]

        with patch("worker.websockets.connect") as mock_connect, \
             patch("worker.aiohttp.ClientSession"), \
             patch("worker.should_update_simc", return_value=False), \
             patch("worker.run_manage_simc_update", side_effect=fake_simc_update), \
             patch("worker.asyncio.sleep", side_effect=[None] * 10 + [Exception("Stop")]), \
             patch("worker.download_input_file", return_value=True), \
             patch("worker.os.makedirs"), \
             patch("worker._execute_task", side_effect=fake_execute), \
             patch("worker.MAX_RETRY_COUNT", 0), \
             patch("worker.DEFAULT_MAX_RETRY_COUNT", 0):
            mock_connect.return_value.__aenter__.return_value = mock_ws
            try:
                await run_worker()
            except:
                pass

        assert attempts[0] == 4  # 3 failures + 1 success

    def test_backoff_values_correct(self):
        """Verify _calculate_retry_backoff returns correct exponential values."""
        import src.worker as worker_mod
        original_base = worker_mod.RETRY_BACKOFF_BASE
        original_max = worker_mod.RETRY_BACKOFF_MAX

        try:
            worker_mod.RETRY_BACKOFF_BASE = 2.0
            worker_mod.RETRY_BACKOFF_MAX = 60.0

            assert worker_mod._calculate_retry_backoff(1) == pytest.approx(2.0)
            assert worker_mod._calculate_retry_backoff(2) == pytest.approx(4.0)
            assert worker_mod._calculate_retry_backoff(3) == pytest.approx(8.0)
            assert worker_mod._calculate_retry_backoff(4) == pytest.approx(16.0)
            assert worker_mod._calculate_retry_backoff(5) == pytest.approx(32.0)
            assert worker_mod._calculate_retry_backoff(6) == pytest.approx(60.0)
            assert worker_mod._calculate_retry_backoff(10) == pytest.approx(60.0)
        finally:
            worker_mod.RETRY_BACKOFF_BASE = original_base
            worker_mod.RETRY_BACKOFF_MAX = original_max

    @pytest.mark.asyncio
    async def test_download_failure_not_retried(self):
        """If downloading the input file fails, the task reports immediately without retry."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        async def fake_execute(session, task_id, input_file, websocket):
            return 0, None, None

        async def fake_simc_update(*args, **kwargs):
            return 0

        mock_ws.recv.side_effect = [
            json.dumps({"type": "start", "task_id": "t-no-download", "input_url": "/in"}),
            Exception("Break"),
        ]

        with patch("worker.websockets.connect") as mock_connect, \
             patch("worker.aiohttp.ClientSession"), \
             patch("worker.should_update_simc", return_value=False), \
             patch("worker.run_manage_simc_update", side_effect=fake_simc_update), \
             patch("worker.asyncio.sleep", side_effect=[None, Exception("Stop")]), \
             patch("worker.download_input_file", return_value=False), \
             patch("worker.os.makedirs"), \
             patch("worker._execute_task", side_effect=fake_execute) as mock_execute:
            mock_connect.return_value.__aenter__.return_value = mock_ws
            try:
                await run_worker()
            except:
                pass

        assert not mock_execute.called

        done_calls = [
            c for c in mock_ws.send.call_args_list
            if json.loads(c.args[0]).get("type") == "done"
        ]
        assert len(done_calls) == 1
        final_msg = json.loads(done_calls[-1].args[0])
        assert final_msg["code"] == 1
        assert final_msg["retry_count"] == 0


# ---------------------------------------------------------------------------
# 6. Edge cases and configuration
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_task_status_zero_retries_config(self):
        """TaskStatus with max_retries=0 stores it correctly."""
        ts = TaskStatus("zero-retry", max_retries=0)
        assert ts.max_retries == 0
        d = ts.to_dict()
        assert d["max_retries"] == 0

    def test_task_status_none_exit_code(self):
        """TaskStatus starts with exit_code=None."""
        ts = TaskStatus("no-exit", max_retries=1)
        assert ts.exit_code is None

    def test_task_status_none_error(self):
        """TaskStatus starts with error=None."""
        ts = TaskStatus("no-error", max_retries=1)
        assert ts.error is None

    def test_task_status_updated_at_is_float(self):
        """TaskStatus.updated_at is a Unix timestamp (float)."""
        ts = TaskStatus("timestamp", max_retries=1)
        assert isinstance(ts.updated_at, float)
        assert ts.updated_at > 0

    def test_backoff_at_boundary(self):
        """Backoff exactly at the cap value."""
        # 2^5 = 32, 2^6 = 64 (capped at 60)
        assert _calculate_retry_backoff(5) == pytest.approx(32.0, abs=0.01)
        assert _calculate_retry_backoff(6) == 60.0

    def test_backoff_large_attempt_stays_capped(self):
        """Even with a very large attempt number, backoff stays capped."""
        assert _calculate_retry_backoff(50) == 60.0
        assert _calculate_retry_backoff(100) == 60.0

    @pytest.mark.asyncio
    async def test_task_status_update_preserves_task_id(self):
        """Updating TaskStatus fields doesn't change the task_id."""
        ts = TaskStatus("id-preserved", max_retries=3)
        ts.status = "done"
        ts.retry_count = 5
        ts.exit_code = 0
        ts.error = None

        assert ts.task_id == "id-preserved"
        d = ts.to_dict()
        assert d["task_id"] == "id-preserved"
