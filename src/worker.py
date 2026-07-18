import asyncio
import json
import os
import pty
import re
import select
import signal
import ssl
import subprocess  # nosec B404
import sys
import time
from pathlib import Path
from typing import Any, Dict

import aiohttp
import websockets

CONFIGURED_BASE_DIR = os.environ.get("BASE_DIR")
BASE_DIR = CONFIGURED_BASE_DIR or "."
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data", "worker")
SIMC_DIR = (
    os.path.join(CONFIGURED_BASE_DIR, "thirdparties", "simc")
    if CONFIGURED_BASE_DIR
    else os.path.expanduser("~/.simc")
)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
from src.core.logging import setup_logging  # noqa: E402

logger = setup_logging("worker")
from src.core.env import clean_pyinstaller_env
from src.core.env import load_cluster_secret as _load_cluster_secret


def get_clean_env():
    env = clean_pyinstaller_env()
    if "PATH" in env and sys.prefix in env["PATH"]:
        paths = env["PATH"].split(os.pathsep)
        env["PATH"] = os.pathsep.join([p for p in paths if sys.prefix not in p])
    return env

def load_cluster_secret(role: str) -> str:
    return _load_cluster_secret(role, logger)

MASTER_URL = os.environ.get("MASTER_URL", "http://localhost:8000")
WS_URL = MASTER_URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/worker"
WORKER_NAME = os.environ.get("WORKER_NAME", "LocalWorker")
CLUSTER_SECRET = load_cluster_secret("worker")
DEFAULT_SIMC_UPDATE_INTERVAL_SECONDS = 24 * 60 * 60
SIMC_UPDATE_INTERVAL_SECONDS = int(os.environ.get("SIMC_UPDATE_INTERVAL_SECONDS", DEFAULT_SIMC_UPDATE_INTERVAL_SECONDS))

# Retry settings
DEFAULT_MAX_RETRY_COUNT = 3
MAX_RETRY_COUNT = int(os.environ.get("MAX_RETRY_COUNT", str(DEFAULT_MAX_RETRY_COUNT)))
DEFAULT_RETRY_BACKOFF_BASE = 2.0  # base for exponential backoff
RETRY_BACKOFF_BASE = float(os.environ.get("RETRY_BACKOFF_BASE", str(DEFAULT_RETRY_BACKOFF_BASE)))
DEFAULT_RETRY_BACKOFF_MAX = 60.0  # max backoff in seconds
RETRY_BACKOFF_MAX = float(os.environ.get("RETRY_BACKOFF_MAX", str(DEFAULT_RETRY_BACKOFF_MAX)))

# Task status tracking (in-memory, shared with main.py via sync)
# (defined after TaskStatus class)


class TaskStatus:
    """Represents the current state of a simulation task with retry tracking."""
    def __init__(self, task_id: str, max_retries: int = 0):
        self.task_id = task_id
        self.status = "pending"  # pending, running, retrying, done, failed
        self.retry_count = 0
        self.max_retries = max_retries
        self.exit_code = None
        self.error = None
        self.updated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "exit_code": self.exit_code,
            "error": self.error,
            "updated_at": self.updated_at,
        }


def get_or_create_task_status(task_id: str, max_retries: int = 0) -> TaskStatus:
    """Get existing TaskStatus or create a new one."""
    if task_id not in task_status_store:
        task_status_store[task_id] = TaskStatus(task_id, max_retries)
    return task_status_store[task_id]


# Module-level store — must be defined after TaskStatus class
task_status_store: Dict[str, TaskStatus] = {}

def _calculate_retry_backoff(retry_count: int) -> float:
    """Calculate exponential backoff with max cap."""
    backoff = RETRY_BACKOFF_BASE ** retry_count
    return min(backoff, RETRY_BACKOFF_MAX)

ssl_context = None
if WS_URL.startswith("wss://"):
    if os.environ.get("SIMC_HELPER_INSECURE_TLS") == "1":
        logger.warning("SIMC_HELPER_INSECURE_TLS=1 disables worker TLS certificate verification.")
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    else:
        ssl_context = ssl.create_default_context()

async def upload_file(session, task_id, file_path):
    if not file_path or not os.path.exists(file_path):
        return None
    file_name = os.path.basename(file_path)
    url = f"{MASTER_URL}/api/worker/upload-file?task_id={task_id}&file_name={file_name}&secret={CLUSTER_SECRET}"
    try:
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field('file', f, filename=file_name)
            async with session.post(url, data=data) as resp:
                return await resp.json()
    except Exception as e:
        logger.info(f"Failed to upload {file_name}: {e}")
        return None

async def download_input_file(session, url_path, dest_path):
    url = f"{MASTER_URL}{url_path}"
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(dest_path, 'wb') as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                return True
            else:
                logger.info(f"Failed to download input file: HTTP {resp.status}")
                return False
    except Exception as e:
        logger.info(f"Error downloading input file: {e}")
        return False

def should_update_simc(last_update_time, now, interval_seconds=SIMC_UPDATE_INTERVAL_SECONDS):
    if interval_seconds <= 0:
        return False
    return last_update_time is None or now - last_update_time >= interval_seconds


def worker_subcommand(subcommand: str) -> list[str]:
    """Build a worker helper command for source and bundled executions."""
    # On some macOS hosts a bundled worker is killed when it spawns itself as
    # a PyInstaller child. Prefer the deployed source helper when available.
    if (
        getattr(sys, "frozen", False)
        and os.environ.get("SIMC_HELPER_USE_SOURCE_HELPERS") == "1"
        and Path("src/worker.py").is_file()
    ):
        return ["python3", "-m", "src.worker", subcommand]
    if getattr(sys, "frozen", False):
        return [sys.executable, subcommand]
    return [sys.executable, "-m", "src.worker", subcommand]


async def sleep_or_shutdown(shutdown_event: asyncio.Event, delay: float) -> bool:
    """Wait for a retry delay, returning early when shutdown is requested."""
    sleep_task = asyncio.create_task(asyncio.sleep(delay))
    shutdown_task = asyncio.create_task(shutdown_event.wait())
    done, pending = await asyncio.wait(
        {sleep_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if sleep_task in done:
        await sleep_task
    return shutdown_event.is_set()


async def run_manage_simc_update(websocket=None, task_id=None):
    """Run manage_simc and optionally stream its output to the master."""
    logger.info("Updating SimulationCraft engine...")
    cmd = worker_subcommand("manage_simc")
    master_fd_upd, slave_fd_upd = pty.openpty()
    proc = subprocess.Popen(cmd, stdout=slave_fd_upd, stderr=slave_fd_upd, close_fds=True, start_new_session=True, env=get_clean_env())  # nosec B603
    os.close(slave_fd_upd)
    try:
        while True:
            r, _, _ = select.select([master_fd_upd], [], [], 0.1)
            if r:
                try:
                    raw = os.read(master_fd_upd, 4096)
                    if not raw:
                        break
                    text = raw.decode('utf-8', errors='replace').replace('\r\n', '\n')
                    for line in text.split('\n'):
                        if not line:
                            continue
                        logger.info(line)
                        if websocket is not None and task_id is not None:
                            await websocket.send(json.dumps({"type": "log", "task_id": task_id, "text": line}))
                except OSError:
                    break
            if proc.poll() is not None:
                r, _, _ = select.select([master_fd_upd], [], [], 0.1)
                if not r:
                    break
            await asyncio.sleep(0.01)
        exit_code = proc.wait()
        logger.info("SimulationCraft update finished with code %s", exit_code)
        if websocket is not None and task_id is not None:
            await websocket.send(json.dumps({"type": "done", "task_id": task_id, "code": exit_code}))
        return exit_code
    except Exception as e:
        logger.info(f"Update error: {e}")
        if websocket is not None and task_id is not None:
            try:
                await websocket.send(json.dumps({"type": "done", "task_id": task_id, "code": 1}))
            except Exception as send_exc:
                logger.debug(f"Failed to send update failure: {send_exc}")
        return 1
    finally:
        try:
            os.close(master_fd_upd)
        except OSError as close_exc:
            logger.debug(f"Failed to close update fd: {close_exc}")


async def process_logs(master_fd, active_process, websocket, task_id, full_log, last_send_time_ref, progress_throttle):
    log_batch = []
    last_batch_send = time.time()

    while active_process and active_process.poll() is None:
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=0.01)
            data = json.loads(message)
            if data["type"] == "stop" and data.get("task_id") == task_id:
                logger.info(f"[{task_id}] Received STOP command.")
                import signal
                try:
                    os.killpg(os.getpgid(active_process.pid), signal.SIGTERM)
                except Exception as exc:
                    logger.debug(f"Failed to stop process group: {exc}")
                return "stopped"
        except asyncio.TimeoutError:
            pass
        except websockets.ConnectionClosed:
            return "reconnect"

        r, _, _ = select.select([master_fd], [], [], 0)
        if r:
            try:
                raw_data = os.read(master_fd, 4096)
                if not raw_data: break
                text = raw_data.decode('utf-8', errors='replace').replace('\r\n', '\n')
                for line in text.split('\n'):
                    if line:
                        full_log.append(line)
                        is_progress = "Progress:" in line
                        curr_time = time.time()
                        if not is_progress or (curr_time - last_send_time_ref[0] >= progress_throttle):
                            log_batch.append(line)
                            if is_progress: last_send_time_ref[0] = curr_time
            except OSError: break

        curr_time = time.time()
        if log_batch and (len(log_batch) >= 50 or (curr_time - last_batch_send >= 0.1)):
            try:
                await websocket.send(json.dumps({"type": "log_batch", "task_id": task_id, "lines": log_batch}))
                log_batch = []
                last_batch_send = curr_time
            except Exception:
                return "reconnect"

        await asyncio.sleep(0.01)

    if log_batch:
        try:
            await websocket.send(json.dumps({"type": "log_batch", "task_id": task_id, "lines": log_batch}))
        except Exception as exc:
            logger.debug(f"Failed to send final log batch: {exc}")
    return "done"


async def _push_task_status(websocket, task_id: str, status: TaskStatus):
    """Push a task status update to the master for /api/task-status tracking."""
    try:
        await websocket.send(json.dumps({
            "type": "task_status_update",
            "task_id": task_id,
            "status": status.to_dict(),
        }))
    except Exception:
        pass


async def _execute_task(session, task_id: str, input_file: str, websocket) -> tuple:
    """Execute a single task attempt. Returns (exit_code, report_file, error)."""
    simc_engine = os.path.join(SIMC_DIR, "engine", "simc")
    cmd = worker_subcommand("sim_helper") + [
        f"simc_path={simc_engine}",
        f"input_file={input_file}",
        "start_server=0",
    ]
    logger.info(f"[{task_id}] Executing: {' '.join(cmd)}")

    try:
        master_fd, slave_fd = pty.openpty()
        active_process = subprocess.Popen(cmd, stdout=slave_fd, stderr=slave_fd, close_fds=True, start_new_session=True, env=get_clean_env())  # nosec B603
        os.close(slave_fd)
    except Exception as e:
        error_msg = f"Failed to spawn simulation process: {str(e)}"
        logger.error(f"[{task_id}] {error_msg}")
        return 1, None, error_msg

    try:
        if not hasattr(active_process, 'full_log_buffer'): active_process.full_log_buffer = []
        if not hasattr(active_process, 'last_send_time_ref'): active_process.last_send_time_ref = [0]

        res = await process_logs(master_fd, active_process, websocket, task_id, active_process.full_log_buffer, active_process.last_send_time_ref, 1.0)
        if res == "reconnect":
            return 1, None, "Worker connection lost during execution"
        if res == "stopped":
            return 1, None, "Task was stopped by user"

        exit_code = active_process.wait()
        logger.info(f"[{task_id}] Process finished with code {exit_code}")
        log_str = "\n".join(active_process.full_log_buffer)
        report_match = re.search(r"report_.*\.html", log_str)
        report_file = report_match.group(0) if report_match else None
        tmp_match = re.search(r"Temporary files are in (\/tmp\/simc_[^\s\n]+)", log_str)
        tmp_dir = tmp_match.group(1) if tmp_match else None

        if tmp_dir or report_file:
            import zipfile
            zip_path = f"/tmp/worker_sim_{task_id}/artifacts.zip"  # nosec B108
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                if tmp_dir and os.path.exists(os.path.join(tmp_dir, "stage3.simc")): zf.write(os.path.join(tmp_dir, "stage3.simc"), "stage3.simc")
                if report_file:
                    report_path = os.path.join("/tmp/simc_reports", report_file)  # nosec B108
                    if os.path.exists(report_path):
                        zf.write(report_path, report_file)
            await upload_file(session, task_id, zip_path)

        return exit_code, report_file, None
    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass

async def run_worker():
    logger.info(f"Starting Worker: {WORKER_NAME}")
    logger.info(f"Master URL: {MASTER_URL}")

    active_process = None
    active_task_id = None
    last_simc_update_time = None

    # Graceful shutdown flag
    _shutdown_event = asyncio.Event()

    def _handle_signal(signum, frame):
        logger.info(f"Worker received signal {signum}, initiating graceful shutdown...")
        _shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig, None)
        except NotImplementedError:
            pass

    # Helper: execute task with reconnect awareness
    async def _execute_task_with_reconnect(session, task_id: str, input_file: str, websocket):
        """Execute a task, returning 'reconnect' if the WebSocket closes mid-execution."""
        try:
            exit_code, report_file, error = await _execute_task(session, task_id, input_file, websocket)
            return ("success", exit_code, report_file, error)
        except websockets.ConnectionClosed:
            return ("reconnect", 1, None, "WebSocket closed during execution")
        except Exception as e:
            return ("error", 1, None, str(e))

    while True:
        # Check shutdown flag
        if _shutdown_event.is_set():
            logger.info("Shutdown signal received — finishing current task if any...")
            break

        try:
            now = time.time()
            if should_update_simc(last_simc_update_time, now, SIMC_UPDATE_INTERVAL_SECONDS):
                await run_manage_simc_update()
                last_simc_update_time = time.time()

            connector = aiohttp.TCPConnector(ssl=ssl_context) if ssl_context else None
            async with aiohttp.ClientSession(connector=connector) as session:
                try:
                    async with websockets.connect(
                        f"{WS_URL}?name={WORKER_NAME}&secret={CLUSTER_SECRET}",
                        max_size=67108864,
                        ping_interval=None,
                        ping_timeout=None,
                        compression="deflate",
                        ssl=ssl_context,
                    ) as websocket:
                        logger.info(f"Connected to Master at {WS_URL}")

                        if active_task_id:
                            logger.info(f"[{active_task_id}] Resuming active task after reconnect...")
                            await websocket.send(json.dumps({"type": "resume", "task_id": active_task_id}))

                        last_ping_time = time.time()

                        try:
                            while True:
                                # Check shutdown flag
                                if _shutdown_event.is_set():
                                    logger.info("Shutdown requested during message loop — exiting.")
                                    break

                                curr_time = time.time()
                                if curr_time - last_ping_time > 20:
                                    try:
                                        await websocket.send(json.dumps({"type": "ping"}))
                                    except Exception:
                                        break
                                    last_ping_time = curr_time

                                if not active_process:
                                    now = time.time()
                                    if should_update_simc(last_simc_update_time, now, SIMC_UPDATE_INTERVAL_SECONDS):
                                        await run_manage_simc_update()
                                        last_simc_update_time = time.time()
                                        continue

                                    try:
                                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                                        data = json.loads(message)

                                        if data["type"] == "start":
                                            task_id = data["task_id"]
                                            active_task_id = task_id
                                            input_url = data.get("input_url")
                                            logger.info(f"\n[{task_id}] Received start command. Downloading input from {input_url}...")

                                            workspace = f"/tmp/worker_sim_{task_id}"  # nosec B108
                                            os.makedirs(workspace, exist_ok=True)
                                            input_file = os.path.join(workspace, "input.simc")

                                            if input_url:
                                                success = await download_input_file(session, input_url, input_file)
                                                if not success:
                                                    task_status = get_or_create_task_status(task_id, MAX_RETRY_COUNT)
                                                    task_status.status = "failed"
                                                    task_status.exit_code = 1
                                                    task_status.error = "Failed to download input file"
                                                    task_status.updated_at = time.time()
                                                    await _push_task_status(websocket, task_id, task_status)
                                                    await websocket.send(json.dumps({
                                                        "type": "done",
                                                        "task_id": task_id,
                                                        "code": 1,
                                                        "error": "Failed to download input file",
                                                        "retry_count": 0,
                                                        "max_retries": MAX_RETRY_COUNT,
                                                    }))
                                                    active_task_id = None
                                                    continue
                                            else:
                                                input_content = data.get("input_content", "")
                                                with open(input_file, "w") as f: f.write(input_content)

                                            # Initialize task status for retry tracking
                                            task_status = get_or_create_task_status(task_id, MAX_RETRY_COUNT)
                                            task_status.status = "running"
                                            task_status.retry_count = 0
                                            task_status.updated_at = time.time()
                                            await _push_task_status(websocket, task_id, task_status)

                                            # Retry loop for task execution
                                            final_exit_code = 1
                                            final_report_file = None
                                            final_error = None
                                            attempt = 0

                                            while True:
                                                if _shutdown_event.is_set():
                                                    final_error = "Worker shutdown requested"
                                                    task_status.status = "failed"
                                                    task_status.exit_code = final_exit_code
                                                    task_status.error = final_error
                                                    task_status.updated_at = time.time()
                                                    await _push_task_status(websocket, task_id, task_status)
                                                    break
                                                attempt += 1
                                                logger.info(f"[{task_id}] Execution attempt {attempt}")

                                                result = await _execute_task_with_reconnect(session, task_id, input_file, websocket)
                                                status, exit_code, report_file, error = result

                                                if status == "reconnect":
                                                    # Connection lost — exit inner retry loop to reconnect
                                                    logger.info(f"[{task_id}] Connection lost — reconnecting to master.")
                                                    active_task_id = None
                                                    final_exit_code = 1
                                                    final_error = "Connection lost"
                                                    break

                                                if exit_code == 0:
                                                    task_status.status = "done"
                                                    task_status.exit_code = exit_code
                                                    task_status.updated_at = time.time()
                                                    final_exit_code = exit_code
                                                    final_report_file = report_file
                                                    logger.info(f"[{task_id}] Task succeeded on attempt {attempt}")
                                                    break

                                                # Failed — check if we should retry
                                                if MAX_RETRY_COUNT <= 0 or attempt <= MAX_RETRY_COUNT:
                                                    remaining = MAX_RETRY_COUNT - attempt if MAX_RETRY_COUNT > 0 else "unlimited"
                                                    backoff = _calculate_retry_backoff(attempt)
                                                    logger.info(f"[{task_id}] Attempt {attempt} failed (exit {exit_code}), retrying in {backoff:.1f}s (max retries: {remaining})")
                                                    task_status.status = "retrying"
                                                    task_status.retry_count = attempt
                                                    task_status.exit_code = exit_code
                                                    task_status.error = error
                                                    task_status.updated_at = time.time()
                                                    await _push_task_status(websocket, task_id, task_status)
                                                    if await sleep_or_shutdown(_shutdown_event, backoff):
                                                        final_exit_code = exit_code
                                                        final_report_file = report_file
                                                        final_error = "Worker shutdown requested"
                                                        task_status.status = "failed"
                                                        task_status.exit_code = exit_code
                                                        task_status.error = final_error
                                                        task_status.updated_at = time.time()
                                                        await _push_task_status(websocket, task_id, task_status)
                                                        break
                                                else:
                                                    final_exit_code = exit_code
                                                    final_report_file = report_file
                                                    final_error = error
                                                    task_status.status = "failed"
                                                    task_status.retry_count = attempt
                                                    task_status.exit_code = exit_code
                                                    task_status.error = error
                                                    task_status.updated_at = time.time()
                                                    await _push_task_status(websocket, task_id, task_status)
                                                    logger.info(f"[{task_id}] All retries exhausted after {attempt} attempts. Final exit code: {exit_code}")
                                                    break

                                            # Send final result to master
                                            await websocket.send(json.dumps({
                                                "type": "done",
                                                "task_id": task_id,
                                                "code": final_exit_code,
                                                "report_file": final_report_file,
                                                "error": final_error,
                                                "retry_count": task_status.retry_count,
                                                "max_retries": task_status.max_retries,
                                            }))
                                            active_task_id = None

                                        elif data["type"] == "update":
                                            task_id = data["task_id"]
                                            logger.info(f"\n[{task_id}] Received UPDATE command.")
                                            await run_manage_simc_update(websocket, task_id)
                                            last_simc_update_time = time.time()
                                    except asyncio.TimeoutError:
                                        pass
                        except websockets.ConnectionClosed:
                            logger.info("WebSocket connection closed by master.")
                            raise
                        except asyncio.CancelledError:
                            logger.info("Worker task cancelled — shutting down gracefully.")
                            raise
                except websockets.ConnectionClosed:
                    logger.info("WebSocket connection closed at session layer.")
                    raise
                except asyncio.CancelledError:
                    logger.info("Worker task cancelled at session layer.")
                    raise
        except websockets.ConnectionClosed:
            logger.info("WebSocket closed.")
        except asyncio.CancelledError:
            logger.info("Worker cancelled — shutting down.")
            break
        except Exception as e:
            logger.info(f"Connection lost or error: {e}.")

        # Graceful shutdown: finish any in-progress work
        if _shutdown_event.is_set():
            logger.info("Graceful shutdown complete.")
            break

        logger.info("Retrying in 5 seconds...")
        await asyncio.sleep(5)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "sim_helper":
        from src.cli.sim_helper import main
        sys.argv.pop(1)
        sys.exit(main())
    elif len(sys.argv) > 1 and sys.argv[1] == "manage_simc":
        from utils.manage_simc import main
        sys.argv.pop(1)
        sys.exit(main())

    import multiprocessing
    multiprocessing.freeze_support()

    try: asyncio.run(run_worker())
    except KeyboardInterrupt: pass
