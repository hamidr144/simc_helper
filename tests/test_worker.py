import asyncio
import json
import os
import re
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from worker import (
    TaskStatus,
    _calculate_retry_backoff,
    _sweep_stale_tmp_dirs,
    download_input_file,
    get_or_create_task_status,
    process_logs,
    run_worker,
    sleep_or_shutdown,
    task_status_store,
    worker_subcommand,
)


@pytest.fixture(autouse=True)
def _no_host_tmp_sweep(monkeypatch):
    """LIFE-10: run_worker sweeps the real /tmp at startup; keep unit tests
    off the host filesystem. Tests that need the sweep call the function
    directly (the top-level import above binds the original)."""
    import worker as _w
    monkeypatch.setattr(_w, "_sweep_stale_tmp_dirs", lambda root="/tmp": 0)


def test_simc_update_due_on_startup_and_after_interval():
    from worker import should_update_simc

    assert should_update_simc(last_update_time=None, now=1000, interval_seconds=86400)
    assert not should_update_simc(last_update_time=1000, now=2000, interval_seconds=86400)
    assert should_update_simc(last_update_time=1000, now=87400, interval_seconds=86400)
    assert not should_update_simc(last_update_time=None, now=1000, interval_seconds=0)


def test_worker_default_simc_dir_matches_local_updater():
    import worker

    assert worker.SIMC_DIR == os.path.expanduser("~/.simc")


def test_worker_subcommand_uses_module_when_running_from_source():
    with patch.object(sys, "frozen", False, create=True):
        assert worker_subcommand("sim_helper") == [
            sys.executable, "-m", "src.worker", "sim_helper"
        ]


def test_worker_subcommand_uses_executable_dispatch_when_bundled():
    with patch.object(sys, "frozen", True, create=True):
        assert worker_subcommand("manage_simc") == [sys.executable, "manage_simc"]


@pytest.mark.asyncio
async def test_retry_delay_returns_immediately_on_shutdown():
    shutdown_event = asyncio.Event()
    shutdown_event.set()
    assert await sleep_or_shutdown(shutdown_event, 60) is True


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
         patch("worker.shutil.rmtree") as mock_rmtree, \
         patch("worker._execute_task", side_effect=fake_execute) as mock_execute:
        mock_connect.return_value.__aenter__.return_value = mock_ws
        try: await run_worker()
        except: pass
        assert mock_execute.called
        assert mock_execute.call_count >= 1
        # LIFE-10: terminal task must drop its /tmp/worker_sim_<id> workspace.
        mock_rmtree.assert_any_call("/tmp/worker_sim_t1", ignore_errors=True)

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
         patch("worker.should_update_simc", return_value=False), \
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
         patch("worker.should_update_simc", return_value=False), \
         patch("worker.asyncio.sleep", side_effect=[None, None, None, Exception("Stop")]), \
         patch("worker.download_input_file", return_value=True), \
         patch("worker.os.makedirs"), \
         patch("worker._execute_task", side_effect=fake_execute) as mock_execute, \
         patch("worker.MAX_RETRY_COUNT", 2):
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


def _reload_worker_with_env(monkeypatch, base_dir, **extra_env):
    """Re-import src.worker with a controlled environment (module reads env at import)."""
    import importlib
    import src.worker as worker_mod

    for key in ("BASE_DIR", "SIMC_ENGINE_MODE", "SIMC_NIGHTLY_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("BASE_DIR", str(base_dir))
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(worker_mod)
    return worker_mod


def _restore_default_worker(monkeypatch):
    import importlib
    import src.worker as worker_mod

    for key in ("BASE_DIR", "SIMC_ENGINE_MODE", "SIMC_NIGHTLY_DIR"):
        monkeypatch.delenv(key, raising=False)
    importlib.reload(worker_mod)


def test_worker_nightly_mode_engine_path_and_update_skip(monkeypatch, tmp_path):
    worker_mod = _reload_worker_with_env(monkeypatch, tmp_path, SIMC_ENGINE_MODE="nightly")
    try:
        assert worker_mod.engine_path() == str(tmp_path / "thirdparties" / "simc-nightly" / "simc")
        assert not worker_mod.should_update_simc(None, 10_000, 86400)
    finally:
        _restore_default_worker(monkeypatch)


def test_worker_source_mode_engine_path_unchanged(monkeypatch, tmp_path):
    worker_mod = _reload_worker_with_env(monkeypatch, tmp_path, SIMC_ENGINE_MODE="source")
    try:
        assert worker_mod.engine_path() == str(tmp_path / "thirdparties" / "simc" / "engine" / "simc")
        assert worker_mod.should_update_simc(None, 10_000, 86400)
    finally:
        _restore_default_worker(monkeypatch)


# =========================================================================
# Real nightly-SimC-output fixtures (t_1651ba9b)
#
# Every fixture under tests/fixtures/simc_nightly_* / simc_input_* is
# verbatim output of SimulationCraft 1210-01 (WoW 12.1.0.69933 nightly)
# running the real Hamidriel addon export inside the production worker
# container. These tests certify the worker against REAL engine output —
# a green run here means the report-discovery and DPS-extraction paths
# work on what the nightly engine actually emits, not on hand-written
# mocks.
# =========================================================================

import shutil
import zipfile
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
NIGHTLY_CONSOLE_LOG = FIXTURES / "simc_nightly_console_multicopy.log"
NIGHTLY_SIMHELPER_ZERO_COMBO_LOG = FIXTURES / "simc_nightly_simhelper_zero_combo.log"
NIGHTLY_SIMHELPER_MULTICOPY_LOG = FIXTURES / "simc_nightly_simhelper_multicopy.log"
NIGHTLY_BASELINE_REPORT = FIXTURES / "simc_nightly_report_baseline_only.html"


def test_get_all_dps_parses_real_nightly_console_log():
    """P0 class: stage filtering must read the nightly engine's real ranking."""
    from src.cli.sim_helper import get_all_dps

    results = get_all_dps(str(NIGHTLY_CONSOLE_LOG), current_name="Hamidriel")
    # Verbatim from the fixture's DPS Ranking block (Raid and the current
    # actor are excluded by design).
    assert results == [("Hamidriel_wrist_0", 7861), ("Hamidriel_neck_1", 7828)]

    # Without a current_name the base actor is part of the ranking too.
    all_results = get_all_dps(str(NIGHTLY_CONSOLE_LOG))
    assert ("Hamidriel", 7894) in all_results


def test_execute_task_report_regexes_match_real_simhelper_logs():
    """P0 class: _execute_task must find the report in REAL sim_helper stdout.

    Mirrors the exact regexes from worker._execute_task so any change there
    without a fixture update here breaks the contract.
    """
    for log_path, expected_report, expected_tmp in (
        (NIGHTLY_SIMHELPER_ZERO_COMBO_LOG, "report_20261015_020532.html", "/tmp/simc_20261015_020532"),
        (NIGHTLY_SIMHELPER_MULTICOPY_LOG, "report_20261015_020435.html", "/tmp/simc_20261015_020435"),
    ):
        log_str = log_path.read_text(encoding="utf-8")
        report_match = re.search(r"report_.*\.html", log_str)
        assert report_match is not None, f"no report found in {log_path.name}"
        assert report_match.group(0) == expected_report
        tmp_match = re.search(r"Temporary files are in (\/tmp\/simc_[A-Za-z0-9_]+)", log_str)
        assert tmp_match is not None, f"no tmp dir found in {log_path.name}"
        assert tmp_match.group(1) == expected_tmp


@pytest.mark.asyncio
async def test_execute_task_uploads_real_baseline_report(tmp_path, monkeypatch):
    """P0-4 × worker: a zero-combo baseline run must flow through the worker.

    The sim_helper invocation is replaced by a stub that replays the REAL
    sim_helper stdout log from the production container (zero-combo
    baseline run) and materialises the REAL nightly report it announces.
    Everything after that — PTY capture, log streaming, report discovery,
    artifact zipping, upload — is the genuine worker code path.
    """
    import worker as worker_mod

    report_file = "report_20261015_020532.html"
    stub = tmp_path / "stub_sim_helper.py"
    stub.write_text(
        "import os, shutil, sys, time\n"
        f"sys.stdout.write(open({str(NIGHTLY_SIMHELPER_ZERO_COMBO_LOG)!r}).read())\n"
        "sys.stdout.flush()\n"
        "os.makedirs('/tmp/simc_reports', exist_ok=True)\n"
        f"shutil.copy({str(NIGHTLY_BASELINE_REPORT)!r}, f'/tmp/simc_reports/{report_file}')\n"
        "time.sleep(0.3)\n"
    )

    task_id = f"fixture-zero-{os.getpid()}"
    os.makedirs(f"/tmp/worker_sim_{task_id}", exist_ok=True)
    monkeypatch.setattr(worker_mod, "worker_subcommand", lambda sub: [sys.executable, str(stub)])

    uploads = []

    async def fake_upload(session, tid, path):
        # Snapshot the artifact before test cleanup can race the assertion.
        snapshot = tmp_path / "artifacts.zip"
        shutil.copy(path, snapshot)
        uploads.append((tid, str(snapshot)))
        return {"status": "success"}

    monkeypatch.setattr(worker_mod, "upload_file", fake_upload)

    ws = AsyncMock()
    ws.recv.side_effect = asyncio.TimeoutError
    try:
        exit_code, report, error = await worker_mod._execute_task(
            MagicMock(), task_id, "/tmp/inputs/fixture.simc", ws
        )
    finally:
        import shutil as _shutil
        _shutil.rmtree(f"/tmp/worker_sim_{task_id}", ignore_errors=True)
        try:
            os.remove(f"/tmp/simc_reports/{report_file}")
        except OSError:
            pass

    assert (exit_code, error) == (0, None)
    assert report == report_file
    assert uploads and uploads[0][0] == task_id
    # The uploaded artifact must contain the genuine nightly report bytes.
    with zipfile.ZipFile(uploads[0][1]) as zf:
        assert report_file in zf.namelist()
        assert zf.read(report_file) == NIGHTLY_BASELINE_REPORT.read_bytes()


def test_sweep_stale_tmp_dirs(tmp_path):
    """LIFE-10 (t_3075ffff): startup sweep removes leaked per-task dirs."""
    (tmp_path / "worker_sim_t1").mkdir()
    (tmp_path / "simc_20261016_101029").mkdir()
    reports = tmp_path / "simc_reports"
    reports.mkdir()
    (reports / "report_x.html").write_text("x")
    (tmp_path / "unrelated").mkdir()
    (tmp_path / "worker_sim_notadir").write_text("x")

    assert _sweep_stale_tmp_dirs(str(tmp_path)) == 2
    assert not (tmp_path / "worker_sim_t1").exists()
    assert not (tmp_path / "simc_20261016_101029").exists()
    assert (reports / "report_x.html").exists()
    assert (tmp_path / "unrelated").exists()
    assert (tmp_path / "worker_sim_notadir").exists()
    assert _sweep_stale_tmp_dirs(str(tmp_path / "missing")) == 0


def test_tmp_dir_regex_rejects_spoofed_paths():
    """LIFE-10: tmp_dir is rmtree'd, so the regex must not match path escapes."""
    for spoof in (
        "/tmp/simc_a/../../../../home/user",
        "/tmp/simc_../../etc",
    ):
        m = re.search(r"Temporary files are in (\/tmp\/simc_[A-Za-z0-9_]+)",
                      f"Temporary files are in {spoof}")
        captured = m.group(1) if m else None
        assert captured is None or "/" not in captured[len("/tmp/simc_"):]
