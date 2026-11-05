"""t_e53e7d6b — worker chip never rests at 'checking...' (source contract).

Iteration-4 rank-4 (ISO 9241-110 self-descriptiveness): logged-out visitors
saw a frozen 'worker: checking...' chip. The initial markup and the 401 poll
path must both state status-unknown with a sign-in hint; the authenticated
tri-state in workers.js stays unchanged.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"
APP_HTML = (STATIC / "app.html").read_text()
WORKERS_JS = (STATIC / "js" / "core" / "workers.js").read_text()


def test_initial_chip_is_unknown_not_checking():
    assert "worker: checking..." not in APP_HTML
    assert '<span id="worker-status" class="status-chip status-unknown" role="status" title="Sign in to see worker status"><span id="worker-status-text">worker: -</span></span>' in APP_HTML


def test_401_path_sets_unknown_chip_once():
    branch = WORKERS_JS.split("response.status === 401", 1)[1].split("return", 1)[0]
    assert "status-chip status-unknown" in branch
    assert "'worker: -'" in branch
    assert "Sign in to see worker status" in branch


def test_authenticated_tristate_unchanged():
    for label in ("No idle workers", "All workers busy \\u00b7 waiting", "workers idle"):
        assert label in WORKERS_JS
    # 'Server offline' stays gated on 3 consecutive failures (doc 4.1).
    assert "workerPollFailures >= 3" in WORKERS_JS
