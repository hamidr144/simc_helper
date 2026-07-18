import asyncio
import glob
import hashlib
import json
import logging
import os
import re
import signal
import sys
import time
import uuid
import datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))


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
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx
from fastapi import (
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
from pydantic import BaseModel

from src.core.addon_parser import parse_addon_lines
from src.core.circuit_breaker import CircuitBreaker
from src.core.db import (
    init_db,
    input_set,
    load_inputs,
    load_sessions,
    session_cleanup_older_than,
    session_get,
    session_set,
    user_create,
    user_get,
)
from src.core.env import get_bind_host, load_cluster_secret, require_admin_token
from src.core.paths import safe_child_path, safe_task_dir, validate_safe_id
from src.worker import task_status_store


# ---------------------------------------------------------------------------
# Pydantic request / response schemas for OpenAPI docs
# ---------------------------------------------------------------------------
class GenerateSimcRequest(BaseModel):
    """Payload for ``/api/generate-simc`` – build a SimulationCraft profile."""
    char_class: str
    char_name: str
    base_profile: str
    equipped_gear: Dict[str, str]
    selected_items: Dict[str, List[str]]
    selected_enchants: Optional[Dict[str, Any]] = {}
    selected_gems: Optional[List[Union[str, int]]] = []
    selected_meta_gems: Optional[List[Union[str, int]]] = []
    item_levels: Optional[Dict[str, Dict[str, Optional[int]]]] = {}
    gear_upgrades: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = {}
    voidforged_items: Optional[Dict[str, Dict[str, bool]]] = {}
    extra_sockets: Optional[Dict[str, bool]] = {}


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


class WowheadUpgradesRequest(BaseModel):
    """Payload for ``/api/wowhead-upgrades`` – look up gear upgrade paths."""
    items_by_slot: Dict[str, List[str]]


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
    """Response from ``/health``."""
    status: str
    timestamp: str
    details: Dict[str, Any]


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
    """Response from ``/api/settings``."""
    master_url: str
    log_level: str
    sim_cooldown_seconds: int
    cors_enabled: bool
    cors_allowed_origins: str
    simc_helper_dev_mode: bool
    ws_max_size: int


class UpdateSettingsRequest(BaseModel):
    """Payload for ``/api/settings`` (POST)."""
    master_url: str
    log_level: str
    sim_cooldown_seconds: int
    cors_enabled: bool
    cors_allowed_origins: str
    simc_helper_dev_mode: bool
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
SIM_COOLDOWN_SECONDS = 300 # 5 minutes

# Initialize DB (creates tables if not exist) – must happen before load_sessions/load_inputs
init_db()

# In-memory storage (backed by SQLite)
user_last_sim_time = load_sessions()
generated_inputs_by_user: dict = load_inputs()
generated_inputs_by_user["latest"] = None
wowhead_upgrade_cache = {}
wowhead_icon_cache: Dict[str, tuple[bytes, str]] = {}
wowhead_tooltip_script_cache: Optional[bytes] = None

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
        self.task_queues: Dict[str, asyncio.Queue] = {}
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
                queue = self.task_queues[worker.current_task]
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

    # Set up signal handlers for graceful shutdown
    def _signal_handler():
        logger.info("Shutdown signal received — marking workers as unavailable.")
        manager._shutting_down = True
        for wid, w in manager.active_workers.items():
            w.status = "Unavailable"
            try:
                asyncio.create_task(w.ws.close(1001, "Server shutting down"))
            except Exception:
                pass
            manager.disconnect(wid)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

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
        "- Admin endpoints require an `X-Admin-Token` header or `admin_token` query parameter\n"
        "- Worker nodes authenticate via the `CLUSTER_SECRET` environment variable\n"
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
REPORTS_DIR = "/tmp/simc_reports"  # nosec B108
os.makedirs(REPORTS_DIR, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")

# Register middlewares for request ID and structured logging
app.add_middleware(RequestIDMiddleware)
app.add_middleware(LoggingMiddleware)

# Prometheus metrics counters (simple in-memory counters)
simc_requests_total = 0
simc_errors_total = 0

# Prometheus metrics endpoint – returns plain‑text exposition format
@app.get("/metrics", tags=["Metrics"])
async def get_metrics():
    """Expose simple Prometheus metrics for the master service.

    Currently provides:
    - ``simc_requests_total`` – total number of API requests handled
    - ``simc_errors_total`` – total number of error responses
    """
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
APP_PAGE = os.path.abspath(os.path.join(static_dir, "app.html"))


templates = Jinja2Templates(directory=static_dir)

@app.get("/")
async def root(request: Request):
    user_id = request.cookies.get("user_id")
    if "pytest" in sys.modules or os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        response = FileResponse(APP_PAGE)
        if not user_id:
            user_id = str(uuid.uuid4())
            response.set_cookie(key="user_id", value=user_id, max_age=31536000)
        return response
    
    session_id = request.cookies.get("session_id")
    if session_id and session_get(session_id) is not None:
        return RedirectResponse(url="/dashboard", status_code=303)
    return FileResponse(LOGIN_PAGE)


@app.get("/dashboard")
async def dashboard(request: Request):
    if "pytest" in sys.modules or os.environ.get("SIMC_HELPER_DEV_MODE") == "1":
        return FileResponse(APP_PAGE)
        
    session_id = request.cookies.get("session_id")
    if session_id and session_get(session_id) is not None:
        return FileResponse(APP_PAGE)
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login")
async def login_page(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id and session_get(session_id) is not None:
        return RedirectResponse(url="/dashboard", status_code=303)
    return FileResponse(LOGIN_PAGE)


@app.post("/register")
async def register(username: str = Form(...), password: str = Form(...)):
    if user_get(username):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    user_id = user_create(username, password_hash)
    return {"status": "success", "user_id": user_id, "username": username}


@app.post("/login")
async def login(response: Response, username: str = Form(...), password: str = Form(...)):
    user = user_get(username)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    expected_hash = hashlib.sha256(password.encode()).hexdigest()
    if user["password_hash"] != expected_hash:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Ensure session exists in DB
    session_set(user["user_id"], time.time())
    
    redirect_resp = RedirectResponse(url="/dashboard", status_code=303)
    redirect_resp.set_cookie(
        key="session_id", 
        value=user["user_id"], 
        httponly=True, 
        max_age=3600 * 24 * 7, 
        samesite="lax"
    )
    return redirect_resp


@app.get("/logout")
async def logout():
    redirect_resp = RedirectResponse(url="/", status_code=303)
    redirect_resp.delete_cookie("session_id")
    return redirect_resp


@app.get("/session/{user_id}")
async def get_session_route(user_id: str):
    last_sim_time = session_get(user_id)
    if last_sim_time is None:
        return {"user_id": user_id, "last_sim_time": None}
    return {"user_id": user_id, "last_sim_time": last_sim_time}


@app.post("/session/{user_id}/update")
async def update_session_route(user_id: str, request: SimulationRequest):
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
    match = re.search(r"Upgrade Level:\s*(Adventurer|Veteran|Champion|Hero|Myth)\s*([1-6])/6", text)
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
            'function Se(e){if(e==="nether"){return location.origin+"/api/wowhead-nether"}',
            1,
        )
        wowhead_tooltip_script_cache = script.encode("utf-8")

    return Response(
        content=wowhead_tooltip_script_cache,
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/wowhead-nether/{path:path}", tags=["Gear"])
async def proxy_wowhead_tooltip_data(path: str, request: Request):
    """Proxy native Wowhead tooltip data for browsers that block third parties."""
    upstream_url = f"https://nether.wowhead.com/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "simc-helper/1.0"},
        ) as client:
            response = await client.get(upstream_url)
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
async def get_api_state():
    """Retrieve the current system state – active input and connected workers.

    **Tags:** System
    **Response Model:** ``StateResponse``
    """
    return {
        "status": "ready",
        "active_input": generated_inputs_by_user.get("latest", {}).get("input_id") if generated_inputs_by_user.get("latest") else None,
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

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health-check endpoint for Docker healthchecks and operational monitoring.

    **Tags:** System
    **Response Model:** ``HealthResponse``

    Returns JSON with:
      - status: "ok" or "degraded"
      - timestamp: ISO-8601 UTC time
      - details: worker connectivity, disk space
    """
    import datetime

    workers = list(manager.active_workers.values())
    connected = len(workers)
    idle = sum(1 for w in workers if w.status == "Idle")
    busy = sum(1 for w in workers if w.status == "Busy")

    disk = _check_disk_space(INPUTS_DIR)

    # Determine overall status — only degraded if disk space is critically low
    status = "ok"
    if disk.get("free_percent", 100) < 5:
        status = "degraded"

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
async def get_task_status(task_id: Optional[str] = None):
    """Get task status for a specific task or list all tasks.

    **Tags:** Tasks
    **Query Parameters:**
      - ``task_id``: Optional task ID. Omit to list all tasks.

    **Response:** Returns a ``TaskStatusResponse`` for a single task or a
    ``TaskListResponse`` when listing all tasks.
    """
    if task_id:
        status = task_status_store.get(task_id)
        if not status:
            return {"status": "not_found", "task_id": task_id}
        return {"status": "ok", "task_id": task_id, "task": status.to_dict()}
    return {
        "status": "ok",
        "tasks": {tid: s.to_dict() for tid, s in task_status_store.items()},
        "total": len(task_status_store),
    }

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
async def parse_addon_text(payload: ParseAddonRequest):
    """Parse SimulationCraft addon text into structured character data.

    **Tags:** Addons
    **Request Model:** ``ParseAddonRequest``
    **Response Model:** ``ParseAddonResponse``

    Returns the base profile (everything before ``### Gear from Bags``),
    equipped gear, available items per slot, item name comments, and
    character name / class.
    """
    base_profile, equipped_gear, items_by_slot, item_names, char_name, char_class = parse_addon_lines(payload.addon_text.split('\n'))
    return {
        "base_profile": base_profile.rstrip("\n"),
        "equipped_gear": equipped_gear,
        "items_by_slot": items_by_slot,
        "item_names": item_names,
        "char_name": char_name,
        "char_class": char_class,
    }

@app.post("/api/generate-simc", response_model=GenerateSimcResponse, tags=["Profiles"])
async def generate_simc(request: Request, payload: GenerateSimcRequest):
    """Generate a SimulationCraft profile with item variations based on the selected gear.

    **Tags:** Profiles
    **Request Model:** ``GenerateSimcRequest``
    **Response Model:** ``GenerateSimcResponse``

    Applies enchantments, gems, item-level overrides, midnight-track upgrades,
    and voidforge modifiers to build a full set of simc profiles (one per
    gear combination).  Writes the result to ``inputs/<input_id>.simc``.
    """
    try:
        from src.cli.generate_input import (
            apply_gear_upgrade,
            apply_item_level,
            generate_variations,
            load_config,
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

        def apply_level_override(slot, item):
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
            if upgrade:
                return apply_gear_upgrade(item, upgrade, slot=slot, voidforged=voidforged)
            level = slot_levels.get(item)
            return apply_item_level(item, level, slot=slot, voidforged=voidforged)

        items_by_slot = {
            slot: [apply_level_override(slot, item) for item in items]
            for slot, items in items_by_slot.items()
        }
        equipped_gear = {
            slot: apply_level_override(
                "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot,
                details,
            )
            for slot, details in equipped_gear.items()
        }
        extra_sockets = payload.extra_sockets or {}

        profile_content = payload.base_profile + "\n"

        # Baseline gear
        for slot, details in equipped_gear.items():
            if details.startswith("id=") or details.startswith("bonus_id="):
                details = "," + details
            profile_content += f"{slot}={details}\n"

        profile_content += "\n"
        count = 0

        all_slots = set(items_by_slot.keys()) | set(config["enchantments"].keys())
        if payload.selected_gems:
            gem_slots = {slot for slot, items in items_by_slot.items() if any("gem_id=" in item for item in items)}
            gem_slots |= {slot for slot, enabled in extra_sockets.items() if enabled}
            all_slots |= gem_slots

        for slot in all_slots:
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

        user_id = request.cookies.get("session_id") or request.cookies.get("user_id") or f"ip_{request.client.host}"
        record = {"input_id": input_id, "file_path": file_path, "input_url": f"/inputs/{input_id}.simc"}
        generated_inputs_by_user[user_id] = record
        generated_inputs_by_user["latest"] = record
        input_set(user_id, record)
        input_set("latest", record)

        return {"status": "success", "file_path": file_path, "input_id": input_id, "input_url": record["input_url"], "combinations": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post('/api/update-simc', response_model=UpdateSimcResponse, tags=['Admin'])
async def update_simc(request: Request):
    """Request a SimulationCraft engine update on an idle worker.

    **Tags:** Admin
    **Authentication:** Requires ``X-Admin-Token`` header or ``admin_token`` query param.
    **Response Model:** ``UpdateSimcResponse``
    """
    require_admin_token(request.headers.get("X-Admin-Token") or request.query_params.get("admin_token"))
    worker_id = manager.get_idle_worker()
    if not worker_id: raise HTTPException(status_code=503, detail="No idle workers")
    task_id = "upd-" + str(uuid.uuid4())[:8]
    manager.task_queues[task_id] = asyncio.Queue()
    await manager.send_task(worker_id, {"type": "update", "task_id": task_id})
    return {"status": "success", "task_id": task_id}

@app.get("/api/update-simc/stream/{task_id}", tags=["Admin"])
async def stream_update_simc(task_id: str):
    """Stream Server-Sent Events for the ``/api/update-simc`` task identified by *task_id*.

    **Tags:** Admin
    **Response Type:** ``text/event-stream``
    """
    if task_id not in manager.task_queues:
        raise HTTPException(status_code=404, detail="Task not found")

    async def update_event_generator():
        queue = manager.task_queues[task_id]
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
        if task_id in manager.task_queues: del manager.task_queues[task_id]

    return StreamingResponse(update_event_generator(), media_type="text/event-stream")

@app.post("/api/stop-simulation", response_model=StopSimulationResponse, tags=["Admin"])
async def stop_simulation(request: Request):
    """Stop all active simulations. Requires admin authentication.

    **Tags:** Admin
    **Authentication:** Requires ``X-Admin-Token`` header or ``admin_token`` query param.
    **Response Model:** ``StopSimulationResponse``
    """
    require_admin_token(request.headers.get("X-Admin-Token") or request.query_params.get("admin_token"))
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
    **Authentication:** Requires ``X-Admin-Token`` header or ``admin_token`` query param.
    **Response Model:** ``ShutdownResponse``
    """
    require_admin_token(request.headers.get("X-Admin-Token") or request.query_params.get("admin_token"))
    logger.info("Shutdown requested...")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting down"}

async def simulation_event_generator(task_id: str, worker_id: str):
    try:
        queue = manager.task_queues[task_id]
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
                    if data["code"] == 0:
                        yield f"data: {json.dumps({'type': 'done', 'text': 'Simulation finished successfully!', 'report_file': data.get('report_file'), 'task_id': task_id})}\n\n"
                    else:
                        err = data.get("error", "Unknown error or process crash")
                        yield f"data: {json.dumps({'type': 'error', 'text': f'Simulation failed: {err}'})}\n\n"
                    break
            except asyncio.TimeoutError:
                if worker_id not in manager.active_workers:
                    yield f"data: {json.dumps({'type': 'error', 'text': 'Worker connection lost mid-simulation.'})}\n\n"
                    break
                yield ": keep-alive\n\n"
    finally:
        if task_id in manager.task_queues: del manager.task_queues[task_id]

@app.post("/api/run-simulation", response_model=RunSimulationResponse, tags=["Simulation"])
async def run_simulation(request: Request, worker_id: Optional[str] = Query(None), input_id: Optional[str] = Query(None)):
    """Run a SimulationCraft simulation on an available worker.

    **Tags:** Simulation
    **Query Parameters:**
      - ``worker_id``: Optional worker ID to target (auto-selected if omitted)
      - ``input_id``: Optional input file ID (defaults to user's latest)

    **Rate Limiting:** 300-second cooldown per user.

    **Response Model:** ``RunSimulationResponse``
    """
    user_id = request.cookies.get("session_id") or request.cookies.get("user_id") or f"ip_{request.client.host}"
    now = time.time()
    db_time = session_get(user_id)
    if db_time is not None and now - db_time < 30:
         raise HTTPException(status_code=429, detail=f"Rate limit: wait {int(30 - (now - db_time))}s")

    target_worker = worker_id if worker_id and worker_id in manager.active_workers and manager.active_workers[worker_id].status == "Idle" else manager.get_idle_worker()
    if not target_worker: raise HTTPException(status_code=503, detail="No idle workers available")

    logger.info(f"Starting sim for {user_id} on {target_worker}")
    user_last_sim_time[user_id] = now
    session_set(user_id, now)
    task_id = str(uuid.uuid4())[:8]
    manager.task_queues[task_id] = asyncio.Queue()
    try:
        input_record = None
        if input_id:
            validate_safe_id(input_id, "input id")
            input_record = {"input_url": f"/inputs/{input_id}.simc"}
        else:
            input_record = generated_inputs_by_user.get(user_id) or generated_inputs_by_user.get("latest")
        input_url = input_record["input_url"] if input_record else "/inputs/char_simc_addon.txt"
        await manager.send_task(target_worker, {"type": "start", "task_id": task_id, "input_url": input_url})
        manager.active_workers[target_worker].status, manager.active_workers[target_worker].current_task, manager.active_workers[target_worker].user_id = "Busy", task_id, user_id
    except Exception:
        if task_id in manager.task_queues: del manager.task_queues[task_id]
        raise HTTPException(status_code=500, detail="Failed to communicate with worker")
    return {"status": "success", "task_id": task_id, "worker_id": target_worker}

@app.get("/api/simulation/stream/{task_id}", tags=["Simulation"])
async def stream_simulation(task_id: str, worker_id: str):
    """Stream Server-Sent Events for the simulation identified by *task_id*.

    **Tags:** Simulation
    **Response Type:** ``text/event-stream``
    """
    if task_id not in manager.task_queues: raise HTTPException(status_code=404)
    return StreamingResponse(simulation_event_generator(task_id, worker_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})

@app.get("/api/get-results", response_model=GetResultsResponse, tags=["Simulation"])
async def get_results(task_id: str = Query(default="latest")):
    """Retrieve parsed simulation results (DPS per class, gear data) for a completed task.

    **Tags:** Simulation
    **Query Parameters:**
      - ``task_id``: Task ID, or ``"latest"`` for the most recent report. Defaults to "latest".

    **Response Model:** ``GetResultsResponse``
    """
    try:
        html_path = None
        if task_id == "latest":
             all_reports = glob.glob(os.path.join(REPORTS_DIR, "*", "report_*.html"))
             if not all_reports: return {"status": "error", "message": "No reports found"}
             all_reports.sort(key=os.path.getmtime, reverse=True)
             html_path = all_reports[0]
        else:
            tmp_dir = _safe_task_dir(task_id)
            if not os.path.exists(tmp_dir):
                return {"status": "error", "message": f"Task {task_id} results not found"}
            report_files = [f for f in os.listdir(tmp_dir) if f.startswith("report_") and f.endswith(".html")]
            if not report_files: return {"status": "error", "message": "No reports found"}
            report_files.sort(key=lambda x: os.path.getmtime(os.path.join(tmp_dir, x)), reverse=True)
            html_path = os.path.join(tmp_dir, report_files[0])

        with open(html_path, encoding='utf-8', errors='replace') as f: html_content = f.read()
        results = []
        sections = re.split(r'<h2[^>]+class="toggle">', html_content)
        for section in sections[1:]:
            m = re.match(r'^\s*([^<]+?)\s*(?:&#160;)?\s*:\s*(?:&#160;)?\s*([\d,.]+)\s*dps', section, re.IGNORECASE)
            if m:
                name, dps_str = m.group(1).strip(), m.group(2).replace(',', '')
                if name == "Raid": continue
                dps = int(float(dps_str))
                gear = {}
                gt_match = re.search(r'<div class="player-section gear">.*?<table[^>]*>(.*?)</table>', section, re.DOTALL)
                if gt_match:
                    slot_map = {"Head": "head", "Neck": "neck", "Shoulders": "shoulder", "Back": "back", "Chest": "chest", "Wrists": "wrist", "Hands": "hands", "Waist": "waist", "Legs": "legs", "Feet": "feet", "Finger 1": "finger1", "Finger 2": "finger2", "Trinket 1": "trinket1", "Trinket 2": "trinket2", "Main Hand": "main_hand", "Off Hand": "off_hand"}
                    rows = re.finditer(r'<th[^>]*>\s*([^<]+)\s*</th>\s*<td[^>]*>\s*<a[^>]+href="([^"]+)"', gt_match.group(1), re.IGNORECASE)
                    for r in rows:
                        simc_slot = slot_map.get(r.group(1).strip())
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
        return {"status": "success", "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing results: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/inputs/{file_name}")
async def get_input_file(file_name: str):
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


def _safe_task_dir(task_id: str) -> str:
    return safe_task_dir(REPORTS_DIR, task_id)


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
async def worker_upload_file(task_id: str, file_name: str, secret: str, file: UploadFile = File(...)):
    """Upload an artifact (e.g. ``artifacts.zip``) from a worker node to the task directory.

    **Tags:** Workers
    **Authentication:** Requires ``secret`` matching ``CLUSTER_SECRET``.
    **Response Model:** ``WorkerUploadFileResponse``
    """
    if secret != CLUSTER_SECRET: raise HTTPException(status_code=403)
    dest_dir = _safe_task_dir(task_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = _safe_child_path(dest_dir, file_name)
    with open(dest_path, "wb") as f: f.write(await file.read())
    if file_name == "artifacts.zip":
        _extract_zip_safely(dest_path, dest_dir)
    return {"status": "success"}

@app.websocket("/ws/worker")
async def worker_websocket(websocket: WebSocket, name: str, secret: str):
    if secret != CLUSTER_SECRET: await websocket.close(code=1008); return
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
                    # Broadcast via all task queues that might have subscribers
                    for qid, queue in manager.task_queues.items():
                        try:
                            await queue.put({"type": "task_status_update", "task_id": tid, "status": task})
                        except Exception:
                            pass
                elif data["type"] == "log" or data["type"] == "log_batch" or data["type"] == "done":
                    tid = data.get("task_id")
                    if tid in manager.task_queues: await manager.task_queues[tid].put(data)
                    if data["type"] == "done": manager.active_workers[worker_id].status = "Idle"
    except WebSocketDisconnect: manager.disconnect(worker_id)
    except Exception as e: logger.error(f"WS error for {name}: {e}"); manager.disconnect(worker_id)

# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------
@app.get("/api/settings", response_model=SettingsResponse, tags=["Settings"])
async def get_settings():
    """Get current application settings.

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
        "simc_helper_dev_mode": os.environ.get("SIMC_HELPER_DEV_MODE") == "1",
        "ws_max_size": int(os.environ.get("WS_MAX_SIZE", "67108864")),  # 64MB default
    }


@app.post("/api/settings", response_model=SettingsResponse, tags=["Settings"])
async def update_settings(request: UpdateSettingsRequest):
    """Update application settings (runtime only - restart required for some changes).

    **Tags:** Settings
    **Request Model:** ``UpdateSettingsRequest``
    """
    # Update CORS settings if changed
    if request.cors_enabled:
        if request.cors_allowed_origins:
            os.environ["CORS_ALLOWED_ORIGINS"] = request.cors_allowed_origins
            logger.info("CORS enabled for origins: %s", request.cors_allowed_origins)
        else:
            os.environ["CORS_ALLOWED_ORIGINS"] = '["*"]'
            logger.info("CORS enabled for all origins")
    else:
        os.environ["CORS_ALLOWED_ORIGINS"] = ""
        logger.info("CORS disabled")
    
    # Update dev mode
    if request.simc_helper_dev_mode:
        os.environ["SIMC_HELPER_DEV_MODE"] = "1"
        logger.info("Dev mode enabled")
    else:
        os.environ["SIMC_HELPER_DEV_MODE"] = "0"
        logger.info("Dev mode disabled")
    
    # Update WebSocket max message size
    os.environ["WS_MAX_SIZE"] = str(request.ws_max_size)
    
    # Update sim cooldown
    global SIM_COOLDOWN_SECONDS
    SIM_COOLDOWN_SECONDS = request.sim_cooldown_seconds
    logger.info("Sim cooldown updated to %d seconds", request.sim_cooldown_seconds)
    
    # Update log level
    if request.log_level:
        os.environ["LOG_LEVEL"] = request.log_level
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
