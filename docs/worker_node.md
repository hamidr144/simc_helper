# Worker Node

The Worker Node runs as a headless worker daemon (`src/worker.py`, compiled as `simc-worker`). It connects to the master via WebSocket, executes SimulationCraft, batches stdout logs, and uploads zipped report files.

---

## 1. Startup Options

Running the worker binary without flags launches the persistent daemon. It also supports utility commands:

```bash
# Clone, build, or update local SimulationCraft engine
./simc-worker manage_simc

# Run the staged simulation orchestrator directly (Command Line Workflow)
./simc-worker sim_helper simc_path=<bin> input_file=<file> [stage1_percent_best=25%]
```

---

## 2. Simulation Lifecycle

```text
Connect ──> Await task ──> Download .simc ──> Start PTY SimC ──> Batch & Stream Logs ──> Zip & Upload reports
```

1.  **Handshake**: Registers connection at `/ws/worker` sending `WORKER_NAME` and `CLUSTER_SECRET`.
2.  **Liveness**: Sends WebSocket pings every 10 seconds.
3.  **Task Start**: Receives `task_id` and `input_url`.
4.  **Sandbox Isolation**: Creates a temporary working directory `/tmp/worker_sim_<task_id>/` and downloads the input file.
5.  **PTY Execution**: Spawns SimC using a Pseudo-Terminal (PTY) to force line-by-line output buffering (bypassing normal terminal block buffering).
6.  **Log Batching**: Batches stdout lines into 100ms intervals to reduce WebSocket frame overhead.
7.  **Upload**: Zips HTML reports, raw console logs, and outputs; uploads them back to `/api/worker/upload-file`.
8.  **Complete**: Reports `done` status and transitions back to `Idle`.

---

## 3. Engine Management (`manage_simc`)

The worker automatically maintains its SimulationCraft installation:
*   Runs on startup, and once every 24 hours (`SIMC_UPDATE_INTERVAL_SECONDS` default) while idle.
*   Pulls the SimulationCraft source repository, configures dependencies via CMake, compiles the engine locally, and registers the binary at `thirdparties/simc/engine/simc`.
*   Can be manually triggered by administrators via `POST /api/update-simc`.
