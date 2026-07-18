# Deployment Guide

The deployer (`utils/deploy.py`) supports exactly two installation topologies. A `local` deployment runs commands and copies binaries directly on the machine where you invoke the deployer; it never calls SSH or SCP. A `remote` deployment reaches installation nodes over SSH. Both use user-level systemd when available, with a `nohup` fallback.

## 1. Choose an installation mode

Copy one complete, unified config:

```bash
mkdir -p deploy_configs

# Master and worker processes on the same installation node
cp examples/deploy_local.example.json deploy_configs/installation.json

# Or: master on one node and worker(s) on other nodes
cp examples/deploy_remote.example.json deploy_configs/installation.json
```

`installation_mode` is validated before deployment:

| Mode | Required topology | Worker connection |
| :--- | :--- | :--- |
| `local` | Exactly one master and at least one worker with the same `target_dir`. `user`, `ip`, and `access` are optional and default locally. | Automatically uses `127.0.0.1:<master port>`. |
| `remote` | Exactly one master and at least one worker; workers must not share the master's installation location. | Uses the master's configured `ip` and `port`. |

Configs without `installation_mode` remain supported for compatibility but do not receive topology checks.

## 2. Compilation

Build standalone binaries inside the `build/` directory before deploying:

```bash
# Package all binaries with test verification
cmake -S . -B build -DBUILD_WITH_TESTS=ON -DPYINSTALLER_CLEAN=ON
cmake --build build --target verified_package_all

# Iterative target compilation
cmake --build build --target simc_master
cmake --build build --target simc_worker
```

---

## 3. Command Reference

```bash
# Verify configs, tools, and remote SSH credentials
python3 utils/deploy.py doctor --config deploy_configs/installation.json

# Deploy both master and worker nodes with preflight checks
python3 utils/deploy.py deploy --preflight --config deploy_configs/installation.json

# Also clone/build the SimulationCraft engine for worker nodes
python3 utils/deploy.py deploy --preflight --install-simc --config deploy_configs/installation.json

# Deploy specific configurations or names
python3 utils/deploy.py master --config deploy_configs/installation.json
python3 utils/deploy.py worker --name Worker1 --config deploy_configs/installation.json

# Service control
python3 utils/deploy.py status
python3 utils/deploy.py stop
python3 utils/deploy.py setup-service
```

### Action Reference

| Action | Mutates Host | Description |
| :--- | :--- | :--- |
| `doctor` | No | Runs local/remote checks on keys, connection ports, directories, and assets. |
| `deploy` | Yes | Discovers configs, stops target nodes, copies new binaries, and restarts processes. |
| `master` | Yes | Deploys only nodes configured with `type: "master"`. |
| `worker` | Yes | Deploys only nodes configured with `type: "worker"`. |
| `simc` | Yes | Executes remote SimulationCraft engine compile on worker nodes. |
| `setup-service`| Yes | Installs user-level systemd service configs. |
| `status` | No | Evaluates running status using `systemctl --user` or `pgrep`. |
| `stop` | Yes | Safely terminates running processes. |

### Deployment Flags

| Flag | Default | Description |
| :--- | :--- | :--- |
| `--config <files>` | `deploy_configs/*.json` | Explicit paths to target configuration files. |
| `--build-dir <dir>` | `build` | Directory where compiled binaries reside. |
| `--skip-build` | None | Reuse existing binaries from the platform build directory (or `--build-dir`). |
| `--install-simc` | None | Clone/build or update SimulationCraft on deployed worker nodes. |
| `--name <name>` | None | Limits execution to a single node name. |
| `--preflight` | None | Runs tool/binary validation checks immediately before mutating hosts. |
| `--fail-fast` | None | Halts deployment immediately on the first node error. |
| `--allow-placeholder-secret` | None | Permits placeholder keys (useful for testing on local environments). |

---

## 4. Service Models

`utils/deploy.py` attempts systemd-user daemon configurations, falling back to a `nohup` wrapper if systemd is unavailable:

```text
Host check ──> systemctl --user is functional?
                ├── Yes ──> Install ~/.config/systemd/user/simc-master.service
                └── No  ──> Run under nohup in background, outputs to logs/<role>.out
```

*To enable systemd persistent execution after logout, ensure `loginctl enable-linger <user>` is run on the host system.*
