# Deployment Guide

The deployer (`utils/deploy.py`) orchestrates binaries on remote systems. It targets user-space folders, avoids root permissions, and uses user-level systemd services (with a `nohup` daemon fallback).

---

## 1. Compilation

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

## 2. Command Reference

```bash
# Verify configs, tools, and remote SSH credentials
python3 utils/deploy.py doctor

# Deploy both master and worker nodes with preflight checks
python3 utils/deploy.py deploy --preflight

# Deploy specific configurations or names
python3 utils/deploy.py master --config deploy_configs/master.json
python3 utils/deploy.py worker --name Worker1

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
| `--name <name>` | None | Limits execution to a single node name. |
| `--preflight` | None | Runs tool/binary validation checks immediately before mutating hosts. |
| `--fail-fast` | None | Halts deployment immediately on the first node error. |
| `--allow-placeholder-secret` | None | Permits placeholder keys (useful for testing on local environments). |

---

## 3. Service Models

`utils/deploy.py` attempts systemd-user daemon configurations, falling back to a `nohup` wrapper if systemd is unavailable:

```text
Host check ──> systemctl --user is functional?
                ├── Yes ──> Install ~/.config/systemd/user/simc-master.service
                └── No  ──> Run under nohup in background, outputs to logs/<role>.out
```

*To enable systemd persistent execution after logout, ensure `loginctl enable-linger <user>` is run on the host system.*
