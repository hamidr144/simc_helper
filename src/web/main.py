import asyncio
import glob
import hmac
import html
import json
import logging
import os
import re
import sys
import time
import uuid
import datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers['X-Request-ID'] = request_id
        return response

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger = logging.getLogger("master")
        request_id = getattr(request.state, "request_id", None)
        # Increment total request counter
        global simc_requests_total
        simc_requests_total += 1
        logger.info(
            f"Incoming request {request.method} {request.url.path}",
            extra={"request_id": request_id},
        )
        response = await call_next(request)
        # Increment error counter on HTTP error status codes
        if response.status_code >= 400:
            global simc_errors_total
            simc_errors_total += 1
        logger.info(
            f"Response status {response.status_code} for {request.method} {request.url.path}",
            extra={"request_id": request_id},
        )
        return response
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

import httpx
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.addon_parser import (
    FOREVER_EXPORT_MESSAGE,
    count_embedded_copies,
    forever_export_warnings,
    is_forever_export,
    parse_addon_lines,
    strip_embedded_copies,
)
from src.core import armory as armory_source
from src.core.armory import (
    ArmoryError,
    ArmoryInputError,
    ArmoryNotFoundError,
    ArmoryParseError,
    ArmoryRateLimitedError,
    ArmoryUnavailableError,
    parse_armory_input,
    parse_armory_model,
)
from src.core.circuit_breaker import CircuitBreaker
from src.core.db import (
    auth_session_create,
    auth_session_delete,
    auth_session_purge_expired,
    auth_session_user,
    init_db,
    input_set,
    load_inputs,
    load_sessions,
    run_history_get,
    run_history_insert,
    run_history_list,
    session_cleanup_older_than,
    session_get,
    session_set,
    task_owner_load,
    task_owner_prune_older_than,
    task_owner_upsert,
    user_create,
    user_get,
    user_set_password_hash,
)
from src.core.env import get_bind_host, load_cluster_secret, require_admin_token
from src.core.paths import safe_child_path, safe_task_dir, validate_safe_id
from src.core.security import (
    RateLimiter,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from src.worker import get_or_create_task_status, task_status_store


# ---------------------------------------------------------------------------
# Pydantic request / response schemas for OpenAPI docs
# ---------------------------------------------------------------------------
# Fighting styles for /api/generate-simc.  ``single_boss`` is the default and
# fixes the fight at 5 minutes with ``duration=300``; it deliberately emits no
# ``time_to_die`` so the boss never dies early.  ``dungeon_slice`` models a
# short Mythic+ pull: the enemy dies after ~30 s, so long fights (and their
# second cooldown window) never happen.  ``time_to_die`` fixes the kill time;
# ``duration`` caps the fight length for iterations where the sim would
# otherwise run longer.
FIGHT_STYLE_SINGLE_BOSS = "single_boss"
FIGHT_STYLE_DUNGEON_SLICE = "dungeon_slice"
FIGHT_STYLE_DIRECTIVES = {
    FIGHT_STYLE_SINGLE_BOSS: (
        "# fighting style: single boss (5 min fixed fight)\n"
        "duration=300\n"
    ),
    FIGHT_STYLE_DUNGEON_SLICE: (
        "# fighting style: dungeon slice (short Mythic+ pull)\n"
        "duration=30\n"
        "time_to_die=30\n"
    ),
}

# TG2 generation modes (design §4.1): ``single_swap`` is the shipped behavior;
# ``combinations`` emits the cross-slot Top Gear product via
# ``build_combination_copies``.
MODE_SINGLE_SWAP = "single_swap"
MODE_COMBINATIONS = "combinations"
TG_GENERATION_MODES = (MODE_SINGLE_SWAP, MODE_COMBINATIONS)
# shortcut: combination budget fixed from env at import; upgrade path =
# POST /api/settings, ruled out of this epic (TG2-ACCEPT Q1, env-only).
TG_MAX_COMBINATIONS = int(os.environ.get("SIMC_TG_MAX_COMBINATIONS", "5000"))
# shortcut: 1 it/s is ~10x pessimistic vs the measured ~9.7 it/s reference
# worker; recalibrate once the TG2 E2E records real throughput (risk R2).
TG_WORK_ESTIMATE_ITERS_PER_SEC = float(os.environ.get("SIMC_TG_ITERS_PER_SEC", "1"))
# shortcut: stage-1 iteration cap for the work estimate; rewired to the
# SIMC_HELPER_STAGE_PLAN knob in TG2-C (t_590f5317).
TG_STAGE1_ITERATIONS_CAP = 200


class GenerateSimcRequest(BaseModel):
    """Payload for ``/api/generate-simc`` – build a SimulationCraft profile."""
    char_class: str
    char_name: str
    base_profile: str
    fight_style: Optional[str] = FIGHT_STYLE_SINGLE_BOSS
    mode: str = MODE_SINGLE_SWAP
    equipped_gear: Dict[str, str]
    selected_items: Dict[str, List[str]]
    selected_enchants: Optional[Dict[str, Any]] = {}
    selected_gems: Optional[List[Union[str, int]]] = []
    selected_meta_gems: Optional[List[Union[str, int]]] = []
    item_levels: Optional[Dict[str, Dict[str, Optional[int]]]] = {}
    gear_upgrades: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = {}
    voidforged_items: Optional[Dict[str, Dict[str, bool]]] = {}
    extra_sockets: Optional[Dict[str, bool]] = {}
    upgrade_season: Optional[str] = None


class ParseAddonRequest(BaseModel):
    """Payload for ``/api/parse-addon`` – parse addon text into structured data."""
    addon_text: str


class ParseAddonResponse(BaseModel):
    """Response from ``/api/parse-addon``."""
    base_profile: str
    equipped_gear: Dict[str, str]
    items_by_slot: Dict[str, List[str]]
    item_names: Dict[str, str]
    char_name: str
    char_class: str
    item_upgrades: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []


class ArmoryLoadRequest(BaseModel):
    """Payload for ``/api/armory-load`` – load a character from the Armory.

    Either a full Armory profile ``url`` (worldsoul or legacy battle.net
    form) or a ``name`` + ``realm`` pair (``name`` may also carry the
    combined ``Name-Realm`` / ``Name, Realm`` free-text form).  ``region``
    defaults to ``eu`` and is ignored when the URL carries one.
    """
    url: Optional[str] = None
    name: Optional[str] = None
    realm: Optional[str] = None
    region: Optional[str] = None


class ArmoryLoadResponse(BaseModel):
    """Response from ``/api/armory-load`` – same shape as ``/api/parse-addon``
    plus ``char_spec`` / ``char_ilvl`` so the UI chip can show spec and ilvl."""
    base_profile: str
    equipped_gear: Dict[str, str]
    items_by_slot: Dict[str, List[str]]
    item_names: Dict[str, str]
    char_name: str
    char_class: str
    char_spec: str = ""
    char_ilvl: Optional[float] = None
    item_upgrades: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []


class WowheadUpgradesRequest(BaseModel):
    """Payload for ``/api/wowhead-upgrades`` – look up gear upgrade paths."""
    items_by_slot: Dict[str, List[str]]


class WowheadTooltipBatchEntry(BaseModel):
    """One item to resolve in ``/api/wowhead/tooltips/batch``."""
    item: int = Field(..., ge=1, le=10_000_000)
    bonus: Optional[str] = None


class WowheadTooltipBatchRequest(BaseModel):
    """Payload for ``/api/wowhead/tooltips/batch`` – resolve + score a slot's items."""
    char_class: Optional[str] = None
    items: List[WowheadTooltipBatchEntry]


class SimulationRequest(BaseModel):
    user_id: str
    sim_time: float


class WowheadUpgradeInfo(BaseModel):
    track: str
    rank: int
    item_level: Optional[int] = None


class WowheadUpgradesResponse(BaseModel):
    """Response from ``/api/wowhead-upgrades``."""
    status: str
    gear_upgrades: Dict[str, Dict[str, WowheadUpgradeInfo]]
    errors: List[str]


class GenerateSimcResponse(BaseModel):
    """Response from ``/api/generate-simc``."""
    status: str
    file_path: str
    input_id: str
    input_url: str
    combinations: int
    mode: str = MODE_SINGLE_SWAP
    # Stage-1-only honest lower bound, combinations mode only (design §4.2).
    work_estimate_minutes: Optional[float] = None
    # TG3-D2: copy= blocks stripped from the caller's base profile.
    embedded_copies: int = 0


class TaskStatusResponse(BaseModel):
    """Response from ``/api/task-status`` (single task)."""
    status: str
    task_id: str
    task: Optional[Dict[str, Any]] = None


class TaskListResponse(BaseModel):
    """Response from ``/api/task-status`` (all tasks)."""
    status: str
    tasks: Optional[Dict[str, Dict[str, Any]]] = None
    total: Optional[int] = None


class RunSimulationResponse(BaseModel):
    """Response from ``/api/run-simulation``."""
    status: str
    task_id: str
    worker_id: str


class GetResultsResponse(BaseModel):
    """Response from ``/api/get-results``."""
    status: str
    results: Optional[List[Dict[str, Any]]] = None
    message: Optional[str] = None


class WorkerUploadFileResponse(BaseModel):
    """Response from ``/api/worker/upload-file``."""
    status: str


class SimResultItem(BaseModel):
    """An individual result row inside ``/api/get-results``."""
    name: str
    dps: int
    gear: Dict[str, str]


class HealthDetailsWorker(BaseModel):
    """Worker counts in the health endpoint."""
    connected: int
    idle: int
    busy: int


class HealthDetailsSimc(BaseModel):
    """SimulationCraft binary status."""
    available: bool
    path: str
    size_bytes: int


class HealthDetailsDisk(BaseModel):
    """Disk space information."""
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_percent: float
    inputs_dir: str


class HealthResponse(BaseModel):
    """Response from ``/health``.

    Audit LOW-1: unauthenticated remote callers only receive ``status``;
    ``timestamp``/``details`` are populated for localhost callers and for
    requests carrying a valid ``X-Admin-Token`` header.
    """
    status: str
    timestamp: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class StateResponse(BaseModel):
    """Response from ``/api/state``."""
    status: str
    active_input: Optional[str] = None
    workers: List[Dict[str, str]]


class UpdateSimcResponse(BaseModel):
    """Response from ``/api/update-simc``."""
    status: str
    task_id: str


class StopSimulationResponse(BaseModel):
    """Response from ``/api/stop-simulation``."""
    status: str
    message: str


class ShutdownResponse(BaseModel):
    """Response from ``/api/shutdown``."""
    status: str


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------
class SettingsResponse(BaseModel):
    """Response from ``/api/settings``.

    Sensitive runtime values (dev mode, WebSocket sizing) are deliberately
    not exposed over the wire (audit F2).
    """
    master_url: str
    log_level: str
    sim_cooldown_seconds: int
    cors_enabled: bool
    cors_allowed_origins: str


class UpdateSettingsRequest(BaseModel):
    """Payload for ``/api/settings`` (POST).

    ``SIMC_HELPER_DEV_MODE`` is env-only and cannot be toggled through this
    API (audit F2); the field was removed from this model entirely.
    """
    master_url: str
    log_level: str
    sim_cooldown_seconds: int
    cors_enabled: bool
    cors_allowed_origins: str
    ws_max_size: int

CLUSTER_SECRET = load_cluster_secret("master")
from contextlib import asynccontextmanager

from fastapi.templating import Jinja2Templates

BASE_DIR = os.environ.get("BASE_DIR", ".")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DATA_DIR = os.path.join(BASE_DIR, "data", "master")
INPUTS_DIR = os.path.join(DATA_DIR, "inputs")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(INPUTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
# Replace the basic logging setup with structured JSON logging via
# ``src.core.logging``.  ``logger`` is still a standard ``logging.Logger``
# — only the formatter changes (JSON in prod, plain-text in dev).
from src.core.logging import setup_logging  # noqa: E402

logger = setup_logging("master")
SIM_COOLDOWN_SECONDS = int(os.environ.get("SIM_COOLDOWN_SECONDS", "300"))  # 5 minutes

# Initialize DB (creates tables if not exist) – must happen before load_sessions/load_inputs
init_db()

# In-memory storage (backed by SQLite)
user_last_sim_time = load_sessions()
generated_inputs_by_user: dict = load_inputs()
# t_2f386596: the global "latest" input used to live inside this map under a
# magic key that collided with real buckets (the client-controlled user_id
# cookie fallback when auth is disabled, and legacy user_inputs rows loaded
# above). SEC-8 (t_ff260cdb) removed the global latest entirely — every
# reader answers from the caller's own bucket. Drop the legacy rows.
generated_inputs_by_user.pop("latest", None)
# t_c968bf8d: task_id -> user_id so worker uploads land in the owner's report
# directory. LIFE-2 (t_2c718ca6): durable in the sqlite task_owner table —
# an in-memory-only map lost report attribution when the master restarted
# mid-run. Hydrated at startup; rows pruned after 24h.
task_user_map: dict = {}
# t_b3b78acd: per-user character metadata captured as the user walks the flow
# (parse-addon / armory-load record the source; generate-simc records the
# fight style, spec and name). run_simulation snapshots it per task (also in
# task_owner.meta) so the done hook can write a complete run_history row.
run_meta_by_user: Dict[str, Dict[str, Any]] = {}
task_meta_map: Dict[str, Dict[str, Any]] = {}
# LIFE-4 (t_5d6903e4): the worker's done payload, kept briefly after the run
# frees its queue entry so a viewer that opens the stream late (fast run, or a
# tab that reconnects after the run ended) still gets a terminal event instead
# of a 404. Pruned on every write.
task_done_map: Dict[str, Dict[str, Any]] = {}
TASK_DONE_TTL_SECONDS = 300


def _record_task_done(task_id: str, data: Dict[str, Any]) -> None:
    now = time.time()
    for stale in [t for t, d in task_done_map.items() if now - d.get("_at", 0) > TASK_DONE_TTL_SECONDS]:
        task_done_map.pop(stale, None)
    task_done_map[task_id] = {**data, "_at": now}


def _restore_task_owner_maps() -> None:
    """Hydrate task_user_map / task_meta_map from sqlite (LIFE-2)."""
    for _tid, _row in task_owner_load().items():
        task_user_map[_tid] = _row["user_id"]
        try:
            task_meta_map[_tid] = json.loads(_row["meta"]) if _row["meta"] else {}
        except ValueError:
            task_meta_map[_tid] = {}


task_owner_prune_older_than(time.time() - 86400)
_restore_task_owner_maps()
wowhead_upgrade_cache = {}
wowhead_icon_cache: Dict[str, tuple[bytes, str]] = {}
wowhead_tooltip_script_cache: Optional[bytes] = None

# GET /api/wowhead/tooltip – TTL cache of raw nether.wowhead.com tooltip JSON.
WOWHEAD_TOOLTIP_TIMEOUT_SECONDS = 8.0
WOWHEAD_TOOLTIP_MAX_BYTES = 256 * 1024
WOWHEAD_TOOLTIP_CACHE_TTL_SECONDS = 3600
WOWHEAD_TOOLTIP_CACHE_MAX_ENTRIES = 512
wowhead_tooltip_json_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}

# Wowhead item quality colours (q0..q8) – used only to tint the preview name.
WOWHEAD_QUALITY_COLORS = {
    0: "#ffffff", 1: "#9d9d9d", 2: "#1eff00", 3: "#40c0ff", 4: "#a335ee",
    5: "#ff8000", 6: "#e6cc80", 7: "#e6cc80", 8: "#00ccff",
}

MIDNIGHT_WOWHEAD_TRACKS = {
    "Adventurer": "adventurer",
    "Veteran": "veteran",
    "Champion": "champion",
    "Hero": "hero",
    "Myth": "myth",
}

# Worker Manager
# Circuit breaker thresholds for worker connections
CB_FAILURE_THRESHOLD = int(os.environ.get("WORKER_CB_FAILURE_THRESHOLD", "5"))
CB_RECOVERY_TIMEOUT = float(os.environ.get("WORKER_CB_RECOVERY_TIMEOUT", "30.0"))

class Worker:
    def __init__(self, id: str, name: str, websocket: WebSocket):
        self.id = id
        self.name = name
        self.ws = websocket
        self.status = "Idle"  # Idle, Busy, Unavailable
        self.current_task = None
        self.last_ping = time.time()
        self.user_id = None
        # Circuit breaker for this worker's connection
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=CB_FAILURE_THRESHOLD,
            recovery_timeout=CB_RECOVERY_TIMEOUT,
        )

    @property
    def is_unavailable(self) -> bool:
        """Whether the circuit breaker has opened this worker."""
        return self.circuit_breaker.state.value != "closed"

    def mark_connection_success(self) -> None:
        """Record a successful ping or message — resets circuit breaker."""
        self.circuit_breaker.record_success()

    def mark_connection_failure(self) -> None:
        """Record a failed connection or ping — may open circuit breaker."""
        self.circuit_breaker.record_failure()
        self.status = "Unavailable"

    def try_recovery(self) -> None:
        """Attempt recovery when circuit transitions to HALF_OPEN."""
        if self.circuit_breaker.state.value == "half_open":
            # One successful ping will close the circuit
            pass

class WorkerManager:
    def __init__(self):
        self.active_workers: Dict[str, Worker] = {}
        # LIFE-4 (t_5d6903e4): one subscriber queue per connected SSE viewer;
        # producers broadcast to all of them, so a disconnect (or a second
        # tab) can no longer delete or starve another viewer's stream.
        self.task_queues: Dict[str, Set[asyncio.Queue]] = {}
        self._shutting_down = False

    async def connect(self, websocket: WebSocket, name: str):
        await websocket.accept()
        worker_id = str(uuid.uuid4())[:8]
        worker = Worker(worker_id, name, websocket)
        self.active_workers[worker_id] = worker
        logger.info(f"Worker {name} ({worker_id}) connected.")
        # Reset circuit breaker on fresh connection
        worker.circuit_breaker.reset()
        return worker_id

    def disconnect(self, worker_id: str):
        if worker_id in self.active_workers:
            worker = self.active_workers[worker_id]
            logger.info(f"Worker {worker.name} ({worker_id}) disconnected.")

            # If worker was busy, notify the task queue that it failed
            if worker.current_task and worker.current_task in self.task_queues:
                for queue in self.task_queues[worker.current_task]:
                    queue.put_nowait(
                        {
                            "type": "error",
                            "text": f"Worker {worker.name} disconnected abruptly.",
                        }
                    )

            del self.active_workers[worker_id]

    def get_idle_worker(self):
        for wid, w in self.active_workers.items():
            if w.status == "Idle": return wid
        return None

    async def send_task(self, worker_id: str, task: Dict):
        if worker_id in self.active_workers:
            await self.active_workers[worker_id].ws.send_json(task)

    async def ping_worker(self, worker_id: str) -> bool:
        """Send a ping to a worker and record success/failure on the circuit breaker."""
        worker = self.active_workers.get(worker_id)
        if not worker:
            return False
        try:
            await worker.ws.send_json({"type": "ping"})
            worker.mark_connection_success()
            if worker.status == "Unavailable":
                worker.status = "Idle"
            return True
        except Exception:
            worker.mark_connection_failure()
            return False

manager = WorkerManager()

async def enforcer():
    """Background task to clean up dead workers and old rate limits."""
    while True:
        try:
            now = time.time()

            # Clean up workers whose circuit breaker is open (consecutive failures)
            for wid, w in list(manager.active_workers.items()):
                if w.circuit_breaker.state.value == "open":
                    logger.info(f"Worker {w.name} ({wid}) circuit breaker OPEN — removing.")
                    manager.disconnect(wid)
                    continue

                # Also clean up dead workers (no ping for 30s)
                if now - w.last_ping > 30:
                    logger.info(f"Worker {w.name} ({wid}) stale — removing.")
                    manager.disconnect(wid)

            # Clean up old rate limit entries (older than cooldown) via DB
            old_users = session_cleanup_older_than(SIM_COOLDOWN_SECONDS, now)
            for uid in old_users:
                user_last_sim_time.pop(uid, None)
        except Exception as e:
            logger.error(f"Enforcer error: {e}")
        await asyncio.sleep(30)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    asyncio.create_task(enforcer())

    yield

    # Shutdown — ensure all workers are cleaned up
    logger.info("Shutting down worker connections...")
    for wid, w in list(manager.active_workers.items()):
        try:
            await w.ws.close(1001, "Server shutting down")
        except Exception:
            pass
        manager.disconnect(wid)
    logger.info("All workers disconnected.")

app = FastAPI(
    # Register middlewares
    # Request ID middleware adds a unique X-Request-ID header to each response
    # Logging middleware logs each request with its ID
    # FastAPI's add_middleware expects the middleware class; we add them after app creation below

    lifespan=lifespan,
    title="SimulationCraft Helper",
    description=(
        "A distributed SimulationCraft batch-simulation platform for World of Warcraft gear optimisation.\n"
        "\n"
        "### Features\n"
        "- **Web UI** – interactive gear picker with Wowhead upgrade tracking, voidforge, and item-level sliders\n"
        "- **REST API** – generate SimulationCraft profiles, run simulations, stream results\n"
        "- **Worker cluster** – WebSocket-based distributed workers with retry logic and task status tracking\n"
        "- **Persistent storage** – SQLite-backed session & input history\n"
        "\n"
        "### Authentication\n"
        "- Interactive pages and state-changing API endpoints require a logged-in session (`session_id` cookie); unauthenticated API calls get 401\n"
        "- Admin endpoints require the `X-Admin-Token` header (`admin_token` query param is dev-mode only)\n"
        "- Worker nodes authenticate via the `X-Cluster-Secret` header (`CLUSTER_SECRET` env var)\n"
        "\n"
        "### Rate Limiting\n"
        "- Simulations are rate-limited to one per user every 300 seconds (5 minutes)\n"
    ),
    version="1.0.0",
    contact={"name": "simc-helper team"},
    license={"name": "MIT"},
)

# ---------------------------------------------------------------------------
# CORS middleware  (enabled via CORS_ALLOWED_ORIGINS env var)
# ---------------------------------------------------------------------------
# CORS_ALLOWED_ORIGINS is a JSON array of origins, e.g.
#   ["http://localhost:3000","http://localhost:8080"]
# Leave unset or empty to allow no CORS (same-origin only).
# In dev mode (SIMC_HELPER_DEV_MODE=1) all origins are allowed.
_cors_origins_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _cors_origins_env.strip():
    import ast
    try:
        allowed_origins = ast.literal_eval(_cors_origins_env)
    except Exception:
        allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
else:
    allowed_origins = []

if os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
    allowed_origins = ["*"]

if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    logger.info("CORS enabled for origins: %s", allowed_origins)

# Create and mount reports directory
# t_c968bf8d: durable report storage on the simc-data volume (mounted at
# $BASE_DIR/data in both master and worker containers). Layout is
#   <REPORTS_DIR>/<user_id>/<task_id>/report_*.html
# so results survive container restarts. Existing /tmp/simc_reports data is
# intentionally NOT migrated (it was already lost on every restart).
REPORTS_DIR = os.environ.get("REPORTS_DIR") or os.path.join(BASE_DIR, "data", "reports")
# Per-user retention cap: the oldest run directories are pruned on insert.
REPORT_RETENTION = int(os.environ.get("REPORT_RETENTION", "50"))
os.makedirs(REPORTS_DIR, exist_ok=True)
class _SessionStaticFiles(StaticFiles):
    """SEC-5 (t_28df6d81): reports are per-user sim output, so the mount
    demands the same session the API endpoints demand (require_session is
    resolved at request time; the AUTHENTICATION_ENABLED kill switch still
    bypasses it, returning "anonymous").

    TG3-SECFIX (t_71013ac2): session existence alone leaked any user's
    reports to any logged-in caller who knew the URL. With auth enabled the
    first path segment (``<user_dir>/...``, as normalized by
    ``StaticFiles.get_path``) must equal the caller's own report directory —
    the same rule as ``_task_access_ok``. Non-owners get the mount's own 404,
    never a 403, so foreign report URLs are indistinguishable from missing
    ones (no existence oracle)."""

    async def get_response(self, path: str, scope):
        user_id = require_session(Request(scope))
        if authentication_enabled() and path.split("/", 1)[0] != _user_report_dir(user_id):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


app.mount("/reports", _SessionStaticFiles(directory=REPORTS_DIR), name="reports")

# Register middlewares for request ID and structured logging
app.add_middleware(RequestIDMiddleware)
app.add_middleware(LoggingMiddleware)

# Prometheus metrics counters (simple in-memory counters)
simc_requests_total = 0
simc_errors_total = 0

# Prometheus metrics endpoint – returns plain‑text exposition format
@app.get("/metrics", tags=["Metrics"])
async def get_metrics(request: Request):
    """Expose simple Prometheus metrics for the master service.

    Audit LOW-1: metrics are operational data, so the endpoint now requires
    the admin token (``X-Admin-Token`` header) whenever ``ADMIN_TOKEN`` is
    configured.

    Currently provides:
    - ``simc_requests_total`` – total number of API requests handled
    - ``simc_errors_total`` – total number of error responses
    """
    require_admin(request)
    # Increment request counter via a middleware hook (not shown here) – for demo we just expose current values
    return (
        f"# HELP simc_requests_total Total number of handled API requests\n"
        f"# TYPE simc_requests_total counter\n"
        f"simc_requests_total {simc_requests_total}\n"
        f"# HELP simc_errors_total Total number of error responses\n"
        f"# TYPE simc_errors_total counter\n"
        f"simc_errors_total {simc_errors_total}\n"
    )

# Mount static files
base_dir = getattr(sys, '_MEIPASS', os.path.abspath("."))
static_dir = os.path.join(base_dir, "src", "web", "static")
if not os.path.exists(static_dir):
    static_dir = os.path.join(os.path.abspath("."), "src", "web", "static")

app.mount("/static", StaticFiles(directory=static_dir), name="static")
LOGIN_PAGE = os.path.abspath(os.path.join(static_dir, "login.html"))
REGISTER_PAGE = os.path.abspath(os.path.join(static_dir, "register.html"))
APP_PAGE = os.path.abspath(os.path.join(static_dir, "app.html"))
RESULTS_PAGE = os.path.abspath(os.path.join(static_dir, "results.html"))
HISTORY_PAGE = os.path.abspath(os.path.join(static_dir, "history.html"))


templates = Jinja2Templates(directory=static_dir)


def authentication_enabled() -> bool:
    """Return whether interactive user login is required."""
    return os.environ.get("AUTHENTICATION_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


SESSION_TTL_SECONDS = 3600 * 24 * 7  # must match the session cookie max_age


def _session_user(request: Request) -> Optional[Dict[str, Any]]:
    """Resolve the ``session_id`` cookie to its user record, or None.

    SEC-7 (t_0e328148): the cookie is an opaque token issued at
    login/register and recorded in the ``auth_sessions`` table — the
    server-side session store. Deleting the row (logout, expiry, account
    deletion) invalidates the cookie immediately, so a copied cookie dies
    with its session instead of being valid forever.
    """
    token = request.cookies.get("session_id")
    if not token:
        return None
    return auth_session_user(token, time.time())


def _issue_session(user_id: str) -> str:
    """Create an opaque session token (SEC-7) and record it server-side."""
    token = uuid.uuid4().hex
    now = time.time()
    auth_session_purge_expired(now)
    auth_session_create(token, user_id, now + SESSION_TTL_SECONDS)
    return token


def require_session(request: Request) -> str:
    """FastAPI dependency: require a valid server-side session on an endpoint.

    The ``session_id`` cookie must be a token issued at login/register and
    still present (unexpired) in ``auth_sessions`` (SEC-7).

    Security policy (P0 audit F1):
    - ``SIMC_HELPER_DEV_MODE`` must NEVER bypass this gate — dev mode only
      relaxes page redirects, never API auth.
    - Only the operator-level ``AUTHENTICATION_ENABLED=false`` kill switch
      (env-only) bypasses it, matching the login-free page behaviour.

    Returns the authenticated user_id, or ``"anonymous"`` when auth is
    disabled process-wide.
    """
    if not authentication_enabled():
        return "anonymous"
    if not request.cookies.get("session_id"):
        raise HTTPException(status_code=401, detail="Authentication required")
    user = _session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user["user_id"]


def _input_bucket(request: Request, current_user: str) -> str:
    """Key of the caller's generated-input bucket in generated_inputs_by_user.

    Shared by generate-simc, run-simulation and /api/state so writer and
    readers cannot disagree (SEC-8 t_ff260cdb). With auth disabled
    require_session returns "anonymous", so fall back to the legacy
    client-controlled user_id cookie / client-IP bucket (single-operator mode).
    """
    if current_user != "anonymous":
        return current_user
    return request.cookies.get("user_id") or f"ip_{request.client.host}"


def _page_session_valid(request: Request) -> bool:
    """True when the request carries a valid server-side session token.

    Page gates use exactly the same rule as ``require_session`` (SEC-7):
    the opaque token must exist unexpired in ``auth_sessions``. The
    ``user_sessions`` table is only sim-cooldown state and is purged every
    ``SIM_COOLDOWN_SECONDS`` (300s) — trusting it for page auth silently
    logged users out ~5 minutes after login (t_ef8682a4).
    """
    return _session_user(request) is not None


def _dev_mode_enabled() -> bool:
    return os.environ.get("SIMC_HELPER_DEV_MODE") == "1"


def require_admin(request: Request) -> None:
    """Audit MEDIUM-2: admin token must travel in a header, not a URL.

    Only the ``X-Admin-Token`` header is accepted in production. The legacy
    ``admin_token`` query parameter is honoured exclusively while
    ``SIMC_HELPER_DEV_MODE=1`` (with a warning) so secrets never land in
    access logs, browser history, or Referer headers.
    """
    token = request.headers.get("X-Admin-Token")
    if not token:
        token = request.query_params.get("admin_token")
        if token:
            if _dev_mode_enabled():
                logger.warning(
                    "admin_token query parameter is deprecated; use the X-Admin-Token header"
                )
            else:
                token = None
    require_admin_token(token)


def _cluster_secret_ok(header_secret: Optional[str], query_secret: Optional[str]) -> bool:
    """Audit MEDIUM-2: workers authenticate via ``X-Cluster-Secret`` header.

    The legacy ``secret`` query parameter is accepted only in dev mode
    (``SIMC_HELPER_DEV_MODE=1``) with a warning, keeping the cluster secret
    out of URLs and access logs.
    """
    candidate = header_secret
    if not candidate and query_secret:
        if _dev_mode_enabled():
            logger.warning(
                "Cluster secret in URL query is dev-mode only; send the X-Cluster-Secret header"
            )
            candidate = query_secret
    if not candidate:
        return False
    return hmac.compare_digest(candidate, CLUSTER_SECRET)


def require_session_or_cluster(request: Request) -> str:
    """SEC-14 (t_28df6d81): gate a resource behind a browser session OR the
    cluster secret — workers fetch generated inputs without cookies."""
    if _cluster_secret_ok(request.headers.get("X-Cluster-Secret"), None):
        return "cluster"
    return require_session(request)


def _require_own_session(user_id: str, current_user: str) -> None:
    """Audit MEDIUM-1: session routes are scoped to the authenticated user.

    ``current_user`` is ``"anonymous"`` only when the operator-level
    ``AUTHENTICATION_ENABLED=false`` kill switch is on, in which case there
    is no session concept to enforce.
    """
    if current_user != "anonymous" and user_id != current_user:
        raise HTTPException(status_code=403, detail="Not your session")


def client_ip(request: Request) -> str:
    """Best-effort client identity for rate limiting (proxy headers are
    deliberately not trusted here — proxy hardening is a separate task)."""
    return request.client.host if request.client else "unknown"


# Set SIMC_COOKIE_SECURE=1 once every client reaches the app through the
# HTTPS front (docs/tls-fronting.md). Secure cookies are refused by
# browsers over plain HTTP, so the default stays off while loopback HTTP
# remains the host-local fallback.
COOKIE_SECURE = os.environ.get("SIMC_COOKIE_SECURE", "0").strip() == "1"


# In-memory per-IP limiters for the credential endpoints (audit F3).
# Login counts *failed* attempts so a successful login clears the window;
# register counts every attempt to cap account farming.
_login_failures = RateLimiter(max_events=5, window_seconds=300)
_registrations = RateLimiter(max_events=5, window_seconds=3600)


def app_response(request: Request) -> FileResponse:
    """Serve the app and ensure login-free users still get a stable identity."""
    response = FileResponse(APP_PAGE)
    if not request.cookies.get("user_id"):
        response.set_cookie(key="user_id", value=str(uuid.uuid4()), max_age=31536000, samesite="lax", secure=COOKIE_SECURE)
    return response

# t_62ff8faa: page redirects are relative (no leading "/") so they resolve
# correctly behind prefix-stripping reverse proxies (Caddy handle_path /simc/*).
@app.get("/")
async def root(request: Request):
    if not authentication_enabled() or "pytest" in sys.modules or os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        return app_response(request)
    
    if _page_session_valid(request):
        return RedirectResponse(url="dashboard", status_code=303)
    return FileResponse(LOGIN_PAGE)


@app.get("/dashboard")
async def dashboard(request: Request):
    if not authentication_enabled() or "pytest" in sys.modules or os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        return app_response(request)
        
    if _page_session_valid(request):
        return FileResponse(APP_PAGE)
    return RedirectResponse(url="login", status_code=303)


@app.get("/results")
async def results_page(request: Request):
    if not authentication_enabled() or "pytest" in sys.modules or os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        return FileResponse(RESULTS_PAGE)
    if _page_session_valid(request):
        return FileResponse(RESULTS_PAGE)
    return RedirectResponse(url="login", status_code=303)


@app.get("/history")
async def history_page(request: Request):
    """Run-history page (t_d34ced81).

    Gate note: unlike the older page routes above, the session cookie is
    validated by the shared session gate (``_page_session_valid``, SEC-7) —
    the cooldown table gets purged and must not back auth decisions.
    """
    if not authentication_enabled() or "pytest" in sys.modules or os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        return FileResponse(HISTORY_PAGE)
    if _page_session_valid(request):
        return FileResponse(HISTORY_PAGE)
    return RedirectResponse(url="login", status_code=303)


def _form_error(request: Request, page: str, status_code: int, detail: str):
    """t_6f351b30: browser form errors 303 back to the page with the message
    as ?error= (the page renders it in a styled box) instead of the raw JSON
    document; API clients that explicitly ask for JSON keep the HTTPException
    path and status codes."""
    if "application/json" in request.headers.get("accept", ""):
        raise HTTPException(status_code=status_code, detail=detail)
    return RedirectResponse(url=f"{page}?error={quote(detail)}", status_code=303)


@app.get("/login")
async def login_page(request: Request):
    if not authentication_enabled():
        return RedirectResponse(url="dashboard", status_code=303)
    if _page_session_valid(request):
        return RedirectResponse(url="dashboard", status_code=303)
    return FileResponse(LOGIN_PAGE)


@app.get("/register")
async def register_page(request: Request):
    if not authentication_enabled():
        return RedirectResponse(url="dashboard", status_code=303)
    if _page_session_valid(request):
        return RedirectResponse(url="dashboard", status_code=303)
    return FileResponse(REGISTER_PAGE)


@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...)):
    if not authentication_enabled():
        raise HTTPException(status_code=403, detail="User authentication is disabled")
    ip = client_ip(request)
    if _registrations.is_limited(ip):
        return _form_error(
            request,
            "register",
            429,
            f"Too many registrations; retry in {_registrations.retry_after(ip)}s",
        )
    _registrations.record(ip)
    if user_get(username):
        return _form_error(request, "register", 400, "Username already exists")

    password_hash = hash_password(password)
    user_id = user_create(username, password_hash)
    token = _issue_session(user_id)
    # Browser flow (t_e4d97db9): land on /dashboard logged in, exactly like
    # a successful /login, instead of dumping raw JSON on the user.
    redirect_resp = RedirectResponse(url="dashboard", status_code=303)
    redirect_resp.set_cookie(
        key="session_id",
        value=token,
        httponly=True,
        max_age=3600 * 24 * 7,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return redirect_resp


@app.post("/login")
async def login(request: Request, response: Response, username: str = Form(...), password: str = Form(...)):
    if not authentication_enabled():
        raise HTTPException(status_code=403, detail="User authentication is disabled")
    ip = client_ip(request)
    if _login_failures.is_limited(ip):
        return _form_error(
            request,
            "login",
            429,
            f"Too many failed login attempts; retry in {_login_failures.retry_after(ip)}s",
        )
    user = user_get(username)
    if not user or not verify_password(password, user["password_hash"]):
        _login_failures.record(ip)
        return _form_error(request, "login", 401, "Invalid username or password")

    # Transparent upgrade of legacy unsalted SHA-256 hashes to salted PBKDF2.
    if password_needs_rehash(user["password_hash"]):
        user_set_password_hash(user["user_id"], hash_password(password))
    _login_failures.reset(ip)

    # NOTE (t_ef8682a4): login must NOT touch ``user_sessions`` — that table
    # is purely sim-run cooldown state (see run_simulation). Writing it here
    # made every run started within the cooldown window after login return a
    # bogus 429 for users who had never run a simulation.

    token = _issue_session(user["user_id"])
    redirect_resp = RedirectResponse(url="dashboard", status_code=303)
    redirect_resp.set_cookie(
        key="session_id", 
        value=token, 
        httponly=True, 
        max_age=3600 * 24 * 7, 
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return redirect_resp


@app.get("/logout")
async def logout(request: Request):
    # SEC-7 (t_0e328148): revoke the session server-side, not just the
    # browser copy of the cookie — a captured cookie must die with logout.
    token = request.cookies.get("session_id")
    if token:
        auth_session_delete(token)
    redirect_resp = RedirectResponse(url="./", status_code=303)
    redirect_resp.delete_cookie("session_id")
    return redirect_resp


@app.get("/session/{user_id}")
async def get_session_route(user_id: str, current_user: str = Depends(require_session)):
    _require_own_session(user_id, current_user)
    last_sim_time = session_get(user_id)
    if last_sim_time is None:
        return {"user_id": user_id, "last_sim_time": None}
    return {"user_id": user_id, "last_sim_time": last_sim_time}


@app.post("/session/{user_id}/update")
async def update_session_route(user_id: str, request: SimulationRequest, current_user: str = Depends(require_session)):
    _require_own_session(user_id, current_user)
    session_set(user_id, request.sim_time)
    return {"status": "success", "user_id": user_id, "last_sim_time": request.sim_time}


def parse_simc_item_identity(item: str) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    fields = {}
    for part in item.split(','):
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        fields[key.strip()] = value.strip()
    item_id = fields.get("id")
    if not item_id or not item_id.isdigit():
        return None
    bonuses = [bonus for bonus in fields.get("bonus_id", "").replace(':', '/').split('/') if bonus.isdigit()]
    return {"id": item_id, "bonuses": bonuses}


def wowhead_xml_url(item: str) -> Optional[str]:
    parsed = parse_simc_item_identity(item)
    if not parsed:
        return None
    params = {"xml": ""}
    if parsed["bonuses"]:
        params["bonus"] = ':'.join(parsed["bonuses"])
    query = urlencode(params)
    return f"https://www.wowhead.com/item={parsed['id']}?{query}"


def parse_wowhead_upgrade(xml_text: str) -> Optional[Dict[str, Any]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None
    item = root.find("item")
    if item is None:
        return None
    tooltip = item.findtext("htmlTooltip") or ""
    text = re.sub(r"<[^>]+>", " ", tooltip)
    text = re.sub(r"\s+", " ", text)
    match = re.search(r"Upgrade Level:\s*(Adventurer|Veteran|Champion|Hero|Myth)\s*([1-9]\d*)/6", text)
    if not match:
        return None
    item_level = item.findtext("level")
    return {
        "track": MIDNIGHT_WOWHEAD_TRACKS[match.group(1)],
        "rank": int(match.group(2)),
        "item_level": int(item_level) if item_level and item_level.isdigit() else None,
    }


def parse_wowhead_icon_name(xml_text: str) -> Optional[str]:
    """Extract a safe icon name from a Wowhead item XML response."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None
    icon_name = (root.findtext("item/icon") or "").strip().lower()
    return icon_name if re.fullmatch(r"[a-z0-9_]+", icon_name) else None


@app.get("/api/item-icon/{item_id}", tags=["Gear"])
async def get_item_icon(item_id: int):
    """Proxy Wowhead item icons so the UI does not depend on external JavaScript."""
    cache_key = str(item_id)
    cached = wowhead_icon_cache.get(cache_key)
    if cached:
        image_bytes, media_type = cached
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    xml_url = f"https://www.wowhead.com/item={item_id}?xml"
    try:
        async with httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": "simc-helper/1.0"},
        ) as client:
            xml_response = await client.get(xml_url)
            xml_response.raise_for_status()
            icon_name = parse_wowhead_icon_name(xml_response.text)
            if not icon_name:
                raise ValueError("Wowhead response did not contain a valid icon name")
            icon_response = await client.get(
                f"https://wow.zamimg.com/images/wow/icons/large/{icon_name}.jpg"
            )
            icon_response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Unable to load icon for item %s: %s", item_id, exc)
        raise HTTPException(status_code=404, detail="Item icon unavailable") from exc

    media_type = icon_response.headers.get("content-type", "image/jpeg").split(";", 1)[0]
    image_bytes = icon_response.content
    wowhead_icon_cache[cache_key] = (image_bytes, media_type)
    return Response(
        content=image_bytes,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/wowhead-tooltips.js", tags=["Gear"])
async def get_wowhead_tooltip_script():
    """Serve Wowhead's official tooltip bundle through the local origin."""
    global wowhead_tooltip_script_cache
    if wowhead_tooltip_script_cache is None:
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "simc-helper/1.0"},
            ) as client:
                response = await client.get("https://wow.zamimg.com/js/tooltips.js")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Unable to load Wowhead tooltip script: %s", exc)
            raise HTTPException(status_code=502, detail="Wowhead tooltip script unavailable") from exc
        script = response.text
        route_marker = "function Se(e){"
        if route_marker not in script:
            raise HTTPException(status_code=502, detail="Unexpected Wowhead tooltip script")
        script = script.replace(
            route_marker,
            # new URL(...) resolves against the page, keeping any proxy path
            # prefix (t_62ff8faa); location.origin would drop it.
            'function Se(e){if(e==="nether"){return new URL("api/wowhead-nether",location.href).href}',
            1,
        )
        wowhead_tooltip_script_cache = script.encode("utf-8")

    return Response(
        content=wowhead_tooltip_script_cache,
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


WOWHEAD_NETHER_HOST = "nether.wowhead.com"
# Audit MEDIUM-3: only the paths the bundled Wowhead tooltip script actually
# requests through this proxy (``<route>/tooltip/<type>/<id>`` and the
# ``/data/*-scaling`` / ``/data/spec-spells`` fetches in WH.REMOTE mode).
WOWHEAD_NETHER_ALLOWED_PREFIXES = ("tooltip/", "ptr/tooltip/", "data/")


async def _nether_fetch(url: str) -> httpx.Response:
    """GET upstream with redirects pinned to ``nether.wowhead.com``.

    Audit MEDIUM-3: automatic redirect following was disabled in favour of a
    manual loop — any redirect that leaves the Wowhead host (SSRF pivot into
    the LAN / cloud metadata) is refused with a 502 instead of being fetched.
    """
    async with httpx.AsyncClient(
        timeout=15.0,
        follow_redirects=False,
        headers={"User-Agent": "simc-helper/1.0"},
    ) as client:
        for _ in range(4):  # initial request + up to 3 same-host redirects
            response = await client.get(url)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("location")
            if not location:
                return response
            next_url = httpx.URL(url).join(location)
            if next_url.host != WOWHEAD_NETHER_HOST:
                logger.warning(
                    "Refusing Wowhead proxy redirect to foreign host %s", next_url.host
                )
                raise HTTPException(status_code=502, detail="Wowhead tooltip data unavailable")
            url = str(next_url)
    raise HTTPException(status_code=502, detail="Wowhead tooltip data unavailable")


@app.get("/api/wowhead-nether/{path:path}", tags=["Gear"])
async def proxy_wowhead_tooltip_data(path: str, request: Request):
    """Proxy native Wowhead tooltip data for browsers that block third parties.

    Audit MEDIUM-3: path traversal is rejected (400), anything outside the
    tooltip/data prefix allowlist is rejected (403), and upstream redirects
    are followed only while they stay on ``nether.wowhead.com``.
    """
    if ".." in path or path.startswith("//"):
        raise HTTPException(status_code=400, detail="Invalid proxy path")
    if not path.startswith(WOWHEAD_NETHER_ALLOWED_PREFIXES):
        raise HTTPException(status_code=403, detail="Proxy path not allowed")
    upstream_url = f"https://{WOWHEAD_NETHER_HOST}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"
    try:
        response = await _nether_fetch(upstream_url)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Unable to load Wowhead tooltip data: %s", exc)
        raise HTTPException(status_code=502, detail="Wowhead tooltip data unavailable") from exc

    media_type = response.headers.get("content-type", "application/json").split(";", 1)[0]
    return Response(
        content=response.content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ---------------------------------------------------------------------------
# GET /api/wowhead/tooltip – server-side tooltip preview proxy
# ---------------------------------------------------------------------------
def wowhead_tooltip_id_list(value: Optional[str], field: str) -> Optional[str]:
    """Normalise a '1/2', '1:2' or '1,2' id list into the colon form Wowhead wants."""
    if value is None or not str(value).strip():
        return None
    parts = [part for part in re.split(r"[/,:;\s]+", str(value).strip()) if part]
    if not all(part.isdigit() for part in parts):
        raise HTTPException(status_code=400, detail=f"{field} must be a list of numeric ids")
    if len(parts) > 10:
        raise HTTPException(status_code=400, detail=f"{field} has too many ids")
    return ":".join(parts)


def wowhead_tooltip_url(item: int, env: str = "live", **overrides: Any) -> str:
    """Build a nether.wowhead.com tooltip URL with dataEnv/locale + optional overrides."""
    base = f"https://nether.wowhead.com{'/ptr' if env == 'ptr' else ''}/tooltip/item/{item}"
    query = {"dataEnv": "2" if env == "ptr" else "1", "locale": "en"}
    query.update({key: str(value) for key, value in overrides.items() if value is not None})
    return f"{base}?{urlencode(query)}"


async def fetch_wowhead_tooltip_json(upstream_url: str) -> Dict[str, Any]:
    """Fetch one nether.wowhead.com tooltip JSON payload (TTL cache + size cap).

    Kept as a module-level coroutine so tests can mock the upstream without a
    network. Failures raise ``httpx.HTTPError``/``ValueError``; the endpoint
    turns those into a graceful 502.
    """
    cached = wowhead_tooltip_json_cache.get(upstream_url)
    now = time.time()
    if cached and now - cached[0] < WOWHEAD_TOOLTIP_CACHE_TTL_SECONDS:
        return cached[1]
    async with httpx.AsyncClient(
        timeout=WOWHEAD_TOOLTIP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "simc-helper/1.0"},
    ) as client:
        response = await client.get(upstream_url)
    response.raise_for_status()
    if len(response.content) > WOWHEAD_TOOLTIP_MAX_BYTES:
        raise ValueError("Wowhead tooltip response too large")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Wowhead tooltip payload")
    if len(wowhead_tooltip_json_cache) >= WOWHEAD_TOOLTIP_CACHE_MAX_ENTRIES:
        oldest = min(wowhead_tooltip_json_cache, key=lambda key: wowhead_tooltip_json_cache[key][0])
        del wowhead_tooltip_json_cache[oldest]
    wowhead_tooltip_json_cache[upstream_url] = (now, payload)
    return payload


WOWHEAD_TOOLTIP_NON_STAT_PREFIXES = (
    "Item Level", "Upgrade Level", "Requires Level", "Required Level",
    "Durability", "Sell Price", "Binds", "Item Set", "Equip:", "Use:",
    "Chance on hit", "Soulbound", "Unique",
)


def wowhead_tooltip_lines(tooltip_html: str) -> List[str]:
    """Split a Wowhead tooltip HTML blob into plain text lines (markers stripped)."""
    text = re.sub(r"<!--.*?-->", "", tooltip_html, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:td|tr|table|div|p)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", html.unescape(raw)).strip()
        if line:
            lines.append(line)
    return lines


def parse_wowhead_tooltip(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compact preview (ilvl, quality, top stats) from a nether tooltip JSON payload."""
    tooltip_html = payload.get("tooltip")
    if not isinstance(tooltip_html, str):
        return None
    ilvl: Optional[int] = None
    upgrade_level: Optional[str] = None
    stats: List[Dict[str, Any]] = []
    for line in wowhead_tooltip_lines(tooltip_html):
        level_match = re.match(r"Item Level (\d+)", line)
        if level_match:
            ilvl = int(level_match.group(1))
            continue
        upgrade_match = re.match(r"Upgrade Level:\s*([A-Za-z]+)\s*(\d+)/(\d+)", line)
        if upgrade_match:
            upgrade_level = f"{upgrade_match.group(1)} {upgrade_match.group(2)}/{upgrade_match.group(3)}"
            continue
        if line.startswith(WOWHEAD_TOOLTIP_NON_STAT_PREFIXES) or re.fullmatch(r"\d+ \d+ \d+", line):
            continue
        stat_match = re.match(r"^\+?([\d,]+)\s+(.+)$", line)
        if stat_match:
            stats.append({
                "label": stat_match.group(2).strip().strip("[]"),
                "value": int(stat_match.group(1).replace(",", "")),
            })
    raw_quality = payload.get("quality")
    quality = int(raw_quality) if isinstance(raw_quality, (int, float)) else None
    return {
        "name": payload.get("name"),
        "quality": quality,
        "quality_color": WOWHEAD_QUALITY_COLORS.get(quality) if quality is not None else None,
        "ilvl": ilvl,
        "upgrade_level": upgrade_level,
        "stats": stats,
        "top_stats": " · ".join(f"{stat['value']:,} {stat['label']}" for stat in stats[:4]),
    }


def wowhead_tooltip_delta(
    current: Optional[Dict[str, Any]], preview: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Per-stat and ilvl delta between the item's current and previewed tooltip."""
    if not current or not preview:
        return None
    current_by_label = {stat["label"]: stat["value"] for stat in current.get("stats", [])}
    preview_by_label = {stat["label"]: stat["value"] for stat in preview.get("stats", [])}
    stats = []
    for label in dict.fromkeys(list(current_by_label) + list(preview_by_label)):
        before = current_by_label.get(label, 0)
        after = preview_by_label.get(label, 0)
        if after != before:
            stats.append({"label": label, "before": before, "after": after, "delta": after - before})
    ilvl_delta = None
    if current.get("ilvl") is not None and preview.get("ilvl") is not None:
        ilvl_delta = preview["ilvl"] - current["ilvl"]
    return {"ilvl": ilvl_delta, "stats": stats}


@app.get("/api/wowhead/tooltip", tags=["Gear"])
async def get_wowhead_tooltip_preview(
    item: int = Query(..., ge=1, le=10_000_000, description="Wowhead item id"),
    bonus: Optional[str] = Query(None, description="Bonus ids ('/', ':' or ',' separated)"),
    upgd: Optional[int] = Query(None, ge=0, le=10, description="Wowhead upgrade index"),
    gems: Optional[str] = Query(None, description="Gem item ids"),
    ench: Optional[str] = Query(None, description="Enchant id"),
    ilvl: Optional[int] = Query(None, ge=1, le=999, description="Resulting item level override"),
    lvl: Optional[int] = Query(None, ge=1, le=100, description="Character level context"),
    env: str = Query("live", pattern="^(live|ptr)$", description="Wowhead data environment"),
):
    """Server-side Wowhead tooltip preview for gear-card upgrade deltas.

    **Tags:** Gear
    **Upstream:** ``https://nether.wowhead.com[/ptr]/tooltip/item/<id>`` – proxied
    with an in-memory 1 h TTL cache, 8 s timeout and 256 KB size cap; the browser
    must never call Wowhead directly (CORS + bot walls).

    Returns the parsed resulting state (ilvl, quality colour, top stats) plus the
    delta vs the item's current tooltip whenever an override (ilvl/upgd/gems/ench)
    is present. Upstream failures degrade to a graceful 502.
    """
    bonus_ids = wowhead_tooltip_id_list(bonus, "bonus")
    gems_ids = wowhead_tooltip_id_list(gems, "gems")
    ench_ids = wowhead_tooltip_id_list(ench, "ench")

    overrides = {"bonus": bonus_ids, "upgd": upgd, "gems": gems_ids, "ench": ench_ids,
                 "ilvl": ilvl, "lvl": lvl}
    has_overrides = any(value is not None for value in overrides.values())

    try:
        preview_payload = await fetch_wowhead_tooltip_json(
            wowhead_tooltip_url(item, env, **overrides))
        if preview_payload.get("error"):
            raise HTTPException(status_code=404, detail=str(preview_payload["error"]))
        preview = parse_wowhead_tooltip(preview_payload)
        if preview is None:
            raise HTTPException(status_code=502, detail="Unparseable Wowhead tooltip")
        current = None
        if has_overrides:
            # Current state = the item with its own bonus ids only, no upgrade overrides.
            current_payload = await fetch_wowhead_tooltip_json(
                wowhead_tooltip_url(item, env, bonus=bonus_ids))
            if not current_payload.get("error"):
                current = parse_wowhead_tooltip(current_payload)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Item not found on Wowhead") from exc
        logger.warning("Unable to load Wowhead tooltip preview for %s: %s", item, exc)
        raise HTTPException(status_code=502, detail="Wowhead tooltip unavailable") from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Unable to load Wowhead tooltip preview for %s: %s", item, exc)
        raise HTTPException(status_code=502, detail="Wowhead tooltip unavailable") from exc

    return {
        "status": "success",
        "item": item,
        "env": env,
        "preview": preview,
        "current": current,
        "delta": wowhead_tooltip_delta(current, preview),
    }


# ---------------------------------------------------------------------------
# POST /api/wowhead/tooltips/batch – resolve + heuristic-score a slot's items
# ---------------------------------------------------------------------------
WOWHEAD_TOOLTIP_BATCH_MAX_ITEMS = 40


@app.post("/api/wowhead/tooltips/batch", tags=["Gear"])
async def post_wowhead_tooltips_batch(payload: WowheadTooltipBatchRequest):
    """Resolve several items in one request and score them with class stat weights.

    **Tags:** Gear
    **Upstream:** same TTL-cached nether.wowhead.com tooltip proxy as
    ``GET /api/wowhead/tooltip``; per-item failures come back as
    ``{"ok": false}`` entries instead of failing the whole batch.

    Powers the per-slot "Stat priority" sort: the client sends every item id
    (with its bonus ids) of one slot plus the character class, and sorts by
    the returned ``score``. Scores are a **heuristic** weighted sum (see
    ``src/core/data/stat_priorities.json``), never a sim result.
    """
    from src.core.stat_priorities import score_stats, weights_for_class

    if len(payload.items) > WOWHEAD_TOOLTIP_BATCH_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many items for one batch (max {WOWHEAD_TOOLTIP_BATCH_MAX_ITEMS})",
        )
    # Validate every bonus string up front so a bad entry is a clean 400.
    normalized_bonuses = []
    for entry in payload.items:
        try:
            normalized_bonuses.append(wowhead_tooltip_id_list(entry.bonus, "bonus"))
        except HTTPException as exc:
            raise HTTPException(status_code=400, detail=str(exc.detail)) from exc

    weights = weights_for_class(payload.char_class)

    async def resolve(index: int, entry: WowheadTooltipBatchEntry, bonus_ids: Optional[str]):
        try:
            tooltip_payload = await fetch_wowhead_tooltip_json(
                wowhead_tooltip_url(entry.item, bonus=bonus_ids))
            if tooltip_payload.get("error"):
                return index, {"index": index, "item": entry.item, "ok": False,
                               "error": str(tooltip_payload["error"])}
            preview = parse_wowhead_tooltip(tooltip_payload)
            if preview is None:
                return index, {"index": index, "item": entry.item, "ok": False,
                               "error": "Unparseable Wowhead tooltip"}
            return index, {
                "index": index,
                "item": entry.item,
                "ok": True,
                "name": preview["name"],
                "ilvl": preview["ilvl"],
                "quality": preview["quality"],
                "quality_color": preview["quality_color"],
                "score": score_stats(preview["stats"], weights),
            }
        except Exception as exc:  # per-item degradation, batch stays 200
            logger.warning("Batch tooltip failed for item %s: %s", entry.item, exc)
            return index, {"index": index, "item": entry.item, "ok": False,
                           "error": "Tooltip unavailable"}

    resolved = await asyncio.gather(
        *(resolve(i, entry, bonus)
          for i, (entry, bonus) in enumerate(zip(payload.items, normalized_bonuses))))
    return {
        "status": "success",
        "char_class": payload.char_class,
        "heuristic": True,
        "results": [result for _, result in sorted(resolved, key=lambda pair: pair[0])],
    }


@app.get("/api/stat-priorities", tags=["Gear"])
async def get_stat_priorities():
    """Heuristic per-class stat weights used by the gear-list stat-priority sort.

    **Tags:** Gear
    **Note:** Editable data file (``src/core/data/stat_priorities.json``); the
    payload carries ``heuristic: true`` so the UI can label the sort honestly.
    """
    from src.core.stat_priorities import load_stat_priorities
    return load_stat_priorities()


async def fetch_wowhead_upgrade(item: str) -> Optional[Dict[str, Any]]:
    url = wowhead_xml_url(item)
    if not url:
        return None
    if url in wowhead_upgrade_cache:
        return wowhead_upgrade_cache[url]
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers={"User-Agent": "simc-helper/1.0"}) as client:
        response = await client.get(url)
        response.raise_for_status()
    upgrade = parse_wowhead_upgrade(response.text)
    wowhead_upgrade_cache[url] = upgrade
    return upgrade


@app.get("/api/state", response_model=StateResponse, tags=["System"])
async def get_api_state(request: Request, user_id: str = Depends(require_session)):
    """Retrieve the current system state – active input and connected workers.

    **Tags:** System
    **Response Model:** ``StateResponse``

    Audit LOW-1: worker names/ids are internal topology, so this endpoint
    now requires a logged-in session (the dashboard sends its session cookie
    automatically).

    SEC-8 (t_ff260cdb): active_input is the caller's own latest generated
    input (or null) — never another user's global "latest".
    """
    record = generated_inputs_by_user.get(_input_bucket(request, user_id))
    return {
        "status": "ready",
        "active_input": record.get("input_id") if record else None,
        "workers": [
            {"id": w.id, "name": w.name, "status": w.status}
            for w in manager.active_workers.values()
        ]
    }


def _check_disk_space(path: str) -> Dict[str, Any]:
    """Return disk space info for *path* in bytes."""
    try:
        st = os.statvfs(path)
        free = st.f_bavail * st.f_frsize
        total = st.f_blocks * st.f_frsize
        used = total - (st.f_bfree * st.f_frsize)
        return {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "free_percent": round(100 * free / total, 1) if total else 0,
        }
    except OSError:
        return {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "free_percent": 0}


START_TIME = datetime.datetime.now(datetime.timezone.utc)

LOCAL_REQUEST_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}


def _is_local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in LOCAL_REQUEST_HOSTS


def _admin_token_provided(request: Request) -> bool:
    """True only when ADMIN_TOKEN is configured and the header matches it."""
    required = os.environ.get("ADMIN_TOKEN")
    provided = request.headers.get("X-Admin-Token")
    return bool(required and provided and hmac.compare_digest(provided, required))


@app.get("/health", response_model=HealthResponse, response_model_exclude_none=True, tags=["System"])
async def health_check(request: Request):
    """Health-check endpoint for Docker healthchecks and operational monitoring.

    **Tags:** System
    **Response Model:** ``HealthResponse``

    Audit LOW-1: remote unauthenticated callers get a bare ``{"status": ...}``
    (the Docker healthcheck only needs the 200 + status). Worker connectivity
    and disk details are reserved for localhost callers (the in-container
    healthcheck) and for requests with a valid ``X-Admin-Token`` header.

    Returns JSON with:
      - status: "ok" or "degraded"
      - timestamp: ISO-8601 UTC time (privileged callers only)
      - details: worker connectivity, disk space (privileged callers only)
    """
    import datetime

    # Determine overall status — only degraded if disk space is critically low
    disk = _check_disk_space(INPUTS_DIR)
    status = "ok"
    if disk.get("free_percent", 100) < 5:
        status = "degraded"

    if not (_is_local_request(request) or _admin_token_provided(request)):
        return {"status": status}

    workers = list(manager.active_workers.values())
    connected = len(workers)
    idle = sum(1 for w in workers if w.status == "Idle")
    busy = sum(1 for w in workers if w.status == "Busy")

    return {
        "status": status,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "uptime_seconds": int((datetime.datetime.now(datetime.timezone.utc) - START_TIME).total_seconds()),
        "details": {
            "workers": {
                "connected": connected,
                "idle": idle,
                "busy": busy,
            },
            "disk_space": {
                **disk,
                "inputs_dir": INPUTS_DIR,
            },
        },
    }


@app.get("/api/task-status", response_model=Union[TaskStatusResponse, TaskListResponse], tags=["Tasks"])
async def get_task_status(task_id: Optional[str] = None, user_id: str = Depends(require_session)):
    """Get task status for a specific task or list all tasks.

    **Tags:** Tasks
    **Query Parameters:**
      - ``task_id``: Optional task ID. Omit to list all tasks.

    **Response:** Returns a ``TaskStatusResponse`` for a single task or a
    ``TaskListResponse`` when listing all tasks.

    Ownership (SEC-2 residual t_1e5e7fb4): only the caller's own tasks are
    visible; another user's task_id answers with the same ``not_found`` shape
    as a nonexistent id (no existence oracle). Tasks with no resolvable owner
    row (update-simc tasks, attribution lost before LIFE-2) stay visible to
    every logged-in user — the documented pass-through bucket shared with
    ``_task_access_ok`` across the ownership family. With
    AUTHENTICATION_ENABLED=false the kill switch makes everything visible
    (single-operator mode).
    """
    if task_id:
        status = task_status_store.get(task_id)
        if not status or not _task_access_ok(task_id, user_id):
            return {"status": "not_found", "task_id": task_id}
        return {"status": "ok", "task_id": task_id, "task": status.to_dict()}
    visible = {tid: s for tid, s in task_status_store.items()
               if _task_access_ok(tid, user_id)}
    return {
        "status": "ok",
        "tasks": {tid: s.to_dict() for tid, s in visible.items()},
        "total": len(visible),
    }

@app.get("/api/upgrade-data", tags=["Gear"])
async def get_upgrade_data():
    """Season-aware gear-upgrade data (track ladders, ascension, crest ids).

    **Tags:** Gear
    **Note:** The web UI renders upgrade dropdowns from this; one entry per
    season so old exports keep resolving. See ``src/core/upgrade_data.py``.
    """
    from src.core.upgrade_data import season_payload
    return season_payload()


@app.get("/api/config", tags=["System"])
async def get_config():
    """Retrieve the current configuration from ``config.json``.

    **Tags:** System
    **Note:** Intended for internal use by the web UI; not a typed API response.
    """
    from src.cli.generate_input import load_config
    return load_config("config.json")

@app.post("/api/wowhead-upgrades", response_model=WowheadUpgradesResponse, tags=["Gear"])
async def get_wowhead_upgrades(payload: WowheadUpgradesRequest):
    """Look up gear upgrade paths (track/rank/item-level) from Wowhead XML for every item in *items_by_slot*.

    **Tags:** Gear
    **Request Model:** ``WowheadUpgradesRequest``
    **Response Model:** ``WowheadUpgradesResponse``

    **Example payload:**
    ```json
    {"items_by_slot": {"main_hand": ["id=198426,bonus_id=3170/3171"]}}
    ```
    """
    items_by_slot = payload.items_by_slot or {}
    if not isinstance(items_by_slot, dict):
        raise HTTPException(status_code=400, detail="items_by_slot must be an object")

    unique_items = []
    seen = set()
    for items in items_by_slot.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, str) or item in seen or not wowhead_xml_url(item):
                continue
            seen.add(item)
            unique_items.append(item)

    if len(unique_items) > 80:
        raise HTTPException(status_code=400, detail="Too many items for Wowhead lookup")

    results = {}
    errors = []

    async def lookup(item):
        try:
            return item, await fetch_wowhead_upgrade(item)
        except Exception as exc:
            logger.warning("Wowhead lookup failed for %s: %s", item, exc)
            return item, None

    looked_up = dict(await asyncio.gather(*(lookup(item) for item in unique_items))) if unique_items else {}
    for slot, items in items_by_slot.items():
        if not isinstance(items, list):
            continue
        for item in items:
            upgrade = looked_up.get(item)
            if not upgrade:
                continue
            results.setdefault(slot, {})[item] = upgrade

    return {"status": "success", "gear_upgrades": results, "errors": errors}

@app.post("/api/parse-addon", response_model=ParseAddonResponse, tags=["Addons"])
async def parse_addon_text(request: Request, payload: ParseAddonRequest, current_user: str = Depends(require_session)):
    """Parse SimulationCraft addon text into structured character data.

    **Tags:** Addons
    **Request Model:** ``ParseAddonRequest``
    **Response Model:** ``ParseAddonResponse``

    Returns the base profile (everything before ``### Gear from Bags``),
    equipped gear, available items per slot, item name comments, and
    character name / class.  ``item_upgrades`` carries per-item data parsed
    from the addon's ``# upgrade_levels=`` debug comment (keyed by the same
    item strings as ``item_names``); it is empty for exports without it.
    ``warnings`` carries soft WoW: Forever signals that do not block parsing.
    Exports with explicit WoW: Forever markers are rejected with HTTP 400.
    Text without a class line (not a SimC export at all) is rejected with
    HTTP 400 "No valid SimC export found".
    """
    lines = payload.addon_text.split('\n')
    if is_forever_export(lines):
        raise HTTPException(status_code=400, detail=FOREVER_EXPORT_MESSAGE)
    warnings = forever_export_warnings(lines)
    embedded = count_embedded_copies(lines)
    if embedded:
        # TG3-D2: re-uploaded app output carries copy= blocks from the
        # previous generation; parse_addon_lines now drops them from the
        # baseline (their gear still lands in the slot groups).
        warnings = warnings + [
            f"The uploaded profile carries {embedded} embedded copy "
            f"block{'' if embedded == 1 else 's'} from a previous generation. "
            "They are not simulated as-is and do not change your equipped "
            "baseline; their items are available in the slot choices — "
            "select the ones you want to compare."
        ]
    base_profile, equipped_gear, items_by_slot, item_names, char_name, char_class, item_upgrades = parse_addon_lines(lines)
    if char_class == "Unknown":
        # t_0cb6af81 (E2E-9/LIFE-8): every real /simc export starts with a
        # class line; without one the parse is an Unknown/Unknown dead end.
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid SimC export found. Paste the full text from the "
                'in-game /simc export window (it starts with a line like '
                'paladin="Name").'
            ),
        )
    # t_b3b78acd: remember where this user's character came from so the
    # eventual run_history row can say "addon".
    run_meta_by_user.setdefault(_resolved_user_id(request, current_user), {}).update(
        {"source": "addon", "char_name": char_name}
    )
    return {
        "base_profile": base_profile.rstrip("\n"),
        "equipped_gear": equipped_gear,
        "items_by_slot": items_by_slot,
        "item_names": item_names,
        "char_name": char_name,
        "char_class": char_class,
        "item_upgrades": item_upgrades,
        "warnings": warnings,
    }

@app.post("/api/armory-load", response_model=ArmoryLoadResponse, tags=["Addons"])
async def armory_load_character(request: Request, payload: ArmoryLoadRequest, current_user: str = Depends(require_session)):
    """Load a character + equipped gear from the WoW Armory (no addon export).

    **Tags:** Addons
    **Request Model:** ``ArmoryLoadRequest``
    **Response Model:** ``ArmoryLoadResponse``

    Accepts either a full Armory profile ``url`` (worldsoul or legacy
    battle.net form) or ``name`` + ``realm`` (``name`` may carry the
    combined ``Name-Realm`` / ``Name, Realm`` form), with ``region``
    defaulting to ``eu``.  The ``model.json`` document is fetched
    **server-side** (never from the browser), cached for 10 minutes per
    region/realm/name, and parsed into exactly the shape
    ``/api/parse-addon`` returns so the frontend can treat both sources
    identically.  Cosmetic shirt/tabard slots are dropped; item, bonus and
    enchant ids go straight into SimC item strings.

    Unknown characters, wrong regions and unreachable upstreams map to
    clean 404/502/429 responses with a human-readable ``detail``.
    """
    try:
        region, realm_slug, name = parse_armory_input(
            url=payload.url,
            name=payload.name,
            realm=payload.realm,
            region=payload.region,
        )
    except ArmoryInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        model = await armory_source.fetch_armory_model(region, realm_slug, name)
    except ArmoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ArmoryRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ArmoryUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ArmoryError as exc:
        logger.warning("Armory load failed for %s/%s: %s", region, realm_slug, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        parsed = parse_armory_model(model)
    except ArmoryInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ArmoryError as exc:
        logger.warning("Armory payload unusable for %s/%s: %s", region, realm_slug, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "Loaded %s from Armory %s/%s (%d slots)",
        parsed["char_name"], region, realm_slug, len(parsed["equipped_gear"]),
    )
    # t_b3b78acd: Armory is the only source that knows region/realm/spec.
    run_meta_by_user.setdefault(_resolved_user_id(request, current_user), {}).update(
        {
            "source": "armory",
            "char_name": parsed["char_name"],
            "region": region,
            "realm_slug": realm_slug,
            "spec": parsed.get("char_spec") or None,
        }
    )
    return parsed


@app.post("/api/generate-simc", response_model=GenerateSimcResponse, tags=["Profiles"])
async def generate_simc(request: Request, payload: GenerateSimcRequest, current_user: str = Depends(require_session)):
    """Generate a SimulationCraft profile with item variations based on the selected gear.

    **Tags:** Profiles
    **Request Model:** ``GenerateSimcRequest``
    **Response Model:** ``GenerateSimcResponse``

    Applies enchantments, gems, item-level overrides, midnight-track upgrades,
    and voidforge modifiers to build a full set of simc profiles (one per
    gear combination).  Writes the result to ``inputs/<input_id>.simc``.
    """
    fight_style = payload.fight_style or FIGHT_STYLE_SINGLE_BOSS
    if fight_style not in FIGHT_STYLE_DIRECTIVES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown fight_style '{fight_style}'; expected one of {sorted(FIGHT_STYLE_DIRECTIVES)}",
        )
    # Ruling E1: mode validation lives OUTSIDE the broad try below (its
    # HTTPException would otherwise be flattened into a 500).
    mode = payload.mode
    if mode not in TG_GENERATION_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown mode '{mode}'; expected one of {list(TG_GENERATION_MODES)}",
        )
    # t_b3b78acd: snapshot what this run is about for the run_history row.
    # ``source`` keeps whatever the load step recorded (addon/armory); plain
    # paste-in profiles with no load step default to "addon".
    _gen_meta = run_meta_by_user.setdefault(
        _resolved_user_id(request, current_user), {}
    )
    _gen_meta.update(
        {
            "fighting_style": fight_style,
            "char_name": payload.char_name,
            "spec": _extract_spec(payload.base_profile) or _gen_meta.get("spec"),
        }
    )
    _gen_meta.setdefault("source", "addon")
    try:
        from src.cli.generate_input import (
            apply_gear_upgrade,
            apply_item_level,
            build_combination_copies,
            canonical_item,
            generate_variations,
            load_config,
        )
        from src.core.upgrade_data import detect_season, get_season

        def _payload_ilvls(req):
            levels = []
            for slot_levels in (req.item_levels or {}).values():
                if isinstance(slot_levels, dict):
                    levels.extend(v for v in slot_levels.values() if isinstance(v, int))
            for gear in list(req.equipped_gear.values()) + [
                item for items in (req.selected_items or {}).values() for item in items
            ]:
                match = re.search(r"ilevel=(\d+)", str(gear))
                if match:
                    levels.append(int(match.group(1)))
            return levels

        season = (
            get_season(payload.upgrade_season)
            if payload.upgrade_season
            else detect_season(_payload_ilvls(payload))
        )
        config = load_config("config.json")
        if payload.selected_enchants:
            config["enchantments"] = payload.selected_enchants
        selected_gems = payload.selected_gems or []
        selected_meta_gems = set(payload.selected_meta_gems or [])
        configured_meta_gems = (
            config.get("gems", {}).get("meta", [])
            if isinstance(config.get("gems"), dict)
            else []
        )
        configured_meta_ids = {
            gem["id"] if isinstance(gem, dict) else gem for gem in configured_meta_gems
        }
        config["gems"] = {
            "meta": list(selected_meta_gems or (set(selected_gems) & configured_meta_ids)),
            "standard": [gem for gem in selected_gems if gem not in configured_meta_ids],
        }

        items_by_slot = payload.selected_items
        char_name = payload.char_name
        equipped_gear = payload.equipped_gear
        item_levels = payload.item_levels or {}
        gear_upgrades = payload.gear_upgrades or {}
        voidforged_items = payload.voidforged_items or {}

        def apply_level_override(slot, item, baseline=False):
            if not item:
                return item
            slot_levels = item_levels.get(slot, {}) if isinstance(item_levels, dict) else {}
            if not isinstance(slot_levels, dict):
                slot_levels = {}
            slot_upgrades = gear_upgrades.get(slot, {}) if isinstance(gear_upgrades, dict) else {}
            if not isinstance(slot_upgrades, dict):
                slot_upgrades = {}
            slot_voidforged = voidforged_items.get(slot, {}) if isinstance(voidforged_items, dict) else {}
            if not isinstance(slot_voidforged, dict):
                slot_voidforged = {}
            voidforged = bool(slot_voidforged.get(item))
            upgrade = slot_upgrades.get(item)
            # Entries the user explicitly chose (marked user_selected by the
            # UI) belong to the candidate copies only; the baseline must stay
            # the character's CURRENT gear, otherwise upgrading an item would
            # move the baseline with it and no diff could ever be generated.
            # Unmarked entries are inferred-current grades (name/level
            # inference, export rank 0, Wowhead hydration) and legitimately
            # describe the baseline too.
            if baseline and isinstance(upgrade, dict) and upgrade.get("user_selected"):
                upgrade = None
                voidforged = False
            if upgrade:
                return apply_gear_upgrade(item, upgrade, slot=slot, voidforged=voidforged, season=season)
            level = slot_levels.get(item)
            return apply_item_level(item, level, slot=slot, voidforged=voidforged, season=season)

        items_by_slot = {
            slot: [apply_level_override(slot, item) for item in items]
            for slot, items in items_by_slot.items()
        }
        equipped_gear = {
            slot: apply_level_override(
                "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot,
                details,
                baseline=True,
            )
            for slot, details in equipped_gear.items()
        }
        extra_sockets = payload.extra_sockets or {}

        # TG3-D2: copy= blocks carried in the caller's base profile must not
        # reach the output — SimC would bind the baseline gear block appended
        # below to the last clone instead of the character (last-actor
        # semantics), so the real actor simulates gearless.
        base_profile, embedded_copies = strip_embedded_copies(payload.base_profile)
        profile_content = base_profile + "\n"

        # Fighting-style overrides go after the base profile so they win over
        # any duration/time_to_die the addon export carried, and before the
        # copy blocks so every candidate profile inherits them.
        if FIGHT_STYLE_DIRECTIVES[fight_style]:
            profile_content += FIGHT_STYLE_DIRECTIVES[fight_style] + "\n"

        # Baseline gear
        for slot, details in equipped_gear.items():
            if details.startswith("id=") or details.startswith("bonus_id="):
                details = "," + details
            profile_content += f"{slot}={details}\n"

        profile_content += "\n"
        count = 0
        work_estimate_minutes = None

        if mode == MODE_COMBINATIONS:
            copy_blocks, count = build_combination_copies(
                items_by_slot, config, equipped_gear, char_name, extra_sockets=extra_sockets)
            # Budget check before any file write: over-cap requests neither
            # create an inputs/ file nor touch generated_inputs_by_user.
            # TG3-D2: embedded copies from the uploaded profile count toward
            # the budget even though strip_embedded_copies drops them from
            # the dispatch (an over-cap upload needs honest re-selection).
            if count + embedded_copies > TG_MAX_COMBINATIONS:
                embedded_part = (
                    f" + {embedded_copies} embedded copies from the uploaded profile"
                    if embedded_copies else ""
                )
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Combination budget exceeded: {count} combinations{embedded_part} "
                        f"(budget {TG_MAX_COMBINATIONS}). Deselect items or enchants, "
                        "or switch back to 'one swap at a time'."
                    ),
                )
            work_estimate_minutes = round(
                count * TG_STAGE1_ITERATIONS_CAP / TG_WORK_ESTIMATE_ITERS_PER_SEC / 60, 1)
            profile_content += "".join(copy_blocks)
        else:
            def profile_signature(override_slot: Optional[str] = None, override_item: Optional[str] = None):
                """Return a stable identity for the baseline or one single-slot override."""
                profile = {
                    slot: canonical_item(item)
                    for slot, item in equipped_gear.items()
                    if item
                }
                if override_slot and override_item:
                    profile[override_slot] = canonical_item(override_item)
                return tuple(sorted(profile.items()))

            def is_equipped_variation(slot: str, variation: str) -> bool:
                if slot == "finger":
                    equipped = [equipped_gear.get("finger1"), equipped_gear.get("finger2")]
                elif slot == "trinket":
                    equipped = [equipped_gear.get("trinket1"), equipped_gear.get("trinket2")]
                else:
                    equipped = [equipped_gear.get(slot)]
                return canonical_item(variation) in {canonical_item(item) for item in equipped if item}

            all_slots = set(items_by_slot.keys()) | set(config["enchantments"].keys())
            if payload.selected_gems:
                gem_slots = {slot for slot, items in items_by_slot.items() if any("gem_id=" in item for item in items)}
                gem_slots |= {slot for slot, enabled in extra_sockets.items() if enabled}
                all_slots |= gem_slots

            seen_profiles = {profile_signature()}
            for slot in sorted(all_slots):
                equipped_key = "finger1" if slot == "finger" else "trinket1" if slot == "trinket" else slot
                item_list = items_by_slot.get(slot)

                if not item_list:
                    if slot == "finger": item_list = [equipped_gear.get("finger1"), equipped_gear.get("finger2")]
                    elif slot == "trinket": item_list = [equipped_gear.get("trinket1"), equipped_gear.get("trinket2")]
                    else: item_list = [equipped_gear.get(slot)]

                item_list = [it for it in item_list if it]
                if not item_list: continue

                variations = generate_variations(item_list, slot, config, extra_sockets=extra_sockets)
                for var in variations:
                    # The base actor already represents equipped gear. Do not create
                    # fake candidates that simply reapply an unchanged slot.
                    if is_equipped_variation(slot, var):
                        continue
                    signature = profile_signature(equipped_key, var)
                    if signature in seen_profiles:
                        continue
                    seen_profiles.add(signature)
                    if var.startswith("id=") or var.startswith("bonus_id="):
                        var = "," + var
                    profile_content += f'copy="{char_name}_{slot}_{count},{char_name}"\n{equipped_key}={var}\n\n'
                    count += 1

        input_id = str(uuid.uuid4())[:12]
        file_path = os.path.join(INPUTS_DIR, f"{input_id}.simc")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(profile_content)

        # Preserve the legacy single-file path for existing CLI/tests/manual workflows.
        with open("char_simc_addon.txt", "w", encoding="utf-8") as f:
            f.write(profile_content)

        user_id = _input_bucket(request, current_user)
        record = {"input_id": input_id, "file_path": file_path, "input_url": f"/inputs/{input_id}.simc"}
        # t_2f386596: no global "latest" key in the per-user map and no fake
        # "latest" user_id row — SEC-8 (t_ff260cdb) removed the global latest
        # variable entirely.
        generated_inputs_by_user[user_id] = record
        input_set(user_id, record)

        # The base actor is always a valid current-gear simulation, even if no
        # alternate item profiles were generated. Report the true candidate
        # count (0 allowed) so the UI can label a baseline-only run honestly
        # and sim_helper can take its baseline path (t_4485565b).
        return {
            "status": "success",
            "file_path": file_path,
            "input_id": input_id,
            "input_url": record["input_url"],
            "combinations": count,
            "mode": mode,
            "work_estimate_minutes": work_estimate_minutes,
            "embedded_copies": embedded_copies,
        }
    except HTTPException:
        # Ruling E1: inner HTTPExceptions (e.g. the budget 422) must not be
        # flattened into 500s by the broad handler below.
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/update-simc', response_model=UpdateSimcResponse, tags=['Admin'])
async def update_simc(request: Request, _: str = Depends(require_session)):
    """Request a SimulationCraft engine update on an idle worker.

    **Tags:** Admin
    **Authentication:** Requires a logged-in session **and** the ``X-Admin-Token``
    header when ``ADMIN_TOKEN`` is configured (query-param fallback is dev-mode only).
    **Response Model:** ``UpdateSimcResponse``
    """
    require_admin(request)
    worker_id = manager.get_idle_worker()
    if not worker_id: raise HTTPException(status_code=503, detail="No idle workers")
    task_id = "upd-" + str(uuid.uuid4())[:8]
    manager.task_queues[task_id] = set()
    await manager.send_task(worker_id, {"type": "update", "task_id": task_id})
    return {"status": "success", "task_id": task_id}

@app.get("/api/update-simc/stream/{task_id}", tags=["Admin"])
async def stream_update_simc(task_id: str, user_id: str = Depends(require_session)):
    """Stream Server-Sent Events for the ``/api/update-simc`` task identified by *task_id*.

    **Tags:** Admin
    **Response Type:** ``text/event-stream``
    """
    if task_id not in manager.task_queues:
        raise HTTPException(status_code=404, detail="Task not found")
    # t_2f386596 (LIFE-4 scope add): same ownership gate as the sim stream.
    # shortcut: update tasks carry no owner record (recording one would make
    # the done handler write a run_history row for an engine update), so this
    # passes until update tasks get attribution; ids are unguessable and the
    # log holds no user data.
    if not _task_access_ok(task_id, user_id):
        raise HTTPException(status_code=404, detail="Task not found")

    async def update_event_generator():
        # LIFE-4 (t_5d6903e4): per-viewer subscriber queue; a disconnect only
        # removes its own subscription. The task entry is freed by the
        # worker-WS done handler.
        # shortcut: worker dying mid-update without done leaks the entry
        # until master restart; upgrade with a TTL sweeper if it shows up.
        queue: asyncio.Queue = asyncio.Queue()
        manager.task_queues.setdefault(task_id, set()).add(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=5.0)
                    if data["type"] == "log":
                        yield f"data: {json.dumps({'type': 'log', 'text': data['text']})}\n\n"
                    elif data["type"] == "done":
                        yield f"data: {json.dumps({'type': 'exit', 'code': data['code']})}\n\n"
                        break
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                except Exception:
                    break
        finally:
            subs = manager.task_queues.get(task_id)
            if subs is not None: subs.discard(queue)

    return StreamingResponse(update_event_generator(), media_type="text/event-stream")

@app.post("/api/stop-simulation", response_model=StopSimulationResponse, tags=["Admin"])
async def stop_simulation(request: Request):
    """Stop all active simulations. Requires admin authentication.

    **Tags:** Admin
    **Authentication:** Requires ``X-Admin-Token`` header (query-param fallback is dev-mode only).
    **Response Model:** ``StopSimulationResponse``
    """
    require_admin(request)
    stopped = False
    for wid, worker in manager.active_workers.items():
        if worker.status == "Busy" and worker.current_task:
            await worker.ws.send_json({"type": "stop", "task_id": worker.current_task})
            stopped = True
    return {"status": "success" if stopped else "error", "message": "Stopped all simulations" if stopped else "No active simulations"}

@app.post("/api/shutdown", response_model=ShutdownResponse, tags=["Admin"])
async def shutdown(request: Request):
    """Shut down the master server. Requires admin authentication.

    **Tags:** Admin
    **Authentication:** Requires ``X-Admin-Token`` header (query-param fallback is dev-mode only).
    **Response Model:** ``ShutdownResponse``
    """
    require_admin(request)
    logger.info("Shutdown requested...")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting down"}

def _done_event(task_id: str, data: Dict[str, Any]) -> str:
    # LIFE-2 (t_2c718ca6): the run_history row is written by the worker-WS
    # done handler — this generator only exists while a browser is watching
    # the stream, so hooking here lost the row when the master restarted
    # mid-run. t_a0bb3a07 (LIFE-1): a user Stop is reported as stopped, not
    # as a failed simulation.
    if data.get("stopped"):
        payload = {"type": "error", "text": "Simulation stopped."}
    elif data.get("code") == 0:
        payload = {"type": "done", "text": "Simulation finished successfully!", "report_file": data.get("report_file"), "task_id": task_id}
    else:
        err = data.get("error") or "the SimC process exited with a non-zero code — see the log above"
        payload = {"type": "error", "text": f"Simulation failed: {err}"}
    return f"data: {json.dumps(payload)}\n\n"


async def simulation_event_generator(task_id: str, worker_id: str, queue: Optional[asyncio.Queue] = None):
    # LIFE-4 (t_5d6903e4): one subscriber queue per connected viewer; a
    # disconnect removes only its own subscription. The task entry is freed
    # by the worker-WS done handler (the run completes with or without
    # viewers); this generator pops it only when the worker is already gone,
    # so no done can arrive. task_meta_map stays until _record_run_history
    # consumes it — popping it here lost the history row's metadata on
    # refresh.
    if task_id not in manager.task_queues and task_id in task_done_map:
        # Viewer joined after the run ended (fast run, or reconnect after a
        # refresh): replay the buffered terminal event instead of hanging.
        yield _done_event(task_id, task_done_map[task_id])
        return
    if queue is None: queue = asyncio.Queue()
    manager.task_queues.setdefault(task_id, set()).add(queue)
    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=5.0)
                if data["type"] == "log":
                    yield f"data: {json.dumps({'type': 'log', 'text': data['text']})}\n\n"
                elif data["type"] == "log_batch":
                    yield f"data: {json.dumps({'type': 'log_batch', 'lines': data['lines']})}\n\n"
                elif data["type"] == "task_status_update":
                    yield f"data: {json.dumps({'type': 'task_status_update', 'task_id': data['task_id'], 'status': data['status']})}\n\n"
                elif data["type"] == "done":
                    yield _done_event(task_id, data)
                    break
            except asyncio.TimeoutError:
                # t_acd39188: after a master restart the browser's worker_id
                # is stale — the task is alive if any current worker still
                # runs it (the resume handler re-attached it to a new id).
                if worker_id not in manager.active_workers and not any(
                    w.current_task == task_id for w in manager.active_workers.values()
                ):
                    yield f"data: {json.dumps({'type': 'error', 'text': 'Worker connection lost mid-simulation.'})}\n\n"
                    break
                yield ": keep-alive\n\n"
    finally:
        subs = manager.task_queues.get(task_id)
        if subs is not None:
            subs.discard(queue)
            # t_acd39188: same stale-worker_id guard as the timeout branch —
            # a stale viewer disconnecting after a resume must not pop the
            # re-attached entry (the replayed done still has to land).
            if (not subs and worker_id not in manager.active_workers
                    and not any(w.current_task == task_id for w in manager.active_workers.values())):
                manager.task_queues.pop(task_id, None)

@app.post("/api/run-simulation", response_model=RunSimulationResponse, tags=["Simulation"])
async def run_simulation(request: Request, worker_id: Optional[str] = Query(None), input_id: Optional[str] = Query(None), current_user: str = Depends(require_session)):
    """Run a SimulationCraft simulation on an available worker.

    **Tags:** Simulation
    **Authentication:** Requires a logged-in session (``session_id`` cookie);
    unauthenticated callers get HTTP 401 — dev mode never bypasses this.
    **Query Parameters:**
      - ``worker_id``: Optional worker ID to target (auto-selected if omitted)
      - ``input_id``: Optional input file ID — must be the caller's own
        generated input (HTTP 403 otherwise, t_2f386596). Defaults to the
        caller's own latest generated input; HTTP 422 if the caller has none
        — never another user's input, SEC-6 t_2447fdbd)

    **Rate Limiting:** per-user cooldown of ``sim_cooldown_seconds`` seconds
    (default 300; runtime-configurable via ``POST /api/settings``).

    **Response Model:** ``RunSimulationResponse``
    """
    user_id = _input_bucket(request, current_user)
    now = time.time()
    # Cooldown state lives ONLY here (t_ef8682a4): ``user_sessions`` is set
    # when a simulation actually starts and is purged after
    # SIM_COOLDOWN_SECONDS by the enforcer. Login never writes it, so a
    # freshly logged-in user is never rate-limited.
    # LIFE-5 (t_c610c962): enforce the configured value, not a hardcoded 30s.
    # Read once so the check and the 429 message can't disagree mid-request.
    cooldown = SIM_COOLDOWN_SECONDS
    db_time = session_get(user_id)
    if db_time is not None and now - db_time < cooldown:
         raise HTTPException(status_code=429, detail=f"Rate limit: wait {int(cooldown - (now - db_time))}s")

    target_worker = worker_id if worker_id and worker_id in manager.active_workers and manager.active_workers[worker_id].status == "Idle" else manager.get_idle_worker()
    if not target_worker: raise HTTPException(status_code=503, detail="No idle workers available")

    # SEC-6 (t_2447fdbd): resolve the input BEFORE any state is consumed and
    # only from the caller's own record — the old global "latest" fallback let
    # one user run another user's generated profile.
    if input_id:
        validate_safe_id(input_id, "input id")
        # t_2f386596: an explicit input_id must be the caller's own generated
        # input. user_inputs keeps only the latest record per user, so "own"
        # means "matches the caller's record". Skipped when auth is disabled
        # (the kill switch is single-operator mode; legacy CLI/test flows pass
        # orphan ids nobody owns).
        if authentication_enabled():
            own = generated_inputs_by_user.get(user_id)
            if not own or own.get("input_id") != input_id:
                raise HTTPException(status_code=403, detail="Input does not belong to user")
        input_record = {"input_url": f"/inputs/{input_id}.simc"}
    else:
        input_record = generated_inputs_by_user.get(user_id)
    if not input_record:
        raise HTTPException(status_code=422, detail="No generated input for this user; generate a profile first or pass input_id")
    input_url = input_record["input_url"]

    logger.info(f"Starting sim for {user_id} on {target_worker}")
    user_last_sim_time[user_id] = now
    session_set(user_id, now)
    task_id = str(uuid.uuid4())[:8]
    manager.task_queues[task_id] = set()
    task_user_map[task_id] = user_id  # t_c968bf8d: owner of the report directory
    # t_b3b78acd: freeze the character metadata for this task; the done hook
    # consumes (and pops) it when writing the run_history row.
    task_meta_map[task_id] = dict(run_meta_by_user.get(user_id) or {})
    # LIFE-2 (t_2c718ca6): persist owner + meta so attribution and the history
    # row survive a master restart mid-run.
    task_owner_upsert(task_id, user_id, json.dumps(task_meta_map[task_id]))
    try:
        await manager.send_task(target_worker, {"type": "start", "task_id": task_id, "input_url": input_url})
        manager.active_workers[target_worker].status, manager.active_workers[target_worker].current_task, manager.active_workers[target_worker].user_id = "Busy", task_id, user_id
    except Exception:
        if task_id in manager.task_queues: del manager.task_queues[task_id]
        raise HTTPException(status_code=500, detail="Failed to communicate with worker")
    return {"status": "success", "task_id": task_id, "worker_id": target_worker}

@app.get("/api/simulation/stream/{task_id}", tags=["Simulation"])
async def stream_simulation(task_id: str, worker_id: str, user_id: str = Depends(require_session)):
    """Stream Server-Sent Events for the simulation identified by *task_id*.

    **Tags:** Simulation
    **Response Type:** ``text/event-stream``
    """
    if task_id not in manager.task_queues and task_id not in task_done_map: raise HTTPException(status_code=404)
    # t_2f386596 (LIFE-4 scope add): per-viewer queues are keyed by task_id
    # only — without this check any session could watch another user's run.
    if not _task_access_ok(task_id, user_id): raise HTTPException(status_code=404)
    return StreamingResponse(simulation_event_generator(task_id, worker_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

# --- SimC HTML report parsing -------------------------------------------------
# SimC nightly emits player headers as <h2 id="player1toggle" class="toggle"">
# — note the stray double-quote before '>' — while older builds emit
# <h2 class="toggle">. The FIRST EXPANDED section additionally carries
# class="toggle open"" (verified in a real single-actor nightly report: a
# baseline-only run otherwise parses back to just the pet). The split
# pattern tolerates all three. Headers whose tag continues after
# class="toggle..." (e.g. id="apm-summary-toggle", style=...) are not
# player sections and must not match.
_REPORT_SECTION_RE = re.compile(r'<h2[^>]+class="toggle(?: open)?""?>')
_REPORT_DPS_RE = re.compile(
    r'^\s*([^<]+?)\s*(?:&#160;|&nbsp;)?\s*:\s*(?:&#160;|&nbsp;)?\s*([\d,.]+)\s*dps',
    re.IGNORECASE,
)
_REPORT_NAME_TRAILER_RE = re.compile(r'(?:&#160;|&nbsp;|\s)+$')
_REPORT_SLOT_MAP = {"Head": "head", "Neck": "neck", "Shoulders": "shoulder", "Back": "back", "Chest": "chest", "Wrists": "wrist", "Hands": "hands", "Waist": "waist", "Legs": "legs", "Feet": "feet", "Finger 1": "finger1", "Finger 2": "finger2", "Trinket 1": "trinket1", "Trinket 2": "trinket2", "Main Hand": "main_hand", "Off Hand": "off_hand"}
# Nightly emits gear labels "Finger1"/"Trinket2" (no space) where older builds
# emitted "Finger 1" (D1 t_ebcd03f1); whitespace-and-case-insensitive lookup
# parses both report generations.
_REPORT_SLOT_BY_LABEL = {re.sub(r"\s+", "", k).lower(): v for k, v in _REPORT_SLOT_MAP.items()}


def parse_report_results(html_content: str) -> list:
    """Parse a SimC HTML report into [{name, dps, gear}] per player section.

    Tolerant of both the classic (<h2 class="toggle">) and nightly
    (<h2 id="playerNtoggle" class="toggle"">) header markup and of the
    &#160;/&nbsp; separators SimC emits around the ':' in the DPS line.
    Shared by /api/get-results and the run-history insert hook.
    """
    results = []
    sections = _REPORT_SECTION_RE.split(html_content)
    for section in sections[1:]:
        m = _REPORT_DPS_RE.match(section)
        if not m:
            continue
        name = _REPORT_NAME_TRAILER_RE.sub('', m.group(1)).strip()
        if name == "Raid":
            continue
        dps = int(float(m.group(2).replace(',', '')))
        # Nightly reports emit pet/utility profiles (e.g. Fluffy_Pillow) as
        # player sections with 0 dps; they are not real alternatives (E2E-7).
        if dps == 0:
            continue
        gear = {}
        gt_match = re.search(r'<div class="player-section gear">.*?<table[^>]*>(.*?)</table>', section, re.DOTALL)
        if gt_match:
            rows = re.finditer(r'<th[^>]*>\s*([^<]+)\s*</th>\s*<td[^>]*>\s*<a[^>]+href="([^"]+)"', gt_match.group(1), re.IGNORECASE)
            for r in rows:
                simc_slot = _REPORT_SLOT_BY_LABEL.get(re.sub(r"\s+", "", r.group(1)).lower())
                if simc_slot:
                    href = r.group(2)
                    id_match = re.search(r'item=([0-9]+)', href)
                    if id_match:
                        simc_str = f"id={id_match.group(1)}"
                        ench = re.search(r'ench=([0-9]+)', href)
                        if ench: simc_str += f",enchant_id={ench.group(1)}"
                        gems = re.search(r'gems=([0-9:]+)', href)
                        if gems: simc_str += f",gem_id={gems.group(1).replace(':', '/')}"
                        bonus = re.search(r'bonus=([0-9:]+)', href)
                        if bonus: simc_str += f",bonus_id={bonus.group(1).replace(':', '/')}"
                        gear[simc_slot] = simc_str
        results.append({"name": name, "dps": dps, "gear": gear})
    return results


_PLAYER_BLOCK_RE = re.compile(r"^Player: (\S+)")
_PLAYER_DPS_RE = re.compile(r"DPS=([\d.]+)[^ ]* DPS-Error=([\d.]+)/([\d.]+)%")


def parse_actor_precision(log_path: str) -> dict:
    """Per-actor ``mean`` / ``error_pct`` from a SimC stage log (D6, t_791b16f5).

    Streams the log: ``Player: <name> ...`` opens an actor block, the next
    ``DPS=<mean> ... DPS-Error=<abs>/<rel>%`` line closes it. Blocks echo the
    full APL, so a block whose summary never appears is skipped when the next
    ``Player:`` line arrives (defensive skip, same spirit as sim_helper's
    ``filter_best`` streaming loop). Missing/unreadable log -> ``{}`` (legacy
    runs ship no log; callers treat the fields as absent).
    """
    precision: dict = {}
    pending = None
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _PLAYER_BLOCK_RE.match(line)
                if m:
                    pending = m.group(1)
                    continue
                if pending is None:
                    continue
                m = _PLAYER_DPS_RE.search(line)
                if m:
                    precision[pending] = {"mean": float(m.group(1)),
                                          "error_pct": float(m.group(3))}
                    pending = None
    except OSError:
        return {}
    return precision


@app.get("/api/get-results", response_model=GetResultsResponse, tags=["Simulation"])
async def get_results(task_id: str = Query(default="latest"), user_id: str = Depends(require_session)):
    """Retrieve parsed simulation results (DPS per class, gear data) for a completed task.

    **Tags:** Simulation
    **Query Parameters:**
      - ``task_id``: Task ID, or ``"latest"`` for the caller's own most recent
        report (SEC-1b, t_a4ff7b5d). Defaults to "latest".

    **Response Model:** ``GetResultsResponse``
    """
    try:
        html_path = None
        if task_id == "latest":
            # SEC-1b (t_a4ff7b5d): the old REPORTS_DIR/* glob served the
            # globally newest report to any logged-in user — cross-user leak.
            own_reports = glob.glob(os.path.join(
                REPORTS_DIR, _user_report_dir(user_id), "*", "report_*.html"))
            if not own_reports: return {"status": "error", "message": "No reports found"}
            own_reports.sort(key=os.path.getmtime, reverse=True)
            html_path = own_reports[0]
        else:
            tmp_dir = _find_task_report_dir(task_id)
            if not tmp_dir or not os.path.exists(tmp_dir):
                return {"status": "error", "message": f"Task {task_id} results not found"}
            # t_2f386596: explicit task_id must belong to the caller (same
            # error shape as not-found — no existence oracle).
            if not _task_access_ok(task_id, user_id):
                return {"status": "error", "message": f"Task {task_id} results not found"}
            report_files = [f for f in os.listdir(tmp_dir) if f.startswith("report_") and f.endswith(".html")]
            if not report_files: return {"status": "error", "message": "No reports found"}
            report_files.sort(key=lambda x: os.path.getmtime(os.path.join(tmp_dir, x)), reverse=True)
            html_path = os.path.join(tmp_dir, report_files[0])

        with open(html_path, encoding='utf-8', errors='replace') as f: html_content = f.read()
        results = parse_report_results(html_content)
        # D6 (t_791b16f5): per-actor precision ships only in the stage-3 log
        # the worker added to artifacts.zip, extracted next to the report.
        # No log (legacy runs) -> no merge, response byte-compatible.
        precision = parse_actor_precision(os.path.join(os.path.dirname(html_path), "stage3.log"))
        if precision:
            for item in results:
                item["mean_error_pct"] = precision.get(item["name"], {}).get("error_pct")
        return {"status": "success", "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing results: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/report-url", tags=["Simulation"])
async def get_report_url(task_id: str = Query(...), user_id: str = Depends(require_session)):
    """Resolve the static URL of a run's HTML report (t_c968bf8d).

    Durable reports live under the owner's user directory
    (``/reports/<user_id>/<task_id>/report_*.html``), which the frontend
    cannot derive from ``task_id`` alone. Explicit task ids are ownership-
    checked (t_2f386596): a non-owner gets the same 404 as not-found.
    """
    from urllib.parse import quote

    task_dir = _find_task_report_dir(task_id)
    if not task_dir or not os.path.isdir(task_dir):
        raise HTTPException(status_code=404, detail="Report not found")
    if not _task_access_ok(task_id, user_id):
        raise HTTPException(status_code=404, detail="Report not found")
    report_files = [f for f in os.listdir(task_dir) if f.startswith("report_") and f.endswith(".html")]
    if not report_files:
        raise HTTPException(status_code=404, detail="Report not found")
    report_files.sort(key=lambda x: os.path.getmtime(os.path.join(task_dir, x)), reverse=True)
    rel = os.path.relpath(os.path.join(task_dir, report_files[0]), REPORTS_DIR)
    return {"status": "success", "url": "reports/" + "/".join(quote(part) for part in rel.split(os.sep))}


# ---------------------------------------------------------------------------
# run_history read API (t_d34ced81: /history page + per-run view)
# ---------------------------------------------------------------------------

def _history_report_url(report_path: Optional[str]) -> Optional[str]:
    """Resolve a stored ``report_path`` (relative to REPORTS_DIR) to a static
    URL, or ``None`` when absent or no longer on disk (retention prunes old
    run dirs). Exposure equals the ``/reports`` mount — no new surface."""
    if not report_path:
        return None
    from urllib.parse import quote

    abs_path = os.path.normpath(os.path.join(os.path.abspath(REPORTS_DIR), report_path))
    if not abs_path.startswith(os.path.abspath(REPORTS_DIR) + os.sep):
        return None  # stored path escaped the reports root — never serve it
    if not os.path.isfile(abs_path):
        return None
    rel = os.path.relpath(abs_path, REPORTS_DIR)
    # Relative "reports/..." URL: resolves under any path prefix (t_62ff8faa).
    return "reports/" + "/".join(quote(part) for part in rel.split(os.sep))


def _history_run_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """One run_history row plus the client-ready ``report_url`` (t_d34ced81)."""
    run = dict(row)
    run["report_url"] = _history_report_url(row.get("report_path"))
    return run


@app.get("/api/history", tags=["Simulation"])
async def get_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    current_user: str = Depends(require_session),
):
    """List the caller's stored runs, newest first (t_d34ced81).

    Anonymous visitors (kill-switch mode, ``ip_*`` identities) get an empty
    list: the write hook only records rows for registered users, so history
    is the account feature's read side.
    """
    user_id = _resolved_user_id(request, current_user)
    runs = [_history_run_view(r) for r in run_history_list(user_id, limit=limit)]
    return {"status": "success", "runs": runs}


@app.get("/api/history/{run_id}", tags=["Simulation"])
async def get_history_run(
    run_id: str,
    request: Request,
    current_user: str = Depends(require_session),
):
    """Per-run detail view data (t_d34ced81). Ownership is enforced in the
    query, so another user's ``run_id`` is indistinguishable from a miss."""
    user_id = _resolved_user_id(request, current_user)
    row = run_history_get(run_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "success", "run": _history_run_view(row)}


@app.get("/inputs/{file_name}")
async def get_input_file(file_name: str, _: str = Depends(require_session_or_cluster)):
    from fastapi.responses import FileResponse

    if file_name == "char_simc_addon.txt":
        file_path = _safe_child_path(os.path.abspath("."), file_name)
    elif file_name.endswith(".simc"):
        input_id = file_name[:-5]
        validate_safe_id(input_id, "input id")
        file_path = _safe_child_path(INPUTS_DIR, file_name)
    else:
        raise HTTPException(status_code=404)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404)

def _safe_child_path(parent_dir: str, child_name: str) -> str:
    return safe_child_path(parent_dir, child_name)


def _user_report_dir(user_id: str) -> str:
    """Sanitize a user_id into a safe per-user reports directory name (t_c968bf8d).

    Registered users get their uuid-hex id; anonymous uuid cookies pass through
    unchanged; the ``ip_<host>`` fallback (dots!) is flattened to ``ip_..._...``.
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", user_id or "") or "anonymous"


# ---------------------------------------------------------------------------
# run_history recording (t_b3b78acd)
# ---------------------------------------------------------------------------

_REPORT_SPEC_RE = re.compile(r"^\s*spec\s*=\s*([A-Za-z0-9_]+)", re.MULTILINE)

# LIFE-2 (t_2c718ca6): the row may now be offered twice for one task (the
# upload fallback and the WS done handler); process-lifetime marker, same
# lifetime as task_user_map.
_history_recorded_tasks: set = set()


def _resolved_user_id(request: Request, current_user: Optional[str]) -> str:
    """Same identity rule as run_simulation/generate_simc (t_b3b78acd)."""
    if current_user and current_user != "anonymous":
        return current_user
    host = request.client.host if request.client else "unknown"
    return request.cookies.get("user_id") or f"ip_{host}"


def _extract_spec(base_profile: str) -> Optional[str]:
    """Pull the SimC ``spec=`` directive out of a base profile, if present."""
    m = _REPORT_SPEC_RE.search(base_profile or "")
    return m.group(1) if m else None


def _record_run_history(task_id: str, status: str) -> None:
    """Insert a run_history row for a finished simulation (t_b3b78acd).

    Called from the worker-WS done handler and, after a master restart, from
    the artifacts upload fallback (LIFE-2, t_2c718ca6). Best-effort by design:
    a missing report, an FK violation (anonymous/ip user), or a read error
    must never break the caller — failures are logged and swallowed.
    ``top_dps`` reuses the t_fdd385ef report parser; ``report_path`` is stored
    relative to REPORTS_DIR (``<user_dir>/<task_id>/report_*.html``).
    """
    try:
        user_id = task_user_map.get(task_id)
        if not user_id or task_id in _history_recorded_tasks:
            return
        _history_recorded_tasks.add(task_id)
        meta = task_meta_map.pop(task_id, {}) or {}
        top_dps: Optional[int] = None
        report_rel: Optional[str] = None
        task_dir = _find_task_report_dir(task_id)
        if task_dir and os.path.isdir(task_dir):
            report_files = [
                f for f in os.listdir(task_dir)
                if f.startswith("report_") and f.endswith(".html")
            ]
            if report_files:
                report_files.sort(
                    key=lambda x: os.path.getmtime(os.path.join(task_dir, x)),
                    reverse=True,
                )
                report_path = os.path.join(task_dir, report_files[0])
                report_rel = os.path.relpath(report_path, REPORTS_DIR)
                try:
                    with open(report_path, encoding="utf-8", errors="replace") as f:
                        parsed = parse_report_results(f.read())
                    if parsed:
                        top_dps = max(r["dps"] for r in parsed)
                except OSError:
                    pass
        elif status == "success":
            user_dir = _user_report_dir(user_id)
            report_rel = os.path.join(user_dir, task_id, "report_<ts>.html")
        run_history_insert(
            {
                "run_id": uuid.uuid4().hex[:12],
                "user_id": user_id,
                "created_at": time.time(),
                "fighting_style": meta.get("fighting_style"),
                "spec": meta.get("spec"),
                "source": meta.get("source"),
                "char_name": meta.get("char_name"),
                "realm_slug": meta.get("realm_slug"),
                "region": meta.get("region"),
                "top_dps": top_dps,
                "report_path": report_rel,
                "status": status,
            }
        )
    except Exception as exc:  # noqa: BLE001 — history must never sink the stream
        logger.warning("run_history insert failed for task %s: %s", task_id, exc)


def _task_report_dir(user_dir: str, task_id: str) -> str:
    """REPORTS_DIR/<user_dir>/<task_id> with the same traversal checks as before."""
    return safe_task_dir(os.path.join(REPORTS_DIR, user_dir), task_id)


def _task_owner(task_id: str) -> Optional[str]:
    """Owner user_id of *task_id*, or None when unresolvable.

    Shared ownership-resolution helper (t_a4ff7b5d ownership family): checks
    the durable task map first, then falls back to the REPORTS_DIR path
    segment (``REPORTS_DIR/<owner>/<task_id>/``) for uploads whose owner was
    lost across a master restart. Callers compare against their own id
    (``_user_report_dir``-sanitized) and reject non-owners with 403/404.
    """
    owner = task_user_map.get(task_id)
    if owner:
        return owner
    for match in glob.glob(os.path.join(REPORTS_DIR, "*", task_id)):
        if os.path.isdir(match):
            return os.path.basename(os.path.dirname(match))
    return None


def _task_access_ok(task_id: str, claimant: str) -> bool:
    """True when *claimant* may read *task_id* (t_2f386596 ownership pass).

    Ownership is only meaningful when authentication is enabled — the
    AUTHENTICATION_ENABLED=false kill switch is single-operator mode. An
    unresolvable owner (update-simc tasks, attribution lost before LIFE-2)
    passes through; the caller's own existence gate still applies.
    """
    if not authentication_enabled():
        return True
    owner = _task_owner(task_id)
    return owner is None or _user_report_dir(owner) == _user_report_dir(claimant)


def _find_task_report_dir(task_id: str) -> Optional[str]:
    """Locate the report directory for *task_id* across user directories.

    Checks the owner's directory first via the shared ``_task_owner``
    resolution, then scans ``REPORTS_DIR/*/<task_id>`` — covers uploads whose
    owner was lost across a master restart. Returns None when the task has no
    directory yet.
    """
    validate_safe_id(task_id, "task id")
    owner = _task_owner(task_id)
    if owner:
        candidate = os.path.join(REPORTS_DIR, _user_report_dir(owner), task_id)
        if os.path.isdir(candidate):
            return candidate
    for match in glob.glob(os.path.join(REPORTS_DIR, "*", task_id)):
        if os.path.isdir(match):
            return match
    return None


def _prune_user_reports(user_dir: str, keep: Optional[int] = None) -> None:
    """Retention cap (t_c968bf8d): keep only the newest ``keep`` run dirs for a
    user (by mtime), deleting the oldest. Called on artifact insert (upload)."""
    import shutil

    keep = REPORT_RETENTION if keep is None else keep
    base = os.path.join(REPORTS_DIR, user_dir)
    try:
        entries = [os.path.join(base, name) for name in os.listdir(base)]
        entries = [p for p in entries if os.path.isdir(p)]
    except OSError:
        return
    if len(entries) <= keep:
        return

    def _mtime(p: str) -> float:
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    entries.sort(key=lambda p: (_mtime(p), p))
    for stale in entries[: len(entries) - keep]:
        shutil.rmtree(stale, ignore_errors=True)


def _extract_zip_safely(zip_path: str, dest_dir: str):
    import zipfile
    dest_real = os.path.realpath(dest_dir)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for member in zf.infolist():
            member_path = os.path.realpath(os.path.join(dest_real, member.filename))
            if os.path.commonpath([dest_real, member_path]) != dest_real:
                raise HTTPException(status_code=400, detail="Unsafe zip member path")
        zf.extractall(dest_real)


@app.post("/api/worker/upload-file", response_model=WorkerUploadFileResponse, tags=["Workers"])
async def worker_upload_file(
    request: Request,
    task_id: str,
    file_name: str,
    secret: Optional[str] = None,
    file: UploadFile = File(...),
):
    """Upload an artifact (e.g. ``artifacts.zip``) from a worker node to the task directory.

    **Tags:** Workers
    **Authentication:** ``X-Cluster-Secret`` header matching ``CLUSTER_SECRET``
    (audit MEDIUM-2 — the legacy ``secret`` query param is dev-mode only).
    **Response Model:** ``WorkerUploadFileResponse``
    """
    if not _cluster_secret_ok(request.headers.get("X-Cluster-Secret"), secret):
        raise HTTPException(status_code=403)
    user_dir = _user_report_dir(task_user_map.get(task_id, ""))
    dest_dir = _task_report_dir(user_dir, task_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = _safe_child_path(dest_dir, file_name)
    with open(dest_path, "wb") as f: f.write(await file.read())
    if file_name == "artifacts.zip":
        _extract_zip_safely(dest_path, dest_dir)
        # LIFE-2 (t_2c718ca6): master restarted mid-run — the worker's done
        # event is gone and this upload is the only completion signal left.
        # The live task queue is the discriminator: on the normal path it
        # still exists and the WS done handler records the row instead.
        # t_acd39188 (LIFE-10): the worker DOES replay done after a
        # reconnect; _record_run_history dedupes via _history_recorded_tasks,
        # so this fallback and the replayed done collapse to one row.
        if task_id not in manager.task_queues and task_id in task_user_map:
            has_report = any(
                f.startswith("report_") and f.endswith(".html")
                for f in os.listdir(dest_dir)
            )
            _record_run_history(task_id, "success" if has_report else "failed")
    # Retention cap (t_c968bf8d): prune this user's oldest runs beyond the cap.
    _prune_user_reports(user_dir)
    return {"status": "success"}

@app.websocket("/ws/worker")
async def worker_websocket(websocket: WebSocket, name: str, secret: Optional[str] = None):
    if not _cluster_secret_ok(websocket.headers.get("x-cluster-secret"), secret):
        await websocket.close(code=1008); return
    worker_id = await manager.connect(websocket, name)
    try:
        while True:
            data = await websocket.receive_json()
            if worker_id in manager.active_workers:
                manager.active_workers[worker_id].last_ping = time.time()
                if data["type"] == "ping": pass
                elif data["type"] == "task_status_update":
                    # Forward task status updates to SSE consumers
                    tid = data["task_id"]
                    task = data["status"]
                    # t_14e40e6c: mirror the worker-pushed status into the
                    # master's task_status_store — the store is per-process,
                    # this WS channel is the only writer that crosses the
                    # master/worker boundary, so /api/task-status stays empty
                    # on master without it.
                    ts = get_or_create_task_status(tid)
                    for field, value in task.items():
                        if field != "task_id" and hasattr(ts, field):
                            setattr(ts, field, value)
                    # Broadcast via all task queues that might have subscribers
                    for subs in manager.task_queues.values():
                        for queue in subs:
                            try:
                                await queue.put({"type": "task_status_update", "task_id": tid, "status": task})
                            except Exception:
                                pass
                elif data["type"] == "resume":
                    # t_acd39188 (LIFE-10): worker reconnected mid-task
                    # (master restart). Re-attach the task queue set so SSE
                    # works and the worker's replayed upload/done land
                    # attributed. Never overwrite an existing subscriber set
                    # (LIFE-4: task_queues is Dict[str, Set[Queue]]). The
                    # master never re-dispatches the sim — the worker replays
                    # its on-disk artifacts or reports the loss.
                    tid = data.get("task_id")
                    if tid and tid in task_user_map:
                        manager.task_queues.setdefault(tid, set())
                        w = manager.active_workers[worker_id]
                        w.status, w.current_task, w.user_id = "Busy", tid, task_user_map[tid]
                        logger.info(f"Worker {name} ({worker_id}) resumed task {tid} after reconnect.")
                elif data["type"] == "log" or data["type"] == "log_batch" or data["type"] == "done":
                    tid = data.get("task_id")
                    for queue in manager.task_queues.get(tid, ()): await queue.put(data)
                    if data["type"] == "done":
                        # LIFE-4 (t_5d6903e4): the queue entry lives for the
                        # run, not for the viewers — free it here at run end.
                        manager.task_queues.pop(tid, None)
                        _record_task_done(tid, data)
                        manager.active_workers[worker_id].status = "Idle"
                        # LIFE-2 (t_2c718ca6): history row recorded here, at the
                        # one done writer that crosses the master/worker boundary
                        # (t_14e40e6c) — works with no SSE consumer and after a
                        # master restart. t_a0bb3a07 (LIFE-1): a user Stop is
                        # reported as stopped, not as a failed simulation.
                        stopped = bool(data.get("stopped"))
                        _record_run_history(tid, "stopped" if stopped else ("success" if data.get("code") == 0 else "failed"))
    except WebSocketDisconnect: manager.disconnect(worker_id)
    except Exception as e: logger.error(f"WS error for {name}: {e}"); manager.disconnect(worker_id)

# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------
@app.get("/api/settings", response_model=SettingsResponse, tags=["Settings"])
async def get_settings():
    """Get current application settings.

    Sensitive fields (dev mode, ws_max_size) are stripped from the response
    (audit F2).

    **Tags:** Settings
    **Response Model:** ``SettingsResponse``
    """
    cors_origins_str = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    cors_enabled = bool(cors_origins_str.strip()) or os.environ.get("SIMC_HELPER_DEV_MODE") == "1"

    return {
        "master_url": os.environ.get("MASTER_URL", ""),
        "log_level": os.environ.get("LOG_LEVEL", "INFO"),
        "sim_cooldown_seconds": SIM_COOLDOWN_SECONDS,
        "cors_enabled": cors_enabled,
        "cors_allowed_origins": cors_origins_str,
    }


@app.post("/api/settings", response_model=SettingsResponse, tags=["Settings"])
async def update_settings(request: Request, payload: UpdateSettingsRequest):
    """Update application settings (runtime only - restart required for some changes).

    **Tags:** Settings
    **Authentication:** Requires ``X-Admin-Token`` header (audit F2 — this
    endpoint mutates process environment; the legacy ``admin_token`` query
    param is honoured only in dev mode, audit MEDIUM-2).
    **Request Model:** ``UpdateSettingsRequest``
    """
    require_admin(request)

    # Update CORS settings if changed
    if payload.cors_enabled:
        if payload.cors_allowed_origins:
            os.environ["CORS_ALLOWED_ORIGINS"] = payload.cors_allowed_origins
            logger.info("CORS enabled for origins: %s", payload.cors_allowed_origins)
        else:
            os.environ["CORS_ALLOWED_ORIGINS"] = '["*"]'
            logger.info("CORS enabled for all origins")
    else:
        os.environ["CORS_ALLOWED_ORIGINS"] = ""
        logger.info("CORS disabled")

    # NOTE: SIMC_HELPER_DEV_MODE is env-only and deliberately NOT settable
    # here anymore (audit F2).  Runtime toggling used to let any unauthenticated
    # caller disable auth redirects and open CORS to "*".

    # Update WebSocket max message size
    os.environ["WS_MAX_SIZE"] = str(payload.ws_max_size)

    # Update sim cooldown
    global SIM_COOLDOWN_SECONDS
    SIM_COOLDOWN_SECONDS = payload.sim_cooldown_seconds
    logger.info("Sim cooldown updated to %d seconds", payload.sim_cooldown_seconds)

    # Update log level
    if payload.log_level:
        os.environ["LOG_LEVEL"] = payload.log_level
        # Note: full log level reload requires restart

    logger.info("Settings updated successfully")
    return await get_settings()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    ssl_keyfile = os.environ.get("SSL_KEYFILE")
    ssl_certfile = os.environ.get("SSL_CERTFILE")
    if ssl_keyfile and ssl_certfile and os.path.exists(ssl_keyfile) and os.path.exists(ssl_certfile):
        uvicorn.run(app, host=get_bind_host(), port=port, ssl_keyfile=ssl_keyfile, ssl_certfile=ssl_certfile)
    else:
        uvicorn.run(app, host=get_bind_host(), port=port)
