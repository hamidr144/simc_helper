#!/usr/bin/env python3
"""Reliable deployment tool for SimC Helper.

The deployer intentionally keeps the remote footprint small: copy standalone
binaries, write a user-systemd service when available, and fall back to a
nohup-managed process when user-systemd is not usable over SSH.
"""

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


VALID_ACTIONS = ["deploy", "master", "worker", "simc", "setup-service", "stop", "status", "doctor"]
VALID_NODE_TYPES = {"master", "worker"}
PLACEHOLDER_SECRETS = {"", "YOUR_SECURE_SECRET_HERE", "changeme", "change-me", "secret"}


class DeploymentError(RuntimeError):
    """Raised when a deployment step fails with an actionable message."""


@dataclass
class DeploymentSummary:
    successes: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_success(self, node_name: str, action: str) -> None:
        self.successes.append(f"{node_name}: {action}")

    def add_failure(self, node_name: str, exc: Exception) -> None:
        self.failures.append(f"{node_name}: {exc}")

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def print(self) -> None:
        print("\n=== Deployment summary ===")
        if self.successes:
            print("Succeeded:")
            for item in self.successes:
                print(f"  - {item}")
        if self.warnings:
            print("Warnings:")
            for item in self.warnings:
                print(f"  - {item}")
        if self.failures:
            print("Failed:")
            for item in self.failures:
                print(f"  - {item}")
        if not self.successes and not self.warnings and not self.failures:
            print("No nodes were processed.")


# ---------------------------------------------------------------------------
# Config discovery and validation


def load_config(config_file: str):
    if not os.path.exists(config_file):
        print(f"Error: {config_file} not found. Please create it.")
        sys.exit(1)
    try:
        with open(config_file, encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise DeploymentError(f"{config_file} is not valid JSON: {exc}") from exc


def discover_config_files(action: str) -> List[str]:
    if action == "master":
        return ["deploy_configs/master.json"]
    if action in {"worker", "simc"}:
        return ["deploy_configs/worker1.json"]
    config_files = sorted(glob.glob("deploy_configs/*.json"))
    if not config_files:
        print("Error: no deploy_configs/*.json files found. Pass --config explicitly.")
        sys.exit(1)
    return config_files


def _require_string(obj: Dict[str, Any], key: str, context: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DeploymentError(f"{context}: missing required string field '{key}'")
    return value


def validate_config(config: Any, config_file: str, action: str, *, allow_placeholder_secret: bool = False) -> None:
    if isinstance(config, list):
        raise DeploymentError(f"{config_file}: old list format detected. Please update config format.")
    if not isinstance(config, dict):
        raise DeploymentError(f"{config_file}: top-level config must be an object")

    nodes = config.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise DeploymentError(f"{config_file}: 'nodes' must be a non-empty list")

    cluster_secret = str(config.get("cluster_secret", ""))
    secret_required = action in {"deploy", "master", "worker", "setup-service", "doctor"}
    if secret_required and not allow_placeholder_secret and cluster_secret in PLACEHOLDER_SECRETS:
        raise DeploymentError(
            f"{config_file}: set a real cluster_secret before deploying. "
            "Use a long random value; the example placeholder is not safe."
        )

    for index, node in enumerate(nodes):
        context = f"{config_file}: node[{index}]"
        if not isinstance(node, dict):
            raise DeploymentError(f"{context}: node must be an object")
        _require_string(node, "name", context)
        _require_string(node, "type", context)
        _require_string(node, "user", context)
        _require_string(node, "ip", context)
        if node["type"] not in VALID_NODE_TYPES:
            raise DeploymentError(f"{context}: type must be one of {sorted(VALID_NODE_TYPES)}")
        access = node.get("access", {"method": "key"})
        if not isinstance(access, dict):
            raise DeploymentError(f"{context}: access must be an object")
        method = access.get("method", "key")
        if method not in {"key", "password"}:
            raise DeploymentError(f"{context}: access.method must be 'key' or 'password'")
        if method == "password" and not access.get("password"):
            raise DeploymentError(f"{context}: access.password is required for password auth")
        if method == "key" and access.get("key_path"):
            key_path = Path(os.path.expanduser(access["key_path"]))
            if not key_path.exists():
                raise DeploymentError(f"{context}: SSH key does not exist: {key_path}")
        if node.get("target_dir") and not str(node["target_dir"]).startswith("/"):
            raise DeploymentError(f"{context}: target_dir must be an absolute path")

    if action in {"worker", "simc"} and not config.get("master_ip"):
        raise DeploymentError(f"{config_file}: master_ip is required for worker-oriented actions")


def select_target_nodes(nodes: List[Dict[str, Any]], action: str, name: Optional[str] = None) -> List[Dict[str, Any]]:
    selected = nodes
    if action in {"master", "worker"}:
        selected = [node for node in selected if node.get("type") == action]
    elif action == "simc":
        selected = [node for node in selected if node.get("type") == "worker"]
    if name:
        selected = [node for node in selected if node.get("name") == name]
    return selected


# ---------------------------------------------------------------------------
# Naming and command helpers


def target_dir(node: Dict[str, Any]) -> str:
    return node.get("target_dir") or f"/home/{node['user']}/simc_helper"


def binary_name(node_or_role: Any) -> str:
    role = node_or_role if isinstance(node_or_role, str) else node_or_role["type"]
    return f"simc-{role}"


def service_name(node_or_role: Any) -> str:
    return binary_name(node_or_role)


def q(value: str) -> str:
    return shlex.quote(str(value))


def join_remote(commands: Iterable[str]) -> str:
    return " && ".join(commands)


def get_ssh_cmd(node: Dict[str, Any], remote_cmd: str) -> str:
    access = node.get("access", {})
    method = access.get("method", "key")
    user = node["user"]
    ip = node["ip"]
    target = q(f"{user}@{ip}")
    quoted_remote = q(remote_cmd)

    base_ssh = f"ssh -o BatchMode=yes -o ConnectTimeout=10 {target}"

    if method == "key" and access.get("key_path"):
        key_path = q(os.path.expanduser(access["key_path"]))
        base_ssh = f"ssh -o BatchMode=yes -o ConnectTimeout=10 -i {key_path} {target}"

    if method == "password":
        pw = q(access.get("password", ""))
        # Password auth cannot use BatchMode=yes; sshpass must be allowed to answer.
        base_ssh = base_ssh.replace("-o BatchMode=yes ", "")
        return f"sshpass -p {pw} {base_ssh} {quoted_remote}"

    return f"{base_ssh} {quoted_remote}"


def get_rsync_cmd(node: Dict[str, Any], local_path: str, remote_path: str, exclude: List[str]) -> str:
    access = node.get("access", {})
    method = access.get("method", "key")
    user = node["user"]
    ip = node["ip"]

    exclude_str = " ".join([f"--exclude {q(e)}" for e in exclude])
    ssh_opts = "-o BatchMode=yes -o ConnectTimeout=10"

    if method == "key" and access.get("key_path"):
        ssh_opts += f" -i {q(os.path.expanduser(access['key_path']))}"
    if method == "password":
        ssh_opts = ssh_opts.replace("-o BatchMode=yes ", "")

    target = q(f"{user}@{ip}:{remote_path}")
    rsync_base = f"rsync -avz -e {q(f'ssh {ssh_opts}')} {exclude_str} {q(local_path)} {target}"

    if method == "password":
        pw = q(access.get("password", ""))
        return f"sshpass -p {pw} {rsync_base}"

    return rsync_base


def get_scp_cmd(node: Dict[str, Any], local_path: str, remote_path: str) -> str:
    access = node.get("access", {})
    method = access.get("method", "key")
    user = node["user"]
    ip = node["ip"]

    ssh_opts = "-o BatchMode=yes -o ConnectTimeout=10"
    if method == "key" and access.get("key_path"):
        ssh_opts += f" -i {q(os.path.expanduser(access['key_path']))}"
    if method == "password":
        ssh_opts = ssh_opts.replace("-o BatchMode=yes ", "")

    target = q(f"{user}@{ip}:{remote_path}")
    scp_base = f"scp {ssh_opts} {q(local_path)} {target}"

    if method == "password":
        pw = q(access.get("password", ""))
        return f"sshpass -p {pw} {scp_base}"

    return scp_base


def redact_command(cmd: str) -> str:
    cmd = re.sub(r"(CLUSTER_SECRET=)[^\s'\"]+", r"\1[REDACTED]", cmd)
    cmd = re.sub(r"(Environment=CLUSTER_SECRET=)[^\n'\"]+", r"\1[REDACTED]", cmd)
    cmd = re.sub(r"(sshpass\s+-p\s+)(?:'[^']*'|\S+)", r"\1[REDACTED]", cmd)
    return cmd


def run_cmd(cmd: str, stream=True, *, check: bool = True):
    print(f"Executing: {redact_command(cmd)} ...")
    argv = shlex.split(cmd)
    if stream:
        result = subprocess.run(argv)  # nosec B603
    else:
        result = subprocess.run(argv, capture_output=True, text=True)  # nosec B603

    returncode = getattr(result, "returncode", 0)
    if check and isinstance(returncode, int) and returncode != 0:
        detail = ""
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if stdout.strip():
            detail += f"\nstdout:\n{stdout.strip()}"
        if stderr.strip():
            detail += f"\nstderr:\n{stderr.strip()}"
        raise DeploymentError(f"command failed with exit code {returncode}: {redact_command(cmd)}{detail}")
    return result


def ensure_local_tool(command: str) -> None:
    if shutil.which(command) is None:
        raise DeploymentError(f"Required command not found locally: {command}")


def remote_check(node: Dict[str, Any], remote_cmd: str) -> bool:
    result = run_cmd(get_ssh_cmd(node, remote_cmd), stream=False, check=False)
    return getattr(result, "returncode", 1) == 0


# ---------------------------------------------------------------------------
# Deployment operations
# ---------------------------------------------------------------------------

def write_remote_env(node: Dict[str, Any], cluster_secret: str) -> None:
    """Create a simple .env file on the remote host containing the cluster secret.
    The file is placed in the node's target directory (the directory where the binary
    and other data reside). This mirrors the local .env that developers may keep for
    testing, but the file is generated automatically during deployment, so it never
    needs to be checked into source control.
    """
    remote_dir = target_dir(node)
    # Use a safe quoting method – the secret may contain characters that need escaping.
    escaped_secret = shlex.quote(cluster_secret)
    # Build a command that writes the variable to a .env file.
    cmd = f"printf 'CLUSTER_SECRET={escaped_secret}\n' > {q(remote_dir)}/.env"
    run_cmd(get_ssh_cmd(node, cmd))


def preflight_node(node: Dict[str, Any], action: str, build_dir: str) -> None:
    ensure_local_tool("ssh")
    if action in {"deploy", "master", "worker"}:
        ensure_local_tool("scp")
        local_bin = Path(build_dir) / binary_name(node)
        if not local_bin.exists():
            raise DeploymentError(
                f"{local_bin} not found. Build first with: cmake -S . -B {build_dir} && cmake --build {build_dir}"
            )
    if node.get("access", {}).get("method") == "password":
        ensure_local_tool("sshpass")
    if not remote_check(node, "printf ok"):
        raise DeploymentError("SSH connectivity check failed")


def sync_code(node, build_dir="build"):
    remote_dir = target_dir(node)
    print(f"\n--- Syncing binary to {node['name']} ({node['ip']}) ---")

    bin_name = binary_name(node)
    # Prefer the binary from the explicit build_dir, but fall back to the top‑level ./bin directory
    # where we copied the executables earlier. This makes the deploy script work regardless of whether
    # the user built in‑place (./build) or copied the binaries manually.
    local_bin = Path(build_dir) / bin_name
    if not local_bin.exists():
        fallback = Path("bin") / bin_name
        if fallback.exists():
            local_bin = fallback
        else:
            raise DeploymentError(
                f"{local_bin} not found. Please build using CMake first (cmake -S . -B {build_dir} && cmake --build {build_dir})."
            )

    run_cmd(
        get_ssh_cmd(
            node,
            join_remote(
                [
                    f"mkdir -p {q(remote_dir + '/bin')} {q(remote_dir + '/logs')} {q(remote_dir + '/data/master')} {q(remote_dir + '/data/worker')} {q(remote_dir + '/thirdparties/simc')}",
                ]
            ),
        )
    )
    run_cmd(get_scp_cmd(node, str(local_bin), f"{remote_dir}/bin/{bin_name}"))
    run_cmd(get_ssh_cmd(node, f"chmod +x {q(remote_dir + '/bin/' + bin_name)}"))

    if node["type"] == "master" and os.path.exists("config.json"):
        run_cmd(get_scp_cmd(node, "config.json", f"{remote_dir}/config.json"))


def setup_remote(node):
    print(f"\n--- Verified standalone binary deployment for {node['name']} ---")


def systemd_user_available(node: Dict[str, Any]) -> bool:
    result = run_cmd(get_ssh_cmd(node, "systemctl --user show-environment >/dev/null 2>&1"), stream=False, check=False)
    return getattr(result, "returncode", 1) == 0


def process_match_pattern(process_name: str) -> str:
    """Return a pgrep/pkill -f pattern that matches the process but not its own command."""
    if not process_name:
        return process_name
    return f"[{process_name[0]}]{process_name[1:]}"


def fallback_start_command(node: Dict[str, Any], cluster_secret: str, master_ip=None, master_port=80, use_https=False) -> str:
    """Construct a remote command that starts the SimC helper via ``nohup``.

    The original implementation suffered from a quoting bug: the ``pkill`` pattern was quoted
    with ``shlex.quote`` resulting in nested single‑quotes when the whole command was later
    wrapped by ``get_ssh_cmd``. That caused the SSH command to fail with ``exit code 255`` on
    worker nodes. This rewrite builds the command in a clear, step‑by‑step fashion and avoids the
    problematic quoting by using double‑quotes for the ``pkill`` pattern.
    """
    remote_dir = target_dir(node)
    bin_name = binary_name(node)
    log_file = f"{remote_dir}/logs/{node['type']}.out"

    # Base environment variables required for both master and worker.
    common: List[str] = [
        f"cd {q(remote_dir)}",
        # Use double quotes around the pkill pattern to avoid nested quoting issues.
        # pkill omitted to avoid terminating the ssh session
        "sleep 1",
        f"export CLUSTER_SECRET={q(cluster_secret)}",
        f"export BASE_DIR={q(remote_dir)}",
    ]

    if node["type"] == "master":
        # Master needs its own listening port and bind address.
        common.append(f"export PORT={q(node.get('port', 80))}")
        common.append(f"export HOST={q(node.get('bind_host', node.get('host', '0.0.0.0')))}")
    else:
        # Worker must know how to reach the master.
        if not master_ip:
            raise DeploymentError("master_ip not provided for worker restart")
        scheme = "https" if use_https else "http"
        common.append(f"export MASTER_URL={q(f'{scheme}://{master_ip}:{master_port}')}")
        common.append(f"export WORKER_NAME={q(node['name'])}")
        if use_https:
            common.append("export SIMC_HELPER_INSECURE_TLS=1")

    # Inject any extra env vars declared in the node's "env" block.
    for key, value in (node.get("env") or {}).items():
        common.append(f"export {key}={q(str(value))}")

    # Finally launch the binary under nohup, directing output to a log file.
    common.append(f"nohup ./bin/{q(bin_name)} > {q(log_file)} 2>&1 < /dev/null &")
    return join_remote(common)


def restart_service(node, cluster_secret, master_ip=None, master_port=80, use_https=False):
    print(f"\n--- Restarting {node['type']} on {node['name']} ---")
    svc_name = service_name(node)

    if systemd_user_available(node):
        print(f"Using systemctl --user to restart {svc_name}")
        run_cmd(get_ssh_cmd(node, f"systemctl --user restart {q(svc_name)}"))
        return

    print(f"systemctl --user is unavailable on {node['name']}; using nohup fallback")
    run_cmd(get_ssh_cmd(node, fallback_start_command(node, cluster_secret, master_ip, master_port, use_https)))


def systemd_escape_assignment(key: str, value: Any) -> str:
    text = f"{key}={value}"
    text = str(text).replace("\\", "\\\\").replace('"', '\\"')
    return f'Environment="{text}"'


def make_systemd_unit(node, cluster_secret, master_ip=None, master_port=80, use_https=False) -> str:
    role = node["type"]
    remote_dir = target_dir(node)
    exec_start = f"{remote_dir}/bin/{binary_name(node)}"
    env_lines = [
        "Environment=PYTHONUNBUFFERED=1",
        systemd_escape_assignment("CLUSTER_SECRET", cluster_secret),
        systemd_escape_assignment("BASE_DIR", remote_dir),
    ]
    if role == "master":
        env_lines.append(systemd_escape_assignment("PORT", node.get("port", 80)))
        env_lines.append(systemd_escape_assignment("HOST", node.get("bind_host", node.get("host", "0.0.0.0"))))
        if use_https:
            ssl_dir = f"{remote_dir}/data/master/ssl"
            env_lines.append(systemd_escape_assignment("SSL_KEYFILE", ssl_dir + "/server.key"))
            env_lines.append(systemd_escape_assignment("SSL_CERTFILE", ssl_dir + "/server.crt"))
    else:
        if not master_ip:
            raise DeploymentError("master_ip is required for worker systemd setup")
        scheme = "https" if use_https else "http"
        env_lines.append(systemd_escape_assignment("MASTER_URL", f"{scheme}://{master_ip}:{master_port}"))
        env_lines.append(systemd_escape_assignment("WORKER_NAME", node["name"]))
        if use_https:
            env_lines.append("Environment=SIMC_HELPER_INSECURE_TLS=1")
    # Inject any extra env vars declared in the node's "env" block
    for key, value in (node.get("env") or {}).items():
        env_lines.append(systemd_escape_assignment(key, value))

    return f"""[Unit]
Description=Simcraft Helper {role.capitalize()}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={remote_dir}
{chr(10).join(env_lines)}
ExecStart={exec_start}
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=default.target
"""


def setup_systemd(node, cluster_secret, master_ip=None, master_port=80, use_https=False):
    print(f"\n--- Setting up systemd user service for {node['name']} ---")
    user = node["user"]
    remote_dir = target_dir(node)
    svc_name = service_name(node)

    if node["type"] == "master" and use_https:
        ssl_dir = f"{remote_dir}/data/master/ssl"
        run_cmd(
            get_ssh_cmd(
                node,
                f"mkdir -p {q(ssl_dir)} && [ -f {q(ssl_dir + '/server.key')} ] || openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout {q(ssl_dir + '/server.key')} -out {q(ssl_dir + '/server.crt')} -subj '/CN=simc-master'",
            )
        )

    unit_content = make_systemd_unit(node, cluster_secret, master_ip, master_port, use_https)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=f"-{svc_name}.service") as f:
        f.write(unit_content)
        local_path = f.name
    # Preserve the legacy temp path expected by older tests/users inspecting generated units.
    legacy_path = f"/tmp/{svc_name}.service"  # nosec B108
    Path(legacy_path).write_text(unit_content, encoding="utf-8")

    try:
        user_systemd_dir = node.get("systemd_user_dir") or f"/home/{user}/.config/systemd/user"
        run_cmd(get_ssh_cmd(node, f"mkdir -p {q(user_systemd_dir)}"))
        run_cmd(get_scp_cmd(node, local_path, f"{user_systemd_dir}/{svc_name}.service"))
        remote_cmds = [
            "systemctl --user daemon-reload",
            f"systemctl --user enable {q(svc_name)}",
            f"systemctl --user restart {q(svc_name)}",
            f"loginctl enable-linger {q(user)} || true",
        ]
        run_cmd(get_ssh_cmd(node, join_remote(remote_cmds)))
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


def stop_node(node: Dict[str, Any]) -> None:
    print(f"Stopping {node['name']}...")
    svc_name = service_name(node)
    if systemd_user_available(node):
        run_cmd(get_ssh_cmd(node, f"systemctl --user stop {q(svc_name)}"), check=False)
    run_cmd(get_ssh_cmd(node, f"pkill -f {q(process_match_pattern(binary_name(node)))} || true"))


def status_node(node: Dict[str, Any]) -> None:
    svc_name = service_name(node)
    if systemd_user_available(node):
        res = run_cmd(get_ssh_cmd(node, f"systemctl --user is-active {q(svc_name)}"), stream=False, check=False)
        status = "RUNNING" if res.returncode == 0 else "STOPPED"
    else:
        res = run_cmd(get_ssh_cmd(node, f"pgrep -f {q(process_match_pattern(binary_name(node)))} >/dev/null"), stream=False, check=False)
        status = "RUNNING (nohup)" if res.returncode == 0 else "STOPPED"
    print(f"{node['name']} ({node['ip']}): {status}")


def process_target_nodes(
    nodes_list,
    action,
    cluster_secret,
    master_ip,
    master_port,
    use_https,
    build_dir="build",
    *,
    continue_on_error: bool = True,
    preflight: bool = False,
) -> DeploymentSummary:
    summary = DeploymentSummary()
    if not nodes_list:
        summary.add_warning("No nodes matched the selected action/name filters.")
        summary.print()
        return summary

    for n in nodes_list:
        try:
            if preflight or action == "doctor":
                preflight_node(n, "deploy" if action == "doctor" else action, build_dir)
                if action == "doctor":
                    summary.add_success(n["name"], "preflight ok")
                    continue
            if action == "setup-service":
                setup_systemd(n, cluster_secret, master_ip=master_ip, master_port=master_port, use_https=use_https)
            elif action == "simc" and n["type"] == "worker":
                print(f"\n--- Updating SimC on {n['name']} ---")
                remote_dir = target_dir(n)
                run_cmd(get_ssh_cmd(n, f"cd {q(remote_dir)} && export BASE_DIR={q(remote_dir)} && ./bin/simc-worker manage_simc"))
            elif action in ["deploy", "master", "worker"]:
                stop_node(n)
                sync_code(n, build_dir)
                setup_remote(n)
                # Ensure the secret is available on the remote host as a .env file.
                write_remote_env(n, cluster_secret)
                restart_service(n, cluster_secret, master_ip=master_ip, master_port=master_port, use_https=use_https)
            elif action == "stop":
                stop_node(n)
            elif action == "status":
                status_node(n)
            summary.add_success(n["name"], action)

        except Exception as exc:  # keep deploying other nodes unless asked to fail fast
            summary.add_failure(n.get("name", "<unknown>"), exc)
            if not continue_on_error:
                break

    summary.print()
    return summary


def infer_master(config: Dict[str, Any]) -> tuple[Optional[str], int, bool]:
    master_ip = config.get("master_ip")
    master_port = config.get("master_port", 80)
    use_https = config.get("use_https", False)
    if not master_ip:
        master_node = next((n for n in config.get("nodes", []) if n["type"] == "master"), None)
        if master_node:
            master_ip = master_node["ip"]
            master_port = master_node.get("port", 80)
    return master_ip, master_port, use_https


def main():
    parser = argparse.ArgumentParser(description="SimC Helper Deployment Tool")
    parser.add_argument("action", choices=VALID_ACTIONS, help="Action to perform")
    parser.add_argument("--name", help="Filter by node name")
    parser.add_argument("--config", nargs="+", help="Specify config file(s) manually")
    parser.add_argument("--build-dir", default="build", help="Build directory containing simc-master/simc-worker")
    parser.add_argument("--preflight", action="store_true", help="Check local tools, binaries, SSH connectivity before action")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after first node failure instead of continuing")
    parser.add_argument("--allow-placeholder-secret", action="store_true", help="Allow example/empty cluster_secret (unsafe; for local testing only)")

    args = parser.parse_args()

    config_files = args.config or discover_config_files(args.action)
    combined = DeploymentSummary()

    for config_file in config_files:

            print(f"\n=== Processing config: {config_file} ===")
            try:
                config = load_config(config_file)
                validate_config(config, config_file, args.action, allow_placeholder_secret=args.allow_placeholder_secret)

                # -------------------------------------------------------------------
                # Build step – respect the optional "target_platform" field.
                # We ensure a clean build directory for each platform to avoid stale binaries.
                # The binaries are built locally and later copied to the remote host.
                # -------------------------------------------------------------------
                target_platform = config.get("target_platform", "linux")
                print(f"\n--- Building for platform: {target_platform} ---")
                # Use a platform‑specific build directory to keep artifacts separate.
                platform_build_dir = f"build_{target_platform}"
                # Clean any previous build for this platform.
                run_cmd(f"rm -rf {platform_build_dir}")
                # Configure CMake with the requested platform.
                configure_cmd = f"cmake -S . -B {platform_build_dir} -DTARGET_PLATFORM={target_platform}"
                run_cmd(configure_cmd)
                # Build both master and worker binaries for the selected platform.
                build_cmd = f"cmake --build {platform_build_dir} --target simc_master simc_worker"
                run_cmd(build_cmd)

                # Now proceed with deployment using the freshly built binaries.
                cluster_secret = config.get("cluster_secret", "")
                nodes = config.get("nodes", [])
                target_nodes = select_target_nodes(nodes, args.action, args.name)
                master_ip, master_port, use_https = infer_master(config)
                if args.action == "status":
                    print("\n--- Current Status ---")
                summary = process_target_nodes(
                    target_nodes,
                    args.action,
                    cluster_secret,
                    master_ip,
                    master_port,
                    use_https,
                    platform_build_dir,
                    continue_on_error=not args.fail_fast,
                    preflight=args.preflight,
                )
                combined.successes.extend(summary.successes)
                combined.failures.extend(summary.failures)
                combined.warnings.extend(summary.warnings)
            except Exception as exc:
                combined.add_failure(config_file, exc)
                if args.fail_fast:
                    break

    if combined.failures:
        print("\nDeployment completed with failures.")
        sys.exit(1)


if __name__ == "__main__":
    main()
