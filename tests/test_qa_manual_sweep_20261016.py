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
