"""Docker-restart acceptance probe for t_c5d47786 (throwaway container).

Flow: register -> login -> fake worker -> run -> upload REAL nightly report
-> SSE done -> /history link serves. Then `docker restart` the container and
re-verify everything. Prints PASS/FAIL per check.

Run manually (e.g. at merge time, when the live simc-master must NOT be
recreated from an unmerged stack)::

    docker build -t simc-helper:acc .
    docker volume create acc_reports_probe
    docker run -d --name acc-probe -p 127.0.0.1:8899:8000 \\
        -e BASE_DIR=/app -e CLUSTER_SECRET=<ascii-secret> \\
        -e SIMC_HELPER_DEV_MODE=0 -e AUTHENTICATION_ENABLED=true \\
        -v acc_reports_probe:/app/data simc-helper:acc
    python tests/acceptance/docker_restart_probe.py   # exit 0 = PASS
    docker rm -f acc-probe && docker volume rm acc_reports_probe

BASE/SECRET/REPORT below must match the container. Not pytest-collected on
purpose: it needs a live Docker daemon and a built image.
"""
import json
import os
import subprocess
import sys
import time
import uuid

import httpx
from websockets.sync.client import connect as ws_connect

BASE = "http://127.0.0.1:8899"
SECRET = "acc-docker-secret-c5d47786"
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures",
               "simc_nightly_report_multicopy.html")

checks = []


def check(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))


def wait_healthy(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/health", timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


report_bytes = open(REPORT, "rb").read()
client = httpx.Client(base_url=BASE, timeout=15)

# register + login
username = f"dockerprobe-{uuid.uuid4().hex[:8]}"
r = client.post("/register", data={"username": username, "password": "***"})
check("register 200", r.status_code == 200, r.text[:80])
r = client.post("/login", data={"username": username, "password": "***"},
                follow_redirects=False)
check("login 303 + session cookie", r.status_code == 303 and "session_id" in r.headers.get("set-cookie", ""))

# rewind the login-seeded cooldown (t_ef8682a4 unmerged)
subprocess.run(
    ["docker", "exec", "acc-c5d47786", "python", "-c",
     "import sqlite3; c=sqlite3.connect('/app/data/master/simc_helper.sqlite');"
     "c.execute('UPDATE user_sessions SET last_sim_time=0'); c.commit()"],
    check=True, capture_output=True)

# fake worker + full run
with ws_connect("ws://127.0.0.1:8899/ws/worker?name=dockerprobe",
                additional_headers={"X-Cluster-Secret": SECRET}) as ws:
    # SEC-6: explicit input_id (the fake ws worker never fetches it)
    r = client.post("/api/run-simulation", params={"input_id": "dockerprobe1"})
    check("run-simulation 200", r.status_code == 200, r.text[:120])
    task_id, worker_id = r.json()["task_id"], r.json()["worker_id"]
    start = json.loads(ws.recv(timeout=15))
    check("worker got start", start.get("type") == "start" and start.get("task_id") == task_id)
    r = client.post("/api/worker/upload-file",
                    params={"task_id": task_id, "file_name": "report_1.html"},
                    headers={"X-Cluster-Secret": SECRET},
                    files={"file": ("report_1.html", report_bytes, "text/html")})
    check("upload 200", r.status_code == 200)
    ws.send(json.dumps({"type": "done", "task_id": task_id, "code": 0}))
    with client.stream("GET", f"/api/simulation/stream/{task_id}?worker_id={worker_id}") as s:
        terminal = None
        for line in s.iter_lines():
            if line.startswith("data:") and ('"type": "done"' in line or '"type": "error"' in line):
                terminal = line
                break
    check("SSE terminal done", terminal is not None and '"type": "done"' in terminal)

runs = client.get("/api/history").json()["runs"]
check("history has 1 row", len(runs) == 1, str(runs)[:200])
row = runs[0]
check("top_dps 7887 from real nightly report", row.get("top_dps") == 7887)
report_url = row.get("report_url")
check("report_url present", bool(report_url), str(report_url))
check("report serves exact bytes pre-restart", client.get(report_url).content == report_bytes)

# ---- docker restart ----
subprocess.run(["docker", "restart", "acc-c5d47786"], check=True, capture_output=True)
check("container healthy after docker restart", wait_healthy())

runs = client.get("/api/history").json()["runs"]
check("history row survives docker restart", len(runs) == 1 and runs[0]["run_id"] == row["run_id"])
check("same report_url after restart", runs and runs[0].get("report_url") == report_url)
served = client.get(report_url)
check("/history link still serves the report after docker restart",
      served.status_code == 200 and served.content == report_bytes)
resolved = client.get(f"/api/report-url?task_id={task_id}")
check("report-url resolves with empty task map (glob fallback)",
      resolved.status_code == 200 and resolved.json().get("url") == report_url)
page = client.get("/history", follow_redirects=False)
check("/history page 200 for session after restart", page.status_code == 200)

failed = [n for n, ok in checks if not ok]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed" + (f" — FAILED: {failed}" if failed else " — PROBE PASS"))
sys.exit(1 if failed else 0)
