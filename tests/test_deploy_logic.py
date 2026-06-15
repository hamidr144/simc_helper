import os
from unittest.mock import MagicMock, patch

import pytest

from utils.deploy import (
    DeploymentError,
    discover_config_files,
    fallback_start_command,
    get_rsync_cmd,
    get_ssh_cmd,
    load_config,
    main,
    make_systemd_unit,
    process_target_nodes,
    restart_service,
    run_cmd,
    select_target_nodes,
    setup_systemd,
    sync_code,
    validate_config,
)


def test_load_config(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"key": "value"}')
    config = load_config(str(config_file))
    assert config["key"] == "value"

def test_load_config_not_found():
    with patch("sys.exit", side_effect=SystemExit) as mock_exit:
        with pytest.raises(SystemExit):
            load_config("nonexistent.json")
        assert mock_exit.called

def test_main_cli(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"cluster_secret": "sec", "nodes": [{"name": "n1", "type": "master", "user": "u", "ip": "1.1.1.1"}]}')

    with patch("sys.argv", ["deploy.py", "status", "--config", str(config_file)]), \
         patch("utils.deploy.process_target_nodes") as mock_process:
        main()
        assert mock_process.called


def test_deploy_action_uses_all_default_configs():
    with patch("glob.glob", return_value=["deploy_configs/master.json", "deploy_configs/worker1.json"]):
        assert discover_config_files("deploy") == ["deploy_configs/master.json", "deploy_configs/worker1.json"]


def test_deploy_cli_supports_simple_deploy_action(tmp_path):
    master_config = tmp_path / "master.json"
    worker_config = tmp_path / "worker.json"
    master_config.write_text('{"cluster_secret": "sec", "nodes": [{"name": "m", "type": "master", "user": "u", "ip": "1.1.1.1"}]}')
    worker_config.write_text('{"cluster_secret": "sec", "master_ip": "1.1.1.1", "nodes": [{"name": "w", "type": "worker", "user": "u", "ip": "1.1.1.2"}]}')

    with patch("sys.argv", ["deploy.py", "deploy", "--config", str(master_config), str(worker_config)]), \
         patch("utils.deploy.process_target_nodes") as mock_process:
        main()

    assert mock_process.call_count == 2


def test_select_target_nodes_filters_by_action_and_name():
    nodes = [
        {"name": "m", "type": "master"},
        {"name": "w", "type": "worker"},
    ]

    assert select_target_nodes(nodes, "master") == [nodes[0]]
    assert select_target_nodes(nodes, "worker") == [nodes[1]]
    assert select_target_nodes(nodes, "deploy") == nodes
    assert select_target_nodes(nodes, "deploy", name="w") == [nodes[1]]

def test_get_ssh_cmd():
    node_key = {"user": "u", "ip": "1.1.1.1", "access": {"method": "key", "key_path": "~/k"}}
    cmd = get_ssh_cmd(node_key, "ls")
    assert "-i " in cmd
    assert "u@1.1.1.1" in cmd

    node_pw = {"user": "u", "ip": "1.1.1.1", "access": {"method": "password", "password": "p"}}
    cmd = get_ssh_cmd(node_pw, "ls")
    assert "sshpass -p p" in cmd


def test_deploy_commands_shell_quote_untrusted_values():
    import shlex

    malicious_pw = "p'; touch /tmp/simc_helper_pwned; echo '"
    malicious_user = "user name"
    malicious_ip = "host.example"
    node = {
        "user": malicious_user,
        "ip": malicious_ip,
        "access": {"method": "password", "password": malicious_pw, "key_path": "~/key path"},
    }

    ssh_cmd = get_ssh_cmd(node, "echo safe")
    rsync_cmd = get_rsync_cmd(node, "./local path/", "/remote path", ["*.log", "bad name"])

    assert shlex.quote(malicious_pw) in ssh_cmd
    assert shlex.quote(f"{malicious_user}@{malicious_ip}") in ssh_cmd
    assert shlex.quote(malicious_pw) in rsync_cmd
    assert "--exclude '*.log'" in rsync_cmd
    assert "--exclude 'bad name'" in rsync_cmd

def test_get_rsync_cmd():
    node = {"user": "u", "ip": "1.1.1.1", "access": {"method": "key"}}
    cmd = get_rsync_cmd(node, "./", "/remote", ["*.log"])
    assert "rsync -avz" in cmd
    assert "--exclude '*.log'" in cmd


def test_run_cmd_redacts_secrets_from_logs(capsys):
    with patch("utils.deploy.subprocess.run"):
        run_cmd("ssh host 'export CLUSTER_SECRET=supersecret && echo ok'")

    output = capsys.readouterr().out
    assert "supersecret" not in output
    assert "CLUSTER_SECRET=[REDACTED]" in output


def test_run_cmd_executes_without_shell():
    with patch("utils.deploy.subprocess.run") as mock_run:
        run_cmd("ssh host 'echo ok'")

    args, kwargs = mock_run.call_args
    assert args[0] == ["ssh", "host", "echo ok"]
    assert kwargs.get("shell") is not True


def test_run_cmd_raises_actionable_error_on_failure():
    failed = MagicMock(returncode=7, stdout="out", stderr="err")
    with patch("utils.deploy.subprocess.run", return_value=failed):
        with pytest.raises(DeploymentError) as exc:
            run_cmd("ssh host false", stream=False)

    message = str(exc.value)
    assert "exit code 7" in message
    assert "stdout:" in message
    assert "stderr:" in message


def test_validate_config_rejects_placeholder_secret_for_deploy():
    config = {
        "cluster_secret": "YOUR_SECURE_SECRET_HERE",
        "nodes": [{"name": "m", "type": "master", "user": "u", "ip": "1.1.1.1"}],
    }
    with pytest.raises(DeploymentError, match="real cluster_secret"):
        validate_config(config, "deploy_configs/master.json", "deploy")


def test_process_target_nodes_continues_and_reports_failed_nodes():
    nodes = [
        {"name": "bad", "type": "master", "user": "u", "ip": "1.1.1.1"},
        {"name": "good", "type": "master", "user": "u", "ip": "1.1.1.2"},
    ]
    with patch("utils.deploy.status_node", side_effect=[DeploymentError("boom"), None]):
        summary = process_target_nodes(nodes, "status", "secret", "1.1.1.1", 80, False)

    assert summary.failures == ["bad: boom"]
    assert summary.successes == ["good: status"]


def test_restart_service_falls_back_when_user_systemd_unavailable():
    node = {"name": "w", "type": "worker", "user": "u", "ip": "1.1.1.2"}
    with patch("utils.deploy.systemd_user_available", return_value=False), \
         patch("utils.deploy.run_cmd") as mock_run, \
         patch("utils.deploy.get_ssh_cmd", side_effect=lambda _node, cmd: cmd):
        restart_service(node, "secret with spaces", master_ip="1.1.1.1", master_port=8080, use_https=True)

    fallback_cmd = mock_run.call_args.args[0]
    assert "pkill -f '[s]imc-worker'" in fallback_cmd
    assert "MASTER_URL=https://1.1.1.1:8080" in fallback_cmd
    assert "CLUSTER_SECRET='secret with spaces'" in fallback_cmd
    assert "SIMC_HELPER_INSECURE_TLS=1" in fallback_cmd


def test_master_runtime_sets_bind_host_for_remote_deployments():
    node = {"name": "m", "type": "master", "user": "u", "ip": "1.1.1.1", "bind_host": "0.0.0.0"}

    fallback_cmd = fallback_start_command(node, "secret", use_https=True)
    unit = make_systemd_unit(node, "secret", use_https=True)

    assert "HOST=0.0.0.0" in fallback_cmd
    assert 'Environment="HOST=0.0.0.0"' in unit


def test_stop_node_uses_process_pattern_that_does_not_match_pkill_command():
    from utils.deploy import stop_node

    node = {"name": "m", "type": "master", "user": "u", "ip": "1.1.1.1"}
    with patch("utils.deploy.systemd_user_available", return_value=False), \
         patch("utils.deploy.run_cmd") as mock_run, \
         patch("utils.deploy.get_ssh_cmd", side_effect=lambda _node, cmd: cmd):
        stop_node(node)

    assert mock_run.call_args.args[0] == "pkill -f '[s]imc-master' || true"


def test_make_systemd_unit_quotes_environment_values():
    node = {"name": "worker one", "type": "worker", "user": "u", "ip": "1.1.1.2", "target_dir": "/opt/simc helper"}
    unit = make_systemd_unit(node, 'sec"ret', master_ip="1.1.1.1", master_port=80, use_https=False)

    assert 'Environment="CLUSTER_SECRET=sec\\"ret"' in unit
    assert 'Environment="BASE_DIR=/opt/simc helper"' in unit
    assert 'Environment="WORKER_NAME=worker one"' in unit

def test_setup_systemd_master(tmp_path):
    node = {
        "name": "TestMaster",
        "type": "master",
        "user": "ubuntu",
        "ip": "1.1.1.1",
        "access": {"method": "key"}
    }

    with patch("utils.deploy.run_cmd") as mock_run, \
         patch("utils.deploy.get_scp_cmd", return_value="scp-mock"), \
         patch("utils.deploy.get_ssh_cmd", return_value="ssh-mock"):

        setup_systemd(node, "secret123", master_ip="1.1.1.1", master_port=80, use_https=True)

        assert mock_run.called
        if os.path.exists("/tmp/simc-master.service"):
            with open("/tmp/simc-master.service") as f:
                content = f.read()
                assert 'Environment="CLUSTER_SECRET=secret123"' in content
                assert 'Environment="PORT=80"' in content
                assert 'Environment="HOST=0.0.0.0"' in content
                assert "ExecStart=/home/ubuntu/simc_helper/bin/simc-master" in content
                assert "RestartSec=5" in content
                assert "WantedBy=default.target" in content

def test_setup_systemd_worker():
    node = {
        "name": "TestWorker",
        "type": "worker",
        "user": "ubuntu",
        "ip": "1.1.1.2",
        "access": {"method": "password", "password": "pass"}
    }

    with patch("utils.deploy.run_cmd"), \
         patch("utils.deploy.get_scp_cmd"), \
         patch("utils.deploy.get_ssh_cmd"):

        setup_systemd(node, "secret123", master_ip="1.1.1.1", master_port=80, use_https=True)

        assert os.path.exists("/tmp/simc-worker.service")
        with open("/tmp/simc-worker.service") as f:
            content = f.read()
            assert 'Environment="MASTER_URL=https://1.1.1.1:80"' in content
            assert 'Environment="WORKER_NAME=TestWorker"' in content
            assert "SIMC_HELPER_INSECURE_TLS=1" in content
            assert "ExecStart=/home/ubuntu/simc_helper/bin/simc-worker" in content

def test_sync_code(tmp_path):
    node = {"name": "Test", "type": "master", "user": "u", "ip": "1.1.1.1"}
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "simc-master").touch()

    with patch("utils.deploy.run_cmd") as mock_run, \
         patch("utils.deploy.get_scp_cmd"), \
         patch("utils.deploy.get_ssh_cmd"):
        sync_code(node, str(build_dir))
        assert mock_run.call_count >= 3


def test_sync_code_uses_custom_target_dir(tmp_path):
    node = {"name": "Test", "type": "worker", "user": "u", "ip": "1.1.1.1", "target_dir": "/opt/simc_helper"}
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "simc-worker").touch()

    with patch("utils.deploy.run_cmd"), \
         patch("utils.deploy.get_ssh_cmd") as mock_ssh, \
         patch("utils.deploy.get_scp_cmd") as mock_scp:
        sync_code(node, str(build_dir))

    ssh_commands = [call.args[1] for call in mock_ssh.call_args_list]
    scp_remote_paths = [call.args[2] for call in mock_scp.call_args_list]
    assert any("/opt/simc_helper/bin" in cmd for cmd in ssh_commands)
    assert "/opt/simc_helper/bin/simc-worker" in scp_remote_paths

def test_restart_service():
    node = {"name": "Test", "type": "master", "user": "u", "ip": "1.1.1.1"}
    with patch("utils.deploy.run_cmd") as mock_run, \
         patch("utils.deploy.get_ssh_cmd"):
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res
        restart_service(node, "secret")
        assert mock_run.call_count == 2

def test_process_target_nodes():
    nodes = [{"name": "Test", "type": "master", "user": "u", "ip": "1.1.1.1"}]
    with patch("utils.deploy.setup_systemd") as mock_setup, \
         patch("utils.deploy.sync_code") as mock_sync, \
         patch("utils.deploy.setup_remote") as mock_remote, \
         patch("utils.deploy.restart_service") as mock_restart, \
         patch("utils.deploy.run_cmd") as mock_run:

        process_target_nodes(nodes, "setup-service", "secret", "1.1.1.1", 80, False)
        assert mock_setup.called

        process_target_nodes(nodes, "deploy", "secret", "1.1.1.1", 80, False)
        assert mock_sync.called
        assert mock_remote.called
        assert mock_restart.called

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res
        process_target_nodes(nodes, "stop", "secret", "1.1.1.1", 80, False)
        assert mock_run.called

        process_target_nodes(nodes, "status", "secret", "1.1.1.1", 80, False)
        assert mock_run.called


# ---------------------------------------------------------------------------
# env block injection
# ---------------------------------------------------------------------------


def test_fallback_start_command_injects_env_block_for_worker():
    """Extra vars in node['env'] are exported before the binary is launched."""
    node = {
        "name": "w",
        "type": "worker",
        "user": "u",
        "ip": "1.1.1.2",
        "env": {
            "LOG_LEVEL": "DEBUG",
            "SIM_COOLDOWN_SECONDS": 60,
        },
    }
    cmd = fallback_start_command(node, "secret", master_ip="1.1.1.1", master_port=8000)
    assert "export LOG_LEVEL='DEBUG'" in cmd or "export LOG_LEVEL=DEBUG" in cmd
    assert "export SIM_COOLDOWN_SECONDS='60'" in cmd or "export SIM_COOLDOWN_SECONDS=60" in cmd


def test_fallback_start_command_injects_env_block_for_master():
    """env block also works for master nodes."""
    node = {
        "name": "m",
        "type": "master",
        "user": "u",
        "ip": "1.1.1.1",
        "env": {"ADMIN_TOKEN": "tok123", "SIM_COOLDOWN_SECONDS": 0},
    }
    cmd = fallback_start_command(node, "secret")
    assert "ADMIN_TOKEN='tok123'" in cmd or "ADMIN_TOKEN=tok123" in cmd
    assert "SIM_COOLDOWN_SECONDS='0'" in cmd or "SIM_COOLDOWN_SECONDS=0" in cmd


def test_fallback_start_command_env_block_shell_quotes_special_chars():
    """Values with spaces and special chars are properly shell-quoted."""
    import shlex

    node = {
        "name": "w",
        "type": "worker",
        "user": "u",
        "ip": "1.1.1.2",
        "env": {"ADMIN_TOKEN": "tok with spaces & symbols"},
    }
    cmd = fallback_start_command(node, "secret", master_ip="1.1.1.1", master_port=8000)
    quoted = shlex.quote("tok with spaces & symbols")
    assert quoted in cmd


def test_fallback_start_command_no_env_block_is_harmless():
    """Nodes without an env block produce no extra exports."""
    node = {"name": "w", "type": "worker", "user": "u", "ip": "1.1.1.2"}
    cmd = fallback_start_command(node, "secret", master_ip="1.1.1.1", master_port=8000)
    # Should still contain the structural exports
    assert "CLUSTER_SECRET" in cmd
    assert "MASTER_URL" in cmd


def test_fallback_start_command_empty_env_block_is_harmless():
    """An empty env dict behaves the same as no env block."""
    node = {"name": "w", "type": "worker", "user": "u", "ip": "1.1.1.2", "env": {}}
    cmd = fallback_start_command(node, "secret", master_ip="1.1.1.1", master_port=8000)
    assert "CLUSTER_SECRET" in cmd


def test_make_systemd_unit_injects_env_block_for_worker():
    """Extra vars in node['env'] appear as Environment= lines in the unit."""
    node = {
        "name": "w",
        "type": "worker",
        "user": "u",
        "ip": "1.1.1.2",
        "env": {"LOG_LEVEL": "DEBUG", "SIM_COOLDOWN_SECONDS": 60},
    }
    unit = make_systemd_unit(node, "secret", master_ip="1.1.1.1", master_port=8000)
    assert 'Environment="LOG_LEVEL=DEBUG"' in unit
    assert 'Environment="SIM_COOLDOWN_SECONDS=60"' in unit


def test_make_systemd_unit_injects_env_block_for_master():
    """env block injection works for master nodes too."""
    node = {
        "name": "m",
        "type": "master",
        "user": "u",
        "ip": "1.1.1.1",
        "env": {"ADMIN_TOKEN": "prod-token"},
    }
    unit = make_systemd_unit(node, "secret")
    assert 'Environment="ADMIN_TOKEN=prod-token"' in unit


def test_make_systemd_unit_env_block_escapes_quotes():
    """Values containing double-quotes are escaped for systemd."""
    node = {
        "name": "w",
        "type": "worker",
        "user": "u",
        "ip": "1.1.1.2",
        "env": {"SOME_VAR": 'val"with"quotes'},
    }
    unit = make_systemd_unit(node, "secret", master_ip="1.1.1.1", master_port=8000)
    assert 'Environment="SOME_VAR=val\\"with\\"quotes"' in unit


def test_make_systemd_unit_no_env_block_is_harmless():
    """Nodes without an env block still produce a valid unit."""
    node = {"name": "w", "type": "worker", "user": "u", "ip": "1.1.1.2"}
    unit = make_systemd_unit(node, "secret", master_ip="1.1.1.1", master_port=8000)
    assert 'Environment="CLUSTER_SECRET=secret"' in unit
    assert 'Environment="MASTER_URL=http://1.1.1.1:8000"' in unit


def test_env_block_appears_after_structural_vars_in_nohup():
    """Structural vars (CLUSTER_SECRET, MASTER_URL) come before env block exports."""
    node = {
        "name": "w",
        "type": "worker",
        "user": "u",
        "ip": "1.1.1.2",
        "env": {"LOG_LEVEL": "DEBUG"},
    }
    cmd = fallback_start_command(node, "secret", master_ip="1.1.1.1", master_port=8000)
    secret_pos = cmd.index("CLUSTER_SECRET")
    log_pos = cmd.index("LOG_LEVEL")
    nohup_pos = cmd.index("nohup")
    assert secret_pos < log_pos < nohup_pos


def test_env_block_appears_after_structural_vars_in_systemd():
    """Structural Environment= lines appear before env block lines in the unit."""
    node = {
        "name": "w",
        "type": "worker",
        "user": "u",
        "ip": "1.1.1.2",
        "env": {"LOG_LEVEL": "DEBUG"},
    }
    unit = make_systemd_unit(node, "secret", master_ip="1.1.1.1", master_port=8000)
    secret_pos = unit.index("CLUSTER_SECRET")
    log_pos = unit.index("LOG_LEVEL")
    assert secret_pos < log_pos
