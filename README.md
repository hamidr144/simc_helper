# Simcraft Helper Suite

*Trigger CI run*

Simcraft Helper Suite is a Python/FastAPI toolchain for generating SimulationCraft profile combinations, running staged simulations, and managing a small master/worker SimC cluster.

The current project favors a local web UI for day-to-day use, optional distributed workers for heavier runs, and local-only configuration files so deployment secrets do not live in git.

## What it does

- Parses `/simc` addon exports and separates baseline gear from bag items.
- Generates `.simc` profile combinations from selected gear, enchantments, gems, and optional item-level overrides.
- Runs a 3-stage refinement workflow to discard weak profiles early before final high-iteration simulation.
- Provides a compact web dashboard for engine management, gear selection, live logs, worker status, and final reports.
- Supports distributed execution: a FastAPI master dispatches jobs to one or more worker daemons over authenticated WebSockets.
- Stores generated web inputs as task-scoped files under `data/master/inputs/` instead of relying on one global scratch input.
- Keeps local config and deployment secrets out of git; safe templates live in `examples/`.

## Requirements

- Python 3.9+ recommended.
- Git, `make`, CMake, and a C++ compiler for building SimulationCraft.
- Docker for Linux cross-compiled standalone binaries.
- A World of Warcraft SimulationCraft addon export.
- Optional deployment tools: `ssh`, `scp`, `rsync`, and `sshpass` if using password SSH auth.

## Quick local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp examples/config.example.json config.json
```

For Docker Compose, also copy `.env.docker.example` to `.env`.

Put your addon export in `char_simc_addon.txt`, then run either the web app or CLI tools.

### Run the web app locally

```bash
python3 src/web/main.py
```

By default the web app binds to `127.0.0.1:8000`. Set `HOST=0.0.0.0` only when you intentionally want to expose it beyond localhost.

Useful environment variables are fully documented in `.env.example` (copy it to `.env` and fill in your values). A quick reference:

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Web server HTTP port. |
| `HOST` | `127.0.0.1` | Bind host. Use `0.0.0.0` to accept external connections. |
| `BASE_DIR` | `.` | Runtime data/log root. Relative paths resolve against this. |
| `SIMC_PATH` | — | Path to the SimulationCraft binary for running simulations via `sim_helper` CLI. |
| `SSL_KEYFILE` | — | Path to TLS private key (PEM). Required for HTTPS. |
| `SSL_CERTFILE` | — | Path to TLS certificate (PEM). Required for HTTPS. |
| `ADMIN_TOKEN` | — | Admin API token for destructive endpoints (`/api/update-simc`, `/api/stop-simulation`, `/api/shutdown`). |
| `CLUSTER_SECRET` | — | Secret string for secure communication between master and worker. Set the same value on every node. |
| `SIMC_HELPER_DEV_MODE` | — | Set to `1` for local dev (uses a deterministic cluster secret). |
| `MASTER_URL` | `http://localhost:8000` | Master server URL (worker only). |
| `WORKER_NAME` | `LocalWorker` | Worker node name for identification (worker only). |
| `SIMC_UPDATE_INTERVAL_SECONDS` | `86400` | Worker auto-update interval for the SimC engine, in seconds. Set `0` to disable. |
| `SIMC_HELPER_INSECURE_TLS` | — | Set to `1` to skip TLS certificate verification on worker connections (dev only). |
| `INPUTS_DIR` | — | Directory for generated `.simc` inputs (`data/master/inputs/` by default). |
| `REPORTS_DIR` | — | Directory for simulation reports (`/tmp/simc_reports` by default). |

### Use the web UI

1. Build or update the SimC engine.
2. Paste your `/simc` addon export.
3. Select candidate gear, enchants, and gems.
4. Adjust Midnight upgrade tracks/ranks when needed:
   - each item shows a `Track` and `Rank` selector instead of a raw item-level field;
   - the UI infers the current rank from parsed `ilevel=` or the addon label like `(289)` when possible;
   - selected track/rank is converted to the correct `ilevel=` only when generating SimC input;
   - for weapons and trinkets, tick `Ascendant Voidforged +9` to model Midnight Voidforge upgrades.
5. Generate a task-scoped `.simc` input and run the simulation.
6. Watch live logs and open the final HTML report.

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | `GET` | Health check — worker connectivity, SimC binary, disk space. |
| `/api/state` | `GET` | Current server state and connected workers. |
| `/api/parse-addon` | `POST` | Parse a `/simc` addon export. |
| `/api/generate-simc` | `POST` | Generate a task-scoped `.simc` input file. |
| `/api/run-simulation` | `POST` | Start a simulation via a worker. |
| `/api/task-status` | `GET` | Query task status for one or all tasks. |
| `/api/update-simc` | `POST` | Trigger a worker-side SimC engine update. |
| `/api/stop-simulation` | `POST` | Stop the current simulation. |
| `/api/shutdown` | `POST` | Shut down the master process. |
| `/api/wowhead-upgrades` | `POST` | Look up Midnight gear upgrade tracks via Wowhead. |
| `/api/config` | `GET` | Return the current `config.json`. |
| `/inputs/{id}.simc` | `GET` | Serve a generated input file. |
| `/reports/` | `GET` | Serve simulation report artifacts. |

## CLI workflow

### Generate a `.simc` input

```bash
python3 src/cli/generate_input.py
```

Defaults:

- addon input: `char_simc_addon.txt`
- generated output: `generated_sim.simc`
- local config: `config.json`
- optional globals: `globals.simc`

### Run staged SimulationCraft

```bash
python3 src/cli/sim_helper.py \
  simc_path=~/.simc/engine/simc \
  input_file=generated_sim.simc \
  stage1_percent_best=25% \
  stage2_percent_best=25% \
  start_server=1
```

### Build/update the SimC engine from the worker binary

```bash
./simc-worker manage_simc
```

The same management logic is also available through `utils/manage_simc.py` during development.

## Configuration files

Real local config files are intentionally ignored by git:

- `config.json`
- `deploy_configs/*.json`

Start from safe templates:

```bash
cp examples/config.example.json config.json
mkdir -p deploy_configs
cp examples/deploy_master.example.json deploy_configs/master.json
cp examples/deploy_worker.example.json deploy_configs/worker1.json
```

Do not commit real hosts, usernames, passwords, keys, tokens, or cluster secrets.

## Building standalone executables

Linux x86_64 build via Docker:

```bash
cmake -S . -B build
cmake --build build
```

### Docker health check

The `Dockerfile.linux` includes a `HEALTHCHECK` directive that polls `GET /health` every 30 seconds. Docker marks the container as unhealthy if the endpoint is unreachable for 3 consecutive retries (3 seconds timeout, 10-second start period).

The health check verifies:
- Worker connectivity (connected/idle/busy counts)
- SimulationCraft binary presence (`thirdparties/simc/engine/simc`)
- Free disk space (flags `"degraded"` below 5%)

Check container health with:

```bash
docker inspect --format='{{.State.Health.Status}}' <container>
```

Build only the artifact you are iterating on:

```bash
cmake --build build --target simc_master
cmake --build build --target simc_worker
cmake --build build --target deploy_tool
cmake --build build --target debug_cli
```

The default build reuses PyInstaller analysis caches for faster local iteration. Use a clean release build when you need fully fresh PyInstaller output:

```bash
cmake -S . -B build -DPYINSTALLER_CLEAN=ON
cmake --build build --target package_all
```

Run tests before packaging everything:

```bash
cmake -S . -B build -DBUILD_WITH_TESTS=ON
cmake --build build --target verified_package_all
```

Choose another target platform with `-DTARGET_PLATFORM=windows` or `-DTARGET_PLATFORM=macos` when the matching build environment is available. Build outputs are written to the CMake build directory and include `simc-master`, `simc-worker`, `deploy`, and `debug_cli` where supported.

## Docker & Docker Compose

### Quick start

```bash
# Build the image (multi-stage: builder → slim runtime)
docker build -t simc-helper:latest .

# Run the master web server
docker run -d --name simc-master \
  -p 8000:8000 \
  -e HOST=0.0.0.0 \
  -e ADMIN_TOKEN=your-secret \
  -e CLUSTER_SECRET=your-secret \
  simc-helper:latest
```

### Docker Compose

```bash
# Start master + 1 worker
docker compose up -d

# Start with 3 workers
docker compose up -d --scale simc-worker=3

# Start with Redis (optional profile)
docker compose --profile redis up -d

# Stop everything
docker compose down
```

Environment variables are managed via inline defaults in `docker-compose.yml`.
Copy `.env.docker.example` to `.env` and fill in `ADMIN_TOKEN` and `CLUSTER_SECRET` for production.

### Multi-arch builds

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t simc-helper:latest --push .
```

### What the Docker setup provides

| Feature | Details |
|---|---|
| **Multi-stage build** | Builder stage compiles PyInstaller binaries; runtime stage is a slim `python:3.11-slim-bookworm` image |
| **Health check** | `GET /health` every 30 s (5 s timeout, 3 retries) |
| **Environment variables** | `HOST`, `PORT`, `ADMIN_TOKEN`, `CLUSTER_SECRET`, `SIMC_PATH`, `SIMC_HELPER_DEV_MODE`, etc. |
| **Named volumes** | `simc-data`, `simc-logs`, `simc-inputs` for persistent state |
| **Multi-arch** | Supports `linux/amd64` and `linux/arm64` via buildx |
| **Optional Redis** | Commented-out service enabled via `--profile redis` |

## Deployment

The deployer (`utils/deploy.py`) manages standalone binaries on remote nodes via SSH without requiring root access. All deployment config lives in `deploy_configs/*.json` — no `.env` file needed on remote nodes.

See [`docs/deployment.md`](docs/deployment.md) for the full command reference, and [`docs/configuration.md`](docs/configuration.md) for the JSON schema and `env` block.

## Project structure

- `src/web/`: FastAPI master app and vanilla HTML/CSS/JS dashboard.
- `src/worker.py`: worker daemon and embedded worker commands.
- `src/cli/`: standalone SimC input generation and staged run helpers.
- `src/core/`: shared parsing, path-safety, and environment helpers.
- `utils/`: deployment, debug, and SimC engine management utilities.
- `examples/`: safe config templates.
- `docs/`: deeper technical documentation.
- `tests/`: regression tests for CLI, web, deployment, and hardening behavior.

## Testing and checks

```bash
python3 -m pytest -q
bash scripts/run_tests.sh
python3 -m bandit -q -r src utils -x tests
```

See `docs/index.md` for architecture, deployment, and configuration details.

## GUI usage

The web dashboard provides a guided workflow with 7 steps:

### Workflow tabs

| Step | Tab | What you do |
|------|-----|-------------|
| 01 | Setup & Addon | Paste your `/simc` addon export and click **Parse Addon Data** |
| 02 | Gear Selection | Pick gear for each slot, select enchantments/gems to test, enable extra sockets. Click **Generate Combinations & Continue** |
| 03 | Run Simulation | Select a worker (or "Any Free Worker"), then **Start Simulation**. Watch live logs in the console. |
| 04 | Final Report | View DPS rankings, gear differences vs baseline, and open the full HTML report |
| 05 | Compare | Select two profiles to see a side-by-side gear comparison with delta DPS |
| 06 | What-If | Build a hypothetical profile by swapping individual slots, then simulate it |
| 07 | Settings | Configure connection, simulation, network, TLS, theme, and keyboard shortcuts |

### Keyboard shortcuts

| Keys | Action |
|------|--------|
| `1`–`7` | Switch to the corresponding workflow tab |
| `Ctrl`+`Enter` | Run simulation (when on the Run Simulation tab) |
| `Ctrl`+`S` | Save settings (when on the Settings tab) |
| `Escape` | Close modal dialogs / reset selection |

### Tips

- The worker count in the top-right shows `free/total` workers, updated every 10 seconds.
- Gear differences in the report are highlighted: purple for added items, red for removed items.
- Comparison tables highlight rows where gear differs between profiles, with a delta DPS column.
- The Settings tab persists to the server via `/api/settings` — changes apply on the next page load or restart.
