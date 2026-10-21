"""Tests for the /history page and per-run view (t_d34ced81).

Read side of the run_history contract from t_b3b78acd: the page gate, the
per-user list API, ownership-checked per-run detail, and report-link
resolution against REPORTS_DIR.
"""

import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import web.main as master
from src.core import security
from src.core.db import run_history_insert, user_create, user_delete
from web.main import REPORTS_DIR, app

# The suite-wide conftest disables auth (kill switch); page-gate tests opt
# back in per-test, mirroring test_master_api's helpers.


def _auth_on(monkeypatch):
    monkeypatch.setattr(master, "authentication_enabled", lambda: True)
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)


def _make_user():
    username = f"hist-{uuid.uuid4().hex[:8]}"
    return user_create(username, security.hash_password("pw-not-used"))


def _authed_client(user_id):
    client = TestClient(app)
    # session_id drives the real auth path; user_id is the kill-switch-mode
    # fallback identity in _resolved_user_id.
    client.cookies.set("session_id", master._issue_session(user_id))
    client.cookies.set("user_id", user_id)
    return client


def _seed_run(user_id, **overrides):
    record = {
        "run_id": uuid.uuid4().hex[:12],
        "user_id": user_id,
        "created_at": time.time(),
        "fighting_style": "single boss",
        "spec": "blood",
        "source": "addon",
        "char_name": "Testpal",
        "realm_slug": "dethecus",
        "region": "eu",
        "top_dps": 19951,
        "report_path": None,
        "status": "success",
    }
    record.update(overrides)
    run_history_insert(record)
    return record


@pytest.fixture
def history_user():
    user_id = _make_user()
    yield user_id
    user_delete(user_id)  # FK CASCADE removes the user's run_history rows


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

def test_history_page_served_when_auth_disabled():
    response = TestClient(app).get("/history")
    assert response.status_code == 200
    assert "history.js" in response.text
    css = (os.path.dirname(__file__) + "/../src/web/static/css/tokens.css")
    css_text = open(css, encoding="utf-8").read()
    history_js = (os.path.dirname(__file__) + "/../src/web/static/js/pages/history.js")
    js_text = open(history_js, encoding="utf-8").read()
    assert "@media(max-width:480px)" in css_text
    assert ".history-table thead{display:none}" in css_text
    assert ".history-table td::before{content:attr(data-label)" in css_text
    assert all(f'data-label="{label}"' in js_text for label in (
        "When", "Character", "Spec", "Fight", "Top DPS", "Status", "Report", "Run"
    ))
    assert "@media(min-width:481px){.history-table-card{overflow-x:visible}}" in css_text


def test_history_page_redirects_to_login_when_auth_on(monkeypatch):
    _auth_on(monkeypatch)
    # The page routes skip their gate while pytest is importable (dev-mode
    # parity); remove the marker to exercise the real redirect.
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    response = TestClient(app).get("/history", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "login"


def test_history_page_rejects_stale_session_when_auth_on(monkeypatch):
    _auth_on(monkeypatch)
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    client = TestClient(app)
    client.cookies.set("session_id", "user-id-that-does-not-exist")
    response = client.get("/history", follow_redirects=False)
    assert response.status_code == 303


def test_history_page_served_for_valid_session(monkeypatch, history_user):
    _auth_on(monkeypatch)
    response = _authed_client(history_user).get("/history")
    assert response.status_code == 200
    assert "Run history" in response.text


# ---------------------------------------------------------------------------
# List API
# ---------------------------------------------------------------------------

def test_api_history_requires_session(monkeypatch):
    _auth_on(monkeypatch)
    response = TestClient(app).get("/api/history")
    assert response.status_code == 401


def test_api_history_empty_for_anonymous_kill_switch():
    # conftest kill switch -> require_session returns "anonymous", which has
    # no run_history rows by design (the write hook skips anonymous users).
    response = TestClient(app).get("/api/history")
    assert response.status_code == 200
    assert response.json()["runs"] == []


def test_api_history_lists_own_runs_newest_first(history_user):
    old = _seed_run(history_user, created_at=time.time() - 3600, char_name="Old")
    new = _seed_run(history_user, created_at=time.time(), char_name="New")
    runs = _authed_client(history_user).get("/api/history").json()["runs"]
    ids = [r["run_id"] for r in runs]
    assert ids[:2] == [new["run_id"], old["run_id"]]
    newest = runs[0]
    assert newest["char_name"] == "New"
    assert newest["top_dps"] == 19951
    assert newest["status"] == "success"
    assert newest["realm_slug"] == "dethecus"


def test_api_history_respects_limit(history_user):
    for i in range(3):
        _seed_run(history_user, created_at=time.time() + i)
    runs = _authed_client(history_user).get("/api/history?limit=2").json()["runs"]
    assert len(runs) == 2


def test_api_history_isolated_between_users(history_user):
    other = _make_user()
    try:
        mine = _seed_run(history_user, char_name="Mine")
        _seed_run(other, char_name="Theirs")
        client = _authed_client(history_user)
        # conftest kill switch is module-level; force the real identity path.
        runs = client.get("/api/history").json()["runs"]
        assert all(r["char_name"] != "Theirs" for r in runs)
        assert any(r["run_id"] == mine["run_id"] for r in runs)
    finally:
        user_delete(other)


# ---------------------------------------------------------------------------
# Report links
# ---------------------------------------------------------------------------

def test_api_history_report_url_resolves_for_existing_report(history_user):
    task_id = f"t-{uuid.uuid4().hex[:8]}"
    user_dir = master._user_report_dir(history_user)
    task_dir = os.path.join(REPORTS_DIR, user_dir, task_id)
    os.makedirs(task_dir, exist_ok=True)
    report_file = os.path.join(task_dir, "report_123.html")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("<html>report</html>")
    rel = os.path.join(user_dir, task_id, "report_123.html")
    run = _seed_run(history_user, report_path=rel)
    try:
        runs = _authed_client(history_user).get("/api/history").json()["runs"]
        row = next(r for r in runs if r["run_id"] == run["run_id"])
        assert row["report_url"] == f"reports/{rel}"
        # The link must actually serve the report through the static mount.
        served = TestClient(app).get("/" + row["report_url"])
        assert served.status_code == 200
        assert "report" in served.text
    finally:
        import shutil

        shutil.rmtree(task_dir, ignore_errors=True)


def test_api_history_report_url_null_when_file_pruned(history_user):
    rel = os.path.join(master._user_report_dir(history_user), "gone-task", "report_1.html")
    run = _seed_run(history_user, report_path=rel)
    runs = _authed_client(history_user).get("/api/history").json()["runs"]
    row = next(r for r in runs if r["run_id"] == run["run_id"])
    assert row["report_url"] is None


def test_api_history_report_url_rejects_traversal(history_user):
    run = _seed_run(history_user, report_path="../../etc/passwd")
    runs = _authed_client(history_user).get("/api/history").json()["runs"]
    row = next(r for r in runs if r["run_id"] == run["run_id"])
    assert row["report_url"] is None


# ---------------------------------------------------------------------------
# Per-run detail
# ---------------------------------------------------------------------------

def test_api_history_detail_returns_run(history_user):
    run = _seed_run(history_user)
    response = _authed_client(history_user).get(f"/api/history/{run['run_id']}")
    assert response.status_code == 200
    detail = response.json()["run"]
    assert detail["run_id"] == run["run_id"]
    assert detail["fighting_style"] == "single boss"
    assert detail["source"] == "addon"


def test_api_history_detail_hides_other_users_run(history_user):
    other = _make_user()
    try:
        theirs = _seed_run(other)
        client = _authed_client(history_user)
        assert client.get(f"/api/history/{theirs['run_id']}").status_code == 404
    finally:
        user_delete(other)


def test_api_history_detail_unknown_run_is_404():
    response = TestClient(app).get("/api/history/nosuchrun")
    assert response.status_code == 404
