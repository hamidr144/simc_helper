import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_generate_simc_creates_task_scoped_inputs_and_run_uses_latest(monkeypatch):
    import web.main as master

    master.generated_inputs_by_user.clear()
    master.user_last_sim_time.clear()
    client = TestClient(master.app)
    client.get('/')

    payload = {
        "base_profile": "paladin=Scoped",
        "char_class": "paladin",
        "char_name": "Scoped",
        "equipped_gear": {"head": "id=1"},
        "selected_items": {"head": ["id=10"]},
        "selected_enchants": {},
        "selected_gems": [],
    }

    first = client.post('/api/generate-simc', json=payload)
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["input_id"]
    assert first_data["input_url"] == f"/inputs/{first_data['input_id']}.simc"
    assert Path(first_data["file_path"]).exists()

    payload["selected_items"] = {"head": ["id=20"]}
    second = client.post('/api/generate-simc', json=payload)
    second_data = second.json()
    assert second_data["input_id"] != first_data["input_id"]
    assert "id=10" in client.get(first_data["input_url"]).text
    assert "id=20" in client.get(second_data["input_url"]).text

    with patch.object(master.manager, "get_idle_worker", return_value="worker1"), \
         patch.object(master.manager, "send_task") as send_task:
        master.manager.active_workers["worker1"] = type("W", (), {"status": "Idle"})()
        response = client.post('/api/run-simulation')

    assert response.status_code == 200
    sent = send_task.call_args.args[1]
    assert sent["input_url"] == second_data["input_url"]


def test_admin_token_protects_destructive_endpoints(monkeypatch):
    import web.main as master

    monkeypatch.setenv("ADMIN_TOKEN", "required-token")
    master.manager.active_workers.clear()
    client = TestClient(master.app)

    assert client.post('/api/stop-simulation').status_code == 403
    assert client.post('/api/shutdown').status_code == 403
    assert client.post('/api/update-simc').status_code == 403
    assert client.post('/api/stop-simulation', headers={"X-Admin-Token": "required-token"}).status_code in {200, 503}


def test_host_defaults_to_loopback(monkeypatch):
    import web.main as master

    monkeypatch.delenv("HOST", raising=False)
    assert master.get_bind_host() == "127.0.0.1"
    monkeypatch.setenv("HOST", "0.0.0.0")
    assert master.get_bind_host() == "0.0.0.0"


def test_debug_cli_uses_request_timeouts():
    from utils import debug_cli

    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"status": "ready", "workers": []}
        debug_cli.get_status()
        assert mock_get.call_args.kwargs["timeout"] == debug_cli.REQUEST_TIMEOUT

    with patch("requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"message": "Stopped", "status": "ok"}
        debug_cli.stop_simulation()
        debug_cli.shutdown_server()
        for call in mock_post.call_args_list:
            assert call.kwargs["timeout"] == debug_cli.REQUEST_TIMEOUT


def test_frontend_escapes_dynamic_values_before_html_insertion():
    js = Path("src/web/static/app.js").read_text()
    assert "function escapeHtml" in js
    assert "escapeHtml(parsedData.char_name)" in js
    assert "escapeHtml(w.name)" in js
    assert "appendLogLine" in js
    assert "textContent = text" in js


def test_ignored_local_config_files_are_not_tracked():
    tracked_ignored = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    assert "config.json" not in tracked_ignored
    assert "deploy_configs/master.json" not in tracked_ignored
    assert "deploy_configs/worker1.json" not in tracked_ignored


def test_examples_exist_for_untracked_configs():
    assert Path("examples/config.example.json").exists()
    assert Path("examples/deploy_master.example.json").exists()
    assert Path("examples/deploy_worker.example.json").exists()


def test_dev_tooling_config_exists():
    pyproject = Path("pyproject.toml").read_text()
    assert "[tool.pytest.ini_options]" in pyproject
    assert "[tool.coverage.run]" in pyproject
    assert Path("requirements-dev.txt").exists()
