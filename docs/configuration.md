# Configuration

Simcraft Helper uses local JSON files (ignored by git) for runtime config and secrets. Start from the safe templates in `examples/`.

---

## 1. Local Simulation Config (`config.json`)

Stores the items, gems, and enchants available to test. Copy from the example:

```bash
cp examples/config.example.json config.json
```

```json
{
  "enchantments": {
    "chest": ["enchant_id=6625"],
    "finger": ["enchant_id=6592"]
  },
  "gems": {
    "meta": [191983],
    "standard": [191963, 191964]
  }
}
```

*Empty arrays bypass testing for that specific slot.*

---

## 2. Deployment Config (`deploy_configs/*.json`)

Describes SSH targets, directories, cluster keys, and runtime env vars for each node. Copy from the examples:

```bash
mkdir -p deploy_configs
cp examples/deploy_master.example.json deploy_configs/master.json
cp examples/deploy_worker.example.json deploy_configs/worker1.json
```

Full schema example (master + worker in one file):

```json
{
  "cluster_secret": "replace-with-a-long-random-secret",
  "master_ip": "master.example.local",
  "master_port": 8000,
  "use_https": false,
  "nodes": [
    {
      "name": "PrimaryMaster",
      "type": "master",
      "ip": "master.example.local",
      "port": 8000,
      "bind_host": "0.0.0.0",
      "user": "deploy",
      "target_dir": "/opt/simc_helper",
      "access": {
        "method": "key",
        "key_path": "~/.ssh/id_ed25519"
      },
      "env": {
        "ADMIN_TOKEN": "replace-with-a-long-random-token",
        "LOG_LEVEL": "INFO",
        "SIM_COOLDOWN_SECONDS": 300
      }
    },
    {
      "name": "Worker1",
      "type": "worker",
      "ip": "worker1.example.local",
      "user": "deploy",
      "target_dir": "/opt/simc_helper",
      "access": {
        "method": "key",
        "key_path": "~/.ssh/id_ed25519"
      },
      "env": {
        "LOG_LEVEL": "INFO",
        "SIM_COOLDOWN_SECONDS": 300,
        "SIMC_UPDATE_INTERVAL_SECONDS": 86400
      }
    }
  ]
}
```

### Parameter Reference

| Parameter | Scope | Required | Description |
| :--- | :--- | :--- | :--- |
| `cluster_secret` | Global | Yes | Shared authentication token between master and all workers. |
| `master_ip` | Global | Worker configs | IP/hostname workers connect to. |
| `master_port` | Global | No | Master HTTP/WebSocket port (Default: `8000`). |
| `use_https` | Global | No | Generate a self-signed cert and use HTTPS/WSS URLs. |
| `nodes.name` | Node | Yes | Identifier shown in CLI output and status commands. |
| `nodes.type` | Node | Yes | `master` or `worker`. |
| `nodes.ip` | Node | Yes | Remote host SSH address. |
| `nodes.user` | Node | Yes | Remote SSH username. |
| `nodes.port` | Node | Master only | Listen port override. |
| `nodes.bind_host` | Node | Master only | Bind IP (Default: `0.0.0.0`). |
| `nodes.target_dir` | Node | No | Remote install directory (Default: `/home/<user>/simc_helper`). |
| `nodes.access.method` | Node | No | `key` (default) or `password`. |
| `nodes.access.key_path` | Node | key only | Path to SSH private key (e.g. `~/.ssh/id_ed25519`). |
| `nodes.access.password` | Node | password only | SSH password (requires `sshpass` on the local machine). |
| `nodes.env` | Node | No | Key/value map of extra env vars injected at startup. Use this instead of a `.env` file on the remote node. |

> [!TIP]
> The `env` block is the canonical place for all runtime tuning. The deploy tool injects these automatically — via `export` for nohup and `Environment=` for systemd — so no `.env` file is needed on deployed nodes.

---

## 3. Environment Variables

All vars are read by `src/core/config.py` at startup. Defaults are shown; unset optional vars are skipped.

| Variable | Target | Default | Description |
| :--- | :--- | :--- | :--- |
| `BASE_DIR` | Both | `.` | Root directory for logs, SQLite DB, and data subdirs. |
| `PORT` | Master | `8000` | HTTP server bind port. |
| `HOST` | Master | `127.0.0.1` | Bind host. Use `0.0.0.0` to accept external connections. |
| `SSL_KEYFILE` | Master | — | Path to TLS private key (PEM). Required for HTTPS. |
| `SSL_CERTFILE` | Master | — | Path to TLS certificate (PEM). Required for HTTPS. |
| `CORS_ALLOWED_ORIGINS` | Master | — | Comma-separated or JSON array of allowed CORS origins. |
| `ADMIN_TOKEN` | Master | — | Guards `/api/update-simc`, `/api/stop-simulation`, and `/api/shutdown`. |
| `CLUSTER_SECRET` | Both | Ephemeral | Shared WebSocket auth key. An ephemeral key is generated if unset (workers cannot reconnect after a restart). |
| `MASTER_URL` | Worker | `http://localhost:8000` | URL the worker connects to. |
| `WORKER_NAME` | Worker | `LocalWorker` | Worker identifier shown in the dashboard. |
| `SIMC_PATH` | Worker | — | Path to a pre-built SimC binary. Skipped if unset (worker builds its own). |
| `SIMC_UPDATE_INTERVAL_SECONDS` | Worker | `86400` | Auto-recompile SimC interval in seconds. Set `0` to disable. |
| `SIMC_HELPER_INSECURE_TLS` | Worker | — | Set to `1` to skip TLS certificate verification (dev/self-signed only). |
| `SIM_COOLDOWN_SECONDS` | Master | `300` | Minimum seconds between simulation requests per user. |
| `LOG_LEVEL` | Both | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `SIMC_HELPER_DEV_MODE` | Both | — | Set to `1` for local dev: uses a fixed cluster secret and relaxed CORS. |

---

## 4. Docker Compose

For Docker-based deployments, copy `.env.docker.example` to `.env` and fill in `ADMIN_TOKEN` and `CLUSTER_SECRET`. The `docker-compose.yml` picks these up via `${VAR:-default}` substitution.

```bash
cp .env.docker.example .env
docker compose up -d
```

---

## 5. Config Validation

Run the doctor command before deploying to verify config structure and remote connectivity:

```bash
python3 utils/deploy.py doctor --config deploy_configs/master.json deploy_configs/worker1.json
```
