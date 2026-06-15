# Master Node

The Master Node is the FastAPI controller served by `src/web/main.py` (packaged as `simc-master`). It hosts the dashboard UI, parses inputs, manages workers, streams logs, and serves final simulation HTML reports.

---

## API Reference

| Endpoint | Method | Auth | Description |
| :--- | :--- | :--- | :--- |
| `/` | `GET` | Session | Returns `login.html` (or `app.html` in dev/pytest). |
| `/dashboard` | `GET` | Session | Serves the main simulation dashboard (`app.html`). |
| `/login` | `POST` | — | Validates username/password and sets `session_id` cookie. |
| `/register` | `POST` | — | Registers a new user. |
| `/logout` | `GET` | Session | Deletes the user session cookie. |
| `/health` | `GET` | — | Reports worker connectivity, SimC binary presence, and disk space. |
| `/api/state` | `GET` | — | Returns active workers and currently generating inputs. |
| `/api/parse-addon` | `POST` | — | Normalizes `/simc` addon text into JSON gear properties. |
| `/api/generate-simc` | `POST` | — | Builds a task-scoped `.simc` input under `data/master/inputs/`. |
| `/api/run-simulation` | `POST` | Rate-limit (`SIM_COOLDOWN_SECONDS`) | Dispatches task instructions to an idle worker. |
| `/api/task-status` | `GET` | — | Query status for a specific task or all tasks. |
| `/api/simulation/stream/{id}` | `GET` | — | Server-Sent Events (SSE) stream of worker simulation stdout. |
| `/api/get-results` | `GET` | — | Reads and parses the latest simulation HTML report. |
| `/api/wowhead-upgrades` | `POST` | — | Looks up Midnight gear upgrade tracks via Wowhead. |
| `/api/config` | `GET` | — | Returns the current `config.json`. |
| `/api/settings` | `GET`/`POST` | — | Read or persist dashboard settings. |
| `/api/update-simc` | `POST` | Admin Token | Triggers SimulationCraft engine updates on all workers. |
| `/api/stop-simulation` | `POST` | Admin Token | Stops all active worker simulation processes. |
| `/api/shutdown` | `POST` | Admin Token | Shuts down the master process. |
| `/inputs/{file_name}` | `GET` | Safe path | Serves generated `.simc` input files. |
| `/reports/{path}` | `GET` | Safe path | Serves unzipped SimulationCraft report artifacts. |

---

## Health Check (`/health`)

Used by Docker and container orchestrators. Returns HTTP 200 with JSON:

*   **`status: "ok"`** — Node is healthy.
*   **`status: "degraded"`** — Operational, but disk space is critically low (free < 5%).

---

## Worker Coordination

The master maintains WebSocket state to orchestrate task dispatch:

1.  **Registration**: Workers connect to `/ws/worker` with `WORKER_NAME` and `CLUSTER_SECRET`. Invalid secrets are rejected immediately.
2.  **State Tracking**: Workers transition between `Idle`, `Busy`, and `Unavailable`.
3.  **Heartbeat Enforcement**: A background loop drops slots for workers that fail to ping within 30 seconds.
4.  **Graceful Recovery**: If a worker disconnects mid-simulation, its task queue receives a broadcast error and its slot is cleaned up.
5.  **Admin Token**: Destructive routes (`/api/update-simc`, `/api/stop-simulation`, `/api/shutdown`) verify `X-Admin-Token` header or `admin_token` query param against `ADMIN_TOKEN`.
