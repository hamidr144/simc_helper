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
    dispatched = send_task.call_args[0][1]["input_url"] if send_task.called else ""
    assert r.status_code in (401, 422) or a_input not in dispatched, (
        f"B ran A's input {a_input} via global latest fallback ({dispatched})")
