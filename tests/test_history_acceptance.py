"""Acceptance tests for durable results history (t_c5d47786).

Action item 5/5 of adopted motion t_9b812b05:

* **Restart persistence** — run -> restart -> the /history report link still
  serves the report. Covered twice: in-process (in-memory task maps cleared,
  the only state a container restart actually destroys besides the process
  itself) and with a *real two-process restart* (uvicorn killed and relaunched
  against the same ``BASE_DIR`` volume, exactly what ``docker restart`` of
  simc-master does to the app).
* **P0-dependent paths** — the motion's dependency evidence named three of the
  four P0s as gating history acceptance:
    - t_4485565b (zero-combo crash): a baseline-only run must reach the
      task-done point and produce a history row;
    - t_fdd385ef (report parser): ``top_dps`` must be parsed from REAL nightly
      report markup (fixtures captured by t_1651ba9b);
    - t_ef8682a4 (cooldown-table auth bug): the history read side must not
      depend on the ``user_sessions`` cooldown table.

The E2E flow drives the genuine master API surface: a fake worker over the
real ``/ws/worker`` protocol, artifact upload via ``/api/worker/upload-file``,
the SSE done event that fires the ``run_history`` insert hook, and the
``/api/history`` + ``/reports`` read side.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

import web.main as master
from src.core import security
from src.core.db import run_history_list, user_create, user_delete
from web.main import REPORTS_DIR, app

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
# Real SimulationCraft 1210-01 nightly reports (t_1651ba9b). Certified parse
# results (after 60e8297 'toggle open' fix): multicopy -> top dps 7887;
# baseline-only -> Hamidriel 7877 dps (the single real player's header
# carries class="toggle open"").
MULTICOPY_REPORT = os.path.join(FIXTURES, "simc_nightly_report_multicopy.html")
BASELINE_ONLY_REPORT = os.path.join(FIXTURES, "simc_nightly_report_baseline_only.html")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fixture_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _make_user(prefix: str = "acc") -> str:
    username = f"{prefix}-{uuid.uuid4().hex[:8]}"
    return user_create(username, security.hash_password("pw-not-used"))


def _authed_client(user_id: str) -> TestClient:
    client = TestClient(app)
    # conftest kill switch -> require_session yields "anonymous"; the user_id
    # cookie then carries the identity through _resolved_user_id, same rule
    # the write hook used to stamp task ownership.
    client.cookies.set("session_id", master._issue_session(user_id))
    client.cookies.set("user_id", user_id)
    return client


def _drive_run(client: TestClient, worker_ws, *, report_file=None, code=0):
    """Run the real flow: run-simulation -> worker start -> upload -> done -> SSE.

    Returns ``(task_id, worker_id)`` after the SSE stream has observed the
    terminal event, i.e. after the run_history insert hook has fired.
    """
    # SEC-6: explicit input_id (the fake ws worker never fetches it)
    resp = client.post("/api/run-simulation", params={"input_id": "acc-drive"})
    assert resp.status_code == 200, resp.text
    task_id, worker_id = resp.json()["task_id"], resp.json()["worker_id"]

    start = worker_ws.receive_json()
    assert start["type"] == "start" and start["task_id"] == task_id

    if report_file:
        up = client.post(
            "/api/worker/upload-file",
            params={"task_id": task_id, "file_name": "report_1.html"},
            headers={"X-Cluster-Secret": master.CLUSTER_SECRET},
            files={"file": ("report_1.html", _fixture_bytes(report_file), "text/html")},
        )
        assert up.status_code == 200, up.text

    worker_ws.send_json({"type": "done", "task_id": task_id, "code": code})

    with client.stream(
        "GET", f"/api/simulation/stream/{task_id}?worker_id={worker_id}"
    ) as stream:
        _read_until_terminal(stream)
    return task_id, worker_id


def _read_until_terminal(stream, timeout: float = 20.0) -> str:
    deadline = time.time() + timeout
    for line in stream.iter_lines():
        if line.startswith("data:") and ('"type": "done"' in line or '"type": "error"' in line):
            return line
        if time.time() > deadline:
            raise TimeoutError("SSE stream never reached a terminal event")
    raise AssertionError("SSE stream closed without a terminal event")


def _history_row(client: TestClient, task_id: str) -> dict:
    """The history row whose report lives under ``<user>/<task_id>/``."""
    runs = client.get("/api/history").json()["runs"]
    matches = [r for r in runs if r["report_path"] and f"/{task_id}/" in r["report_path"]]
    assert matches, f"no history row for task {task_id} in {[r['run_id'] for r in runs]}"
    return matches[0]


@pytest.fixture
def history_user():
    user_id = _make_user()
    yield user_id
    user_delete(user_id)  # FK CASCADE removes the user's run_history rows


@pytest.fixture
def worker_ws():
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/worker?name=acc-{uuid.uuid4().hex[:6]}",
            headers={"X-Cluster-Secret": master.CLUSTER_SECRET},
        ) as ws:
            yield ws


# ---------------------------------------------------------------------------
# E2E write path (real ws worker + upload + SSE done hook)
# ---------------------------------------------------------------------------

def test_e2e_run_records_history_row_with_real_nightly_report(history_user, worker_ws):
    """P0 t_fdd385ef × history: top_dps comes from REAL nightly report markup."""
    client = _authed_client(history_user)
    task_id, _ = _drive_run(client, worker_ws, report_file=MULTICOPY_REPORT)

    row = _history_row(client, task_id)
    assert row["status"] == "success"
    assert row["top_dps"] == 7887  # certified value of the multicopy fixture
    user_dir = master._user_report_dir(history_user)
    assert row["report_path"] == os.path.join(user_dir, task_id, "report_1.html")

    assert row["report_url"] == f"reports/{user_dir}/{task_id}/report_1.html"
    served = TestClient(app).get("/" + row["report_url"])
    assert served.status_code == 200
    assert served.content == _fixture_bytes(MULTICOPY_REPORT)


def test_e2e_zero_combo_baseline_run_reaches_history(history_user, worker_ws):
    """P0 t_4485565b × history: the zero-combo baseline run no longer crashes
    before task-done, so it produces a history row with a served report."""
    client = _authed_client(history_user)
    task_id, _ = _drive_run(client, worker_ws, report_file=BASELINE_ONLY_REPORT)

    row = _history_row(client, task_id)
    assert row["status"] == "success"
    # t_1651ba9b (60e8297) taught the parser the nightly 'toggle open' player
    # header, so the single real player (Hamidriel, 7877 dps) is now parsed
    # out of the baseline-only fixture instead of the pet-only 0 dps.
    assert row["top_dps"] == 7877
    served = TestClient(app).get("/" + row["report_url"])
    assert served.status_code == 200
    assert served.content == _fixture_bytes(BASELINE_ONLY_REPORT)


def test_e2e_failed_run_records_failed_row_without_link(history_user, worker_ws):
    """A non-zero exit still lands a row (status=failed) and no dead link."""
    client = _authed_client(history_user)
    task_id, _ = _drive_run(client, worker_ws, code=1)

    runs = client.get("/api/history").json()["runs"]
    assert any(r["status"] == "failed" for r in runs), runs
    failed = [r for r in runs if r["status"] == "failed"][-1]
    assert failed["report_url"] is None


# ---------------------------------------------------------------------------
# Restart persistence
# ---------------------------------------------------------------------------

def test_restart_in_memory_loss_keeps_history_link_serving(history_user, worker_ws):
    """Container-restart contract (in-process): the only restart-destroyed
    state is the in-memory task maps — sqlite and REPORTS_DIR are durable.
    After wiping the maps, /history must still list the run and its report
    link must still serve (ownership recovered via the REPORTS_DIR glob)."""
    client = _authed_client(history_user)
    task_id, _ = _drive_run(client, worker_ws, report_file=MULTICOPY_REPORT)
    before = _history_row(client, task_id)
    assert task_id in master.task_user_map

    # Simulate the restart: drop every in-memory map, keep files + sqlite.
    master.task_user_map.clear()
    master.task_meta_map.clear()
    try:
        after = _history_row(client, task_id)
        assert after["run_id"] == before["run_id"]
        assert after["report_url"] == before["report_url"]

        served = TestClient(app).get("/" + after["report_url"])
        assert served.status_code == 200
        assert served.content == _fixture_bytes(MULTICOPY_REPORT)

        # get-results' sibling lookup must also survive the lost map.
        resolved = TestClient(app).get(f"/api/report-url?task_id={task_id}")
        assert resolved.status_code == 200
        assert resolved.json()["url"] == before["report_url"]
    finally:
        master.task_user_map.clear()
        master.task_meta_map.clear()


# --- real two-process restart ------------------------------------------------

ACC_SECRET = "acceptance-secret-c5d47786-x"
_STARTUP_TIMEOUT = 30.0


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _master_env(base_dir: str) -> dict:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env = dict(os.environ)
    env.update(
        BASE_DIR=base_dir,
        CLUSTER_SECRET=ACC_SECRET,
        PYTHONPATH=os.pathsep.join([os.path.join(root, "src"), root]),
    )
    # The suite's conftest points REPORTS_DIR at a temp dir and dev mode may
    # leak in; the subprocess must derive both from BASE_DIR like the container.
    for key in ("REPORTS_DIR", "SIMC_HELPER_DEV_MODE", "AUTHENTICATION_ENABLED"):
        env.pop(key, None)
    return env


def _start_master(base_dir: str, port: int) -> subprocess.Popen:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    log_path = os.path.join(base_dir, f"master-{port}.log")
    log_file = open(log_path, "ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        cwd=root,
        env=_master_env(base_dir),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    proc._acc_log = log_path  # noqa: SLF001 — surfaced in failure messages
    deadline = time.time() + _STARTUP_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            with open(log_path, encoding="utf-8", errors="replace") as f:
                raise AssertionError(f"master exited at startup:\n{f.read()[-3000:]}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.3)
    proc.kill()
    raise AssertionError(f"master never became healthy; see {log_path}")


def _stop_master(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_restart_persistence_two_process_history_link_serves_report(tmp_path):
    """THE acceptance test of the motion: run -> restart the master process
    against the same data volume -> /history still lists the run and its
    report link still serves the report.

    This is what ``docker restart simc-master`` does to the app: the process
    (and with it ``task_user_map``) dies; ``BASE_DIR/data`` (the simc-data
    volume: sqlite + reports) survives.
    """
    from websockets.sync.client import connect as ws_connect

    base_dir = str(tmp_path)
    port = _free_port()
    proc = _start_master(base_dir, port)
    url = f"http://127.0.0.1:{port}"
    try:
        client = httpx.Client(base_url=url, timeout=15)

        # register + login for real (auth is on by default in the subprocess)
        # t_e4d97db9: register now redirects like login; SEC-7 (t_0e328148):
        # session_id is an opaque token, the user is resolved via auth_sessions.
        username = f"restart-{uuid.uuid4().hex[:8]}"
        r = client.post("/register", data={"username": username, "password": "***"},
                        follow_redirects=False)
        assert r.status_code == 303, r.text
        session_token = client.cookies.get("session_id")
        assert session_token
        r = client.post("/login", data={"username": username, "password": "***"},
                        follow_redirects=False)
        assert r.status_code == 303

        # t_ef8682a4 (unmerged): login seeds the run cooldown, so a fresh
        # login would 429 run-simulation for 30s. Rewind the cooldown row
        # directly; the xfail test below pins the bug itself.
        db = sqlite3.connect(os.path.join(base_dir, "data", "master", "simc_helper.sqlite"))
        user_id = db.execute(
            "SELECT user_id FROM auth_sessions WHERE token = ?", (session_token,)
        ).fetchone()[0]
        db.execute("UPDATE user_sessions SET last_sim_time = 0 WHERE user_id = ?", (user_id,))
        db.commit()
        db.close()

        # fake worker on the real ws protocol
        with ws_connect(
            f"ws://127.0.0.1:{port}/ws/worker?name=acc",
            additional_headers={"X-Cluster-Secret": ACC_SECRET},
        ) as ws:
            # SEC-6: explicit input_id (the fake ws worker never fetches it)
            r = client.post("/api/run-simulation", params={"input_id": "acc-live"})
            assert r.status_code == 200, r.text
            task_id, worker_id = r.json()["task_id"], r.json()["worker_id"]

            start = json.loads(ws.recv(timeout=15))
            assert start["type"] == "start" and start["task_id"] == task_id

            report = _fixture_bytes(MULTICOPY_REPORT)
            r = client.post(
                "/api/worker/upload-file",
                params={"task_id": task_id, "file_name": "report_1.html"},
                headers={"X-Cluster-Secret": ACC_SECRET},
                files={"file": ("report_1.html", report, "text/html")},
            )
            assert r.status_code == 200, r.text
            ws.send(json.dumps({"type": "done", "task_id": task_id, "code": 0}))

            with client.stream(
                "GET", f"/api/simulation/stream/{task_id}?worker_id={worker_id}"
            ) as stream:
                _read_until_terminal(stream)

        # pre-restart: the row exists and the link serves
        runs = client.get("/api/history").json()["runs"]
        assert len(runs) == 1
        assert runs[0]["top_dps"] == 7887
        report_url = runs[0]["report_url"]
        assert client.get("/" + report_url).content == report

        # ---- restart the process (same BASE_DIR volume) ----
        _stop_master(proc)
        proc = _start_master(base_dir, port)

        # session cookie still valid (users table is durable)
        runs = client.get("/api/history").json()["runs"]
        assert len(runs) == 1, "history row lost across restart"
        assert runs[0]["run_id"] == runs[0]["run_id"]
        assert runs[0]["report_url"] == report_url

        # the /history link still serves the exact report bytes
        served = client.get("/" + report_url)
        assert served.status_code == 200
        assert served.content == report

        # report-url resolves with an EMPTY task map (glob fallback)
        resolved = client.get(f"/api/report-url?task_id={task_id}")
        assert resolved.status_code == 200
        assert resolved.json()["url"] == report_url

        # the /history page itself still renders for the session
        page = client.get("/history", follow_redirects=False)
        assert page.status_code == 200
        client.close()
    finally:
        _stop_master(proc)


# ---------------------------------------------------------------------------
# P0 t_ef8682a4 — history reads must not depend on the cooldown table
# ---------------------------------------------------------------------------

def _auth_on(monkeypatch):
    monkeypatch.setattr(master, "authentication_enabled", lambda: True)
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)


def test_history_reads_work_without_cooldown_rows(history_user, monkeypatch):
    """The old page gates consulted ``session_get`` (the user_sessions cooldown
    table), which is purged regularly — a logged-in user with no cooldown row
    got bounced. The history read side must use the users table only."""
    _auth_on(monkeypatch)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    # user_create seeds a cooldown row; the regular purge deletes it again —
    # reproduce the purged state (this is what session_cleanup_older_than does).
    from src.core.db import session_delete
    session_delete(history_user)
    assert master.session_get(history_user) is None  # no cooldown row exists

    client = TestClient(app)
    client.cookies.set("session_id", master._issue_session(history_user))

    assert client.get("/history").status_code == 200
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []


def test_run_simulation_right_after_login_known_p0(monkeypatch):
    """A fresh login must not lock the user out of run-simulation for 30s.

    Canary retired: t_ef8682a4 landed on main (ed3498a), so the assertions
    now pin the FIXED behaviour — login leaves no cooldown state.
    """
    _auth_on(monkeypatch)
    password = "acceptance-pw"
    username = f"login-{uuid.uuid4().hex[:8]}"
    user_id = user_create(username, security.hash_password(password))
    try:
        client = TestClient(app)
        r = client.post("/login", data={"username": username, "password": password},
                        follow_redirects=False)
        assert r.status_code == 303, r.text  # session cookie set
        assert master.session_get(user_id) in (None, 0.0)  # no cooldown seeded
        r = client.post("/api/run-simulation")
        assert r.status_code != 429, "login seeded the run cooldown (t_ef8682a4)"
    finally:
        user_delete(user_id)


# ---------------------------------------------------------------------------
# Retention cap × history (t_c968bf8d contract)
# ---------------------------------------------------------------------------

def test_retention_prune_keeps_row_and_nulls_its_link(history_user, worker_ws, monkeypatch):
    """Pruned runs stay listed (history is the record) but their link goes
    null; the surviving newest runs keep serving."""
    monkeypatch.setattr(master, "REPORT_RETENTION", 2)
    client = _authed_client(history_user)

    task_ids = []
    for i in range(3):
        master.session_set(history_user, 0)  # clear the 30s run cooldown
        task_id, _ = _drive_run(client, worker_ws, report_file=MULTICOPY_REPORT)
        task_ids.append(task_id)
        # deterministic mtime ordering for the prune
        task_dir = os.path.join(REPORTS_DIR, master._user_report_dir(history_user), task_id)
        os.utime(task_dir, (1_700_000_000 + i, 1_700_000_000 + i))

    oldest, middle, newest = task_ids
    user_dir = master._user_report_dir(history_user)
    assert not os.path.isdir(os.path.join(REPORTS_DIR, user_dir, oldest))
    assert os.path.isdir(os.path.join(REPORTS_DIR, user_dir, middle))
    assert os.path.isdir(os.path.join(REPORTS_DIR, user_dir, newest))

    runs = client.get("/api/history").json()["runs"]
    by_task = {t: _history_row(client, t) for t in task_ids}
    assert by_task[oldest]["report_url"] is None       # row survives, link dead
    assert by_task[middle]["report_url"] is not None
    assert by_task[newest]["report_url"] is not None
    assert TestClient(app).get("/" + by_task[newest]["report_url"]).status_code == 200
