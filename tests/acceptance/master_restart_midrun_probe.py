"""LIVE master-restart probe for t_acd39188 (LIFE-10).

The LIFE-2 unit test only simulated the master side in-process; this probe
restarts the REAL master container mid-run on the dev stack and asserts the
user-visible contract:

  Case A (mid-run restart, sim lost):
    worker kills the sim on WS death (no retry storm), reconnects, sends
    'resume'; master re-attaches the task queue; the user gets exactly ONE
    failed run_history row and a live SSE stream (200, error event) — not
    silence and not a 404.

  Case B (run finished during the outage):
    master is stopped while the sim runs; the staged artifacts.zip stands in
    for a run that completed while master was down; after master returns the
    worker re-uploads it and the user gets exactly ONE success row with a
    parsed top_dps and a report file in the owner's directory.

Not pytest-collected on purpose: needs the live simc-dev stack and Docker.
Run against the dev system (:8001) with the branch images deployed:

    python tests/acceptance/master_restart_midrun_probe.py   # exit 0 = PASS

Env overrides: BASE, MASTER_CTN, WORKER_CTN, ADDON.
"""
import json
import os
import subprocess
import sys
import time
import uuid
import zipfile

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:8001")
MASTER_CTN = os.environ.get("MASTER_CTN", "simc-dev-simc-master-1")
WORKER_CTN = os.environ.get("WORKER_CTN", "simc-dev-simc-worker-1")
HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.environ.get(
    "ADDON",
    "/Users/hami/.hermes/kanban/attachments/t_4fc38887/"
    "hamidriel_retr_draenor_2026-10-16.simc-addon.txt")
REPORT_FIXTURE = os.path.join(HERE, "..", "fixtures", "simc_nightly_report_multicopy.html")
DB = "/app/data/master/simc_helper.sqlite"
PW = "Qa!test-2026-x"

checks = []


def check(name, cond, extra=""):
    checks.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""), flush=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def ctn_logs(ctn, since="120s"):
    return sh(f"docker logs --since {since} {ctn} 2>&1")


def dbq(sql):
    script = (f"import sqlite3\n"
              f"c=sqlite3.connect('{DB}')\n"
              f"print(list(c.execute(\"{sql}\")))\n")
    r = subprocess.run(["docker", "exec", "-i", MASTER_CTN, "python", "-"],
                       input=script, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def wait_for(pred, timeout, what):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(1)
    log(f"TIMEOUT waiting for {what}")
    return False


def start_run(client, n_slots):
    """Register + parse + generate + run. Returns (user, task_id, worker_id)."""
    user = f"qa_l10{uuid.uuid4().hex[:6]}"
    r = client.post("/register", data={"username": user, "password": PW})
    assert r.status_code == 303, f"register failed: {r.status_code}"
    pa = client.post("/api/parse-addon", json={"addon_text": open(ADDON, encoding="utf-8").read()}).json()
    sel = {}
    for slot, items in pa["items_by_slot"].items():
        if len(items) >= 2 and len(sel) < n_slots:
            sel[slot] = items[:2]
    gen = client.post("/api/generate-simc", json={
        "char_class": pa["char_class"], "char_name": pa["char_name"],
        "base_profile": pa["base_profile"], "equipped_gear": pa["equipped_gear"],
        "selected_items": sel}).json()
    input_id = gen.get("input_id") or gen.get("input", {}).get("input_id")
    r = client.post("/api/run-simulation", params={"input_id": input_id})
    assert r.status_code == 200, f"run-simulation failed: {r.status_code} {r.text[:200]}"
    body = r.json()
    log(f"started run user={user} task={body['task_id']}")
    return user, body["task_id"], body["worker_id"]


def history_rows(user):
    return dbq("SELECT status, top_dps, report_path FROM run_history "
               f"WHERE user_id=(SELECT user_id FROM users WHERE username='{user}')")


def wait_execution_attempt():
    return wait_for(lambda: "Execution attempt" in ctn_logs(WORKER_CTN, "60s"), 60,
                    "worker 'Execution attempt'")


# ---------------------------------------------------------------------------
# Case A: mid-run master RESTART -> exactly one failed row, SSE re-attached
# ---------------------------------------------------------------------------
print("== Case A: mid-run master restart (sim lost) ==")
cA = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)
userA, taskA, workerA = start_run(cA, 5)  # 32 combos, ~40 s
assert wait_execution_attempt()
log("RESTARTING MASTER mid-run")
sh(f"docker restart {MASTER_CTN}")

ok = wait_for(lambda: f"resumed task {taskA}" in ctn_logs(MASTER_CTN, "5m"), 180,
              f"master log 'resumed task {taskA}'")
check("A1 master handled worker 'resume'", ok)
check("A2 worker did not retry-storm on dead WS",
      ctn_logs(WORKER_CTN, "5m").count(f"[{taskA}] Execution attempt") <= 1,
      f"attempts={ctn_logs(WORKER_CTN, '5m').count(f'[{taskA}] Execution attempt')}")

sse_events = []
try:
    with cA.stream("GET", f"/api/simulation/stream/{taskA}",
                   params={"worker_id": workerA}, timeout=30) as s:
        check("A3 SSE stream 200 after restart (was 404)", s.status_code == 200,
              f"status={s.status_code}")
        for line in s.iter_lines():
            if line.startswith("data: "):
                sse_events.append(json.loads(line[6:]))
                if sse_events[-1]["type"] in ("done", "error"):
                    break
except httpx.HTTPError as e:
    check("A3 SSE stream 200 after restart (was 404)", False, f"{e}")
check("A4 SSE delivered terminal error event (not silence)",
      any(e.get("type") == "error" for e in sse_events),
      str(sse_events[-1])[:120] if sse_events else "no events")

ok = wait_for(lambda: "failed" in history_rows(userA), 60, "failed run_history row")
rowsA = history_rows(userA)
check("A5 exactly one failed history row for the user",
      rowsA.count("'failed'") == 1, rowsA[:200])
check("A6 master log clean (no traceback since restart)",
      "Traceback" not in ctn_logs(MASTER_CTN, "5m"))

# ---------------------------------------------------------------------------
# Case B: run finished during outage -> staged zip replayed after restart
# ---------------------------------------------------------------------------
print("== Case B: artifacts replay after master returns (run finished during outage) ==")
cB = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)
userB, taskB, workerB = start_run(cB, 5)
assert wait_execution_attempt()
log("STOPPING MASTER (stays down until zip staged)")
sh(f"docker stop {MASTER_CTN}")
ok = wait_for(lambda: "Connection lost — reconnecting to master" in ctn_logs(WORKER_CTN, "3m"),
              90, "worker reconnect-loop entry")
check("B1 worker broke out of retry loop into reconnect (root cause 1)", ok)

zip_local = f"/tmp/probe_l10_{taskB}.zip"  # nosec B108 — throwaway probe file
with zipfile.ZipFile(zip_local, "w") as zf:
    zf.write(REPORT_FIXTURE, "report_20260101_000000.html")
    zf.writestr("stage3.simc", "simulate\n")
r = sh(f"docker cp {zip_local} {WORKER_CTN}:/tmp/worker_sim_{taskB}/artifacts.zip")
os.remove(zip_local)
check("B2 staged artifacts.zip on worker (sim finished during outage)", "error" not in r.lower(), r)
sh(f"docker start {MASTER_CTN}")

ok = wait_for(lambda: f"resumed task {taskB}" in ctn_logs(MASTER_CTN, "5m"), 180,
              f"master log 'resumed task {taskB}'")
check("B3 master handled resume after master start", ok)
ok = wait_for(lambda: "success" in history_rows(userB), 90, "success run_history row")
rowsB = history_rows(userB)
check("B4 exactly one success history row with parsed top_dps",
      rowsB.count("'success'") == 1 and "('success', None" not in rowsB,
      rowsB[:200])
files = sh(f"docker exec {MASTER_CTN} sh -c \"find /app/data/reports -path '*{taskB}*report_*' -name '*.html'\"")
check("B5 report landed in the owner's task dir", taskB in files and ".html" in files, files[:160])
check("B6 worker re-uploaded via retry path",
      "Resuming active task after reconnect" in ctn_logs(WORKER_CTN, "5m"))

# ---------------------------------------------------------------------------
fails = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not fails else 'FAILURES: ' + str(fails)} ({len(checks)} checks)")
sys.exit(1 if fails else 0)
