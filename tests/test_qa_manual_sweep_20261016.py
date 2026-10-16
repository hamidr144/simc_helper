"""Regression tests filed from manual test plan t_9e76ba93 (2026-10-16).

Each test asserts the CORRECT behaviour from the manual test plan and is
expected to FAIL (red) until the matching BUG card is fixed. One test per
bug; the BUG card id is in the docstring.

Run: .venv/bin/python -m pytest tests/test_qa_manual_sweep_20261016.py -v
"""

import sys
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import src.web.main as master
from src.core import security
from src.core.db import user_create

app = master.app
manager = master.manager

GEN_BODY = {
    "char_class": "paladin", "char_name": "QASweep",
    "base_profile": "paladin=QASweep", "equipped_gear": {},
    "selected_items": {}, "selected_enchants": {}, "selected_gems": [],
    "selected_meta_gems": [], "item_levels": {}, "gear_upgrades": {},
    "voidforged_items": {}, "extra_sockets": {},
}


@pytest.fixture()
def auth_on(monkeypatch):
    """Enable the session gate, disable dev mode and the pytest kill-switch
    exactly like production (pattern from test_integration.TestP03)."""
    monkeypatch.setattr(master, "authentication_enabled", lambda: True)
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")


def _login(username: str) -> TestClient:
    user_id = user_create(username, security.hash_password("pw-qa-123"))
    c = TestClient(app)
    r = c.post("/login", data={"username": username, "password": "pw-qa-123"},
               follow_redirects=False)
    assert r.status_code == 303, f"login failed for {username}"
    c.user_id = user_id
    return c


def _mock_idle_worker():
    """Patch manager so run-simulation dispatches to a fake idle worker."""
    mock = patch.object(manager, "get_idle_worker", return_value="w-test")
    mock2 = patch.object(manager, "send_task")
    return mock, mock2


# ---------------------------------------------------------------- SEC family

def test_sec1_get_results_requires_session(auth_on):
    """BUG SEC-1: /api/get-results must not answer unauthenticated callers."""
    c = TestClient(app)
    r = c.get("/api/get-results", params={"task_id": "latest"})
    assert r.status_code == 401, f"unauthenticated get-results returned {r.status_code}"


def test_sec2_task_status_requires_session(auth_on):
    """BUG SEC-2: /api/task-status must not answer unauthenticated callers."""
    c = TestClient(app)
    r = c.get("/api/task-status")
    assert r.status_code == 401, f"unauthenticated task-status returned {r.status_code}"


def test_sec3_report_url_requires_session(auth_on):
    """BUG SEC-3: /api/report-url must reject unauthenticated callers before
    resolving (401), not leak resolution results (404/200)."""
    c = TestClient(app)
    r = c.get("/api/report-url", params={"task_id": "deadbeef"})
    assert r.status_code == 401, f"unauthenticated report-url returned {r.status_code}"


def test_sec4_sse_streams_require_session(auth_on):
    """BUG SEC-4: simulation + update-simc SSE streams must require a session."""
    c = TestClient(app)
    r = c.get("/api/simulation/stream/abc12345", params={"worker_id": "w1"})
    assert r.status_code == 401, f"unauthenticated sim stream returned {r.status_code}"
    r = c.get("/api/update-simc/stream/upd-1")
    assert r.status_code == 401, f"unauthenticated update stream returned {r.status_code}"


def test_sec5_sec14_static_mounts_require_session(auth_on):
    """BUG SEC-5/SEC-14: /reports/ and /inputs/ mounts must not serve files
    to unauthenticated callers (401/403, not 404/200)."""
    c = TestClient(app)
    r = c.get("/inputs/char_simc_addon.txt")
    assert r.status_code in (401, 403), f"unauthenticated /inputs returned {r.status_code}"
    r = c.get("/reports/deadbeef/report.html")
    assert r.status_code in (401, 403), f"unauthenticated /reports returned {r.status_code}"

    # The fix must not over-block: a logged-in browser and a cluster worker
    # (X-Cluster-Secret, no cookie) still get past the gate (404 is fine —
    # the file need not exist; 401/403 means the gate is broken).
    a = _login(f"sec5-{uuid.uuid4().hex[:6]}")
    assert a.get("/reports/deadbeef/report.html").status_code not in (401, 403)
    assert a.get("/inputs/char_simc_addon.txt").status_code not in (401, 403)
    if master.CLUSTER_SECRET:
        r = c.get("/inputs/char_simc_addon.txt",
                  headers={"X-Cluster-Secret": master.CLUSTER_SECRET})
        assert r.status_code not in (401, 403), "worker cluster-secret gate broken"

def test_sec6_run_without_input_id_must_not_use_global_latest(auth_on):
    """BUG SEC-6: user B who never generated anything must not be able to run
    user A's latest input via the global 'latest' fallback."""
    a = _login(f"sec6-a-{uuid.uuid4().hex[:6]}")
    gen = a.post("/api/generate-simc", json=GEN_BODY)
    assert gen.status_code == 200
    a_input = gen.json()["input_id"]

    b = _login(f"sec6-b-{uuid.uuid4().hex[:6]}")
    m1, m2 = _mock_idle_worker()
    with m1, m2 as send_task:
        manager.active_workers["w-test"] = MagicMock(status="Idle")
        r = b.post("/api/run-simulation")
    manager.active_workers.pop("w-test", None)  # MagicMock leaks into /api/state otherwise
    dispatched = send_task.call_args[0][1]["input_url"] if send_task.called else ""
    assert r.status_code in (401, 422) or a_input not in dispatched, (
        f"B ran A's input {a_input} via global latest fallback ({dispatched})")

def test_sec7_logout_must_invalidate_session_server_side(auth_on):
    """BUG SEC-7: after /logout the same session cookie must stop working."""
    c = _login(f"sec7-{uuid.uuid4().hex[:6]}")
    assert c.get("/api/state").status_code == 200
    stolen = c.cookies.get("session_id")
    assert stolen
    c.get("/logout", follow_redirects=False)
    r = c.get("/api/state")
    assert r.status_code == 401, "session cookie still valid after logout"
    # The card's repro: replay the captured cookie in a fresh client.
    replay = TestClient(app)
    replay.cookies.set("session_id", stolen)
    r = replay.get("/api/state")
    assert r.status_code == 401, "copied cookie still valid after logout"

# ---------------------------------------------------------------- LIFE family

def test_life2_master_restart_keeps_run_attribution(auth_on):
    """BUG LIFE-2 (t_2c718ca6): a master restart mid-run must not lose the
    task->user attribution. The durable task->user map restores the owner
    after the in-memory maps die, the artifacts upload lands in the owner's
    report directory (not anonymous/), and the upload itself records the
    run_history row because the worker's done event never reaches the
    restarted master."""
    import io
    import os
    import zipfile

    from src.core.db import run_history_list, user_delete

    c = _login(f"life2-{uuid.uuid4().hex[:6]}")
    m1, m2 = _mock_idle_worker()
    with m1, m2:
        manager.active_workers["w-test"] = MagicMock(status="Idle")
        # SEC-6: explicit input_id (the fake worker never fetches it)
        r = c.post("/api/run-simulation", params={"input_id": "life2-drive"})
        assert r.status_code == 200, r.text
        task_id = r.json()["task_id"]
    assert master.task_user_map.get(task_id) == c.user_id

    try:
        # Simulate the restart: in-memory maps die, sqlite + volumes survive.
        master.task_user_map.clear()
        master.task_meta_map.clear()
        manager.task_queues.pop(task_id, None)
        master._restore_task_owner_maps()
        assert master.task_user_map.get(task_id) == c.user_id, \
            "task->user attribution not durable across restart"

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("report_1.html",
                        '<h2 class="toggle">Life2&#160;:&#160;1234 dps</h2>')
        r = TestClient(app).post(
            "/api/worker/upload-file",
            params={"task_id": task_id, "file_name": "artifacts.zip"},
            headers={"X-Cluster-Secret": master.CLUSTER_SECRET},
            files={"file": ("artifacts.zip", buf.getvalue(), "application/zip")},
        )
        assert r.status_code == 200, r.text

        user_dir = master._user_report_dir(c.user_id)
        assert os.path.isdir(os.path.join(master.REPORTS_DIR, user_dir, task_id))
        assert not os.path.isdir(os.path.join(master.REPORTS_DIR, "anonymous", task_id))
        rows = run_history_list(c.user_id)
        assert any(row["status"] == "success" and row["top_dps"] == 1234 for row in rows), \
            f"no attributed history row in {rows}"
    finally:
        user_delete(c.user_id)  # FK CASCADE removes the run_history rows
        master.task_user_map.pop(task_id, None)
        master.task_meta_map.pop(task_id, None)
        manager.active_workers.pop("w-test", None)

def test_sec1b_get_results_latest_scoped_to_caller(auth_on, tmp_path, monkeypatch):
    """BUG SEC-1b (t_a4ff7b5d): task_id=latest must resolve only the CALLER's
    newest report. The old REPORTS_DIR/* glob served the globally newest
    report to any logged-in user."""
    import os

    monkeypatch.setattr(master, "REPORTS_DIR", str(tmp_path))
    victim_dir = tmp_path / "victim-user-uuid" / "task0001"
    victim_dir.mkdir(parents=True)
    victim_report = victim_dir / "report_20261016_000000.html"
    victim_report.write_text(
        '<h2 class="toggle">VictimChar : 9999 dps</h2>', encoding="utf-8")
    c = _login(f"sec1b-{uuid.uuid4().hex[:6]}")
    r = c.get("/api/get-results", params={"task_id": "latest"})
    assert "VictimChar" not in r.text, (
        f"get-results served ANOTHER user's report to a caller with no runs: "
        f"{r.status_code} {r.text[:160]}")
    # The fix must not over-block: the caller's own newest report is still
    # served even when another user's report is newer on disk.
    own_dir = tmp_path / master._user_report_dir(c.user_id) / "owntask"
    own_dir.mkdir(parents=True)
    (own_dir / "report_20261016_000001.html").write_text(
        '<h2 class="toggle">OwnChar : 111 dps</h2>', encoding="utf-8")
    os.utime(victim_report, (time.time() + 10, time.time() + 10))
    r = c.get("/api/get-results", params={"task_id": "latest"})
    assert "OwnChar" in r.text and "VictimChar" not in r.text, r.text[:160]

def test_life8_parse_garbage_must_be_rejected(auth_on):
    """BUG LIFE-8/E2E-9: garbage addon text must get a 4xx, not 200 with an
    empty Unknown/Unknown parse."""
    c = _login(f"life8-{uuid.uuid4().hex[:6]}")
    r = c.post("/api/parse-addon", json={
        "addon_text": "this is not a simc export\njust some words\n12345\n",
        "character_name": "x"})
    assert r.status_code >= 400, (
        f"garbage parsed with HTTP {r.status_code}: {r.text[:120]}")

# ---------------------------------------------------------------------------
# LIFE-4 (t_5d6903e4): SSE disconnect must not delete the run queue and the
# first viewer to leave must not kill another tab's stream.
# ---------------------------------------------------------------------------

class _FakeWorkerWS:
    """Minimal stand-in for the /ws/worker socket (pattern from
    test_worker_retry's direct-handler tests)."""

    def __init__(self, msgs):
        self._msgs = list(msgs)
        self.headers = {"x-cluster-secret": master.CLUSTER_SECRET}

    async def accept(self): pass

    async def receive_json(self):
        if self._msgs:
            return self._msgs.pop(0)
        from starlette.websockets import WebSocketDisconnect
        raise WebSocketDisconnect(code=1000)

    async def send_json(self, data): pass

    async def close(self, code=None): pass


@pytest.mark.asyncio
async def test_life4_streams_independent_and_survive_disconnect():
    """Two viewers on one task each receive every event; cancelling one
    viewer's generator (what starlette does on SSE disconnect) must keep the
    task queue and metadata alive and the survivor must still see done."""
    import asyncio as aio
    task_id = f"life4-{uuid.uuid4().hex[:6]}"
    manager.task_queues[task_id] = set()
    manager.active_workers["w-life4"] = MagicMock(status="Busy")
    master.task_meta_map[task_id] = {"char_name": "Life4"}
    master.task_user_map[task_id] = "life4-no-such-user"  # FK insert fails, swallowed by design
    try:
        gen1 = master.simulation_event_generator(task_id, "w-life4")
        gen2 = master.simulation_event_generator(task_id, "w-life4")
        t1 = aio.ensure_future(gen1.__anext__())
        t2 = aio.ensure_future(gen2.__anext__())
        await aio.sleep(0.05)  # both generators register their queues
        assert len(manager.task_queues[task_id]) == 2

        t1.cancel()  # viewer 1 closes its tab mid-run
        try:
            await t1
        except aio.CancelledError:
            pass
        assert task_id in manager.task_queues, \
            "SSE disconnect deleted the run queue (LIFE-4)"
        assert task_id in master.task_meta_map, \
            "SSE disconnect lost the run metadata"

        # the real worker-WS handler delivers log + done with viewer 1 gone
        await master.worker_websocket(_FakeWorkerWS([
            {"type": "log", "task_id": task_id, "text": "x"},
            {"type": "done", "task_id": task_id, "code": 0},
        ]), name="life4-ws")

        log_line = await aio.wait_for(t2, timeout=2)
        assert '"log"' in log_line, "survivor stream lost its events"
        done_line = await aio.wait_for(gen2.__anext__(), timeout=2)
        assert '"type": "done"' in done_line, "survivor never saw done"
        assert task_id not in manager.task_queues, \
            "done must free the queue entry"
        assert task_id not in master.task_meta_map, \
            "done must consume the metadata snapshot"
    finally:
        manager.task_queues.pop(task_id, None)
        manager.active_workers.pop("w-life4", None)
        master.task_meta_map.pop(task_id, None)
        master.task_user_map.pop(task_id, None)


def test_life4_run_completes_without_viewer_records_history_row(auth_on):
    """Card case (a): no SSE viewer is ever connected (refresh mid-run) —
    the run must still finish with a /history row, and the queue entry is
    freed at run end, not on viewer presence."""
    from src.core.db import run_history_list, user_delete
    c = _login(f"life4-{uuid.uuid4().hex[:8]}")
    task_id = None
    try:
        with TestClient(app) as admin:
            with admin.websocket_connect(
                f"/ws/worker?name=life4-{uuid.uuid4().hex[:6]}",
                headers={"X-Cluster-Secret": master.CLUSTER_SECRET},
            ) as ws:
                # no patching: the connected fake worker IS the idle worker
                r = c.post("/api/run-simulation", params={"input_id": "life4-drive"})
                assert r.status_code == 200, r.text
                task_id = r.json()["task_id"]
                assert ws.receive_json()["task_id"] == task_id
                assert task_id in manager.task_queues
                ws.send_json({"type": "done", "task_id": task_id, "code": 0})

                deadline = time.time() + 5
                rows = []
                while time.time() < deadline:
                    rows = run_history_list(c.user_id)
                    if any(row["status"] == "success" for row in rows):
                        break
                    time.sleep(0.1)
                assert any(row["status"] == "success" for row in rows), \
                    f"no history row for viewer-less run: {rows}"
                assert task_id not in manager.task_queues, \
                    "done must free the queue entry"
    finally:
        if task_id:
            master.task_user_map.pop(task_id, None)
            master.task_meta_map.pop(task_id, None)
        user_delete(c.user_id)  # FK CASCADE removes the run_history rows

def test_life9_worker_upload_failure_must_not_swallow():
    """BUG LIFE-9: worker.upload_file swallows every exception and returns
    None (worker.py:145-147) -> artifact loss looks like success."""
    import asyncio
    import src.worker as worker_mod

    class _Boom:
        def __init__(self, *a, **k): raise RuntimeError("disk full")

    old_url = worker_mod.MASTER_URL
    worker_mod.MASTER_URL = "http://master.invalid"
    try:
        with patch.object(worker_mod, "aiohttp", MagicMock(**{"ClientSession": _Boom})):
            with pytest.raises(Exception):
                asyncio.run(worker_mod.upload_file(MagicMock(), "t1", "/nonexistent.bin"))
    finally:
        worker_mod.MASTER_URL = old_url

# ---------------------------------------------------------------- E2E-7

def test_e2e7_zero_dps_pet_profiles_excluded_from_results(auth_on):
    """BUG E2E-7: nightly reports emit pet/utility profiles (e.g.
    Fluffy_Pillow) as player sections with 0 dps; parse_report_results
    returns them and the results page ranks them as real alternatives."""
    html = (
        '<h2 id="player1toggle" class="toggle"">QASweep&#160;:&#160;190784 dps</h2>'
        '<div class="player-section gear"></div>'
        '<h2 id="player-1toggle" class="toggle"">Fluffy_Pillow&#160;:&#160;0 dps</h2>'
        '<div class="player-section gear"></div>'
    )
    results = master.parse_report_results(html)
    names = [r["name"] for r in results]
    assert "Fluffy_Pillow" not in names, (
        f"0-dps pet profile surfaced as alternative: {names}")
