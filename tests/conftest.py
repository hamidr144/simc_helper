"""Shared test configuration.

The P0 security task (t_0fef205c) added a session-auth gate on state-changing
API endpoints (``require_session`` in ``web.main``).  The pre-existing API
test suite predates that gate and calls those endpoints without a session
cookie, so every test runs with ``web.main.authentication_enabled`` patched
to return False — the same effect as the operator-level
``AUTHENTICATION_ENABLED=false`` kill switch, but done on the module
attribute so it cannot be clobbered by tests that mutate ``os.environ``
(e.g. ``test_manage_simc`` clears it).

Security tests that exercise the gate opt back in per-test with
``monkeypatch.setattr(master, "authentication_enabled", lambda: True)``.
"""

import os
import sys
import tempfile

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
for _p in (_SRC, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# t_c968bf8d: reports moved off /tmp/simc_reports onto the durable
# $BASE_DIR/data/reports path. Point REPORTS_DIR at a per-run temp dir BEFORE
# web.main is imported (it reads the env at import time) so the suite never
# writes into the repo's data/ directory.
os.environ.setdefault("REPORTS_DIR", tempfile.mkdtemp(prefix="simc_reports_test_"))


@pytest.fixture(autouse=True)
def auth_kill_switch(monkeypatch):
    """Default the master app to auth-disabled for the legacy suite.

    The suite imports the app under two module aliases — ``web.main`` and
    ``src.web.main`` — which Python loads as *separate* module objects with
    independent globals, so both must be patched.
    """
    for name in ("web.main", "src.web.main"):
        try:
            module = __import__(name, fromlist=["main"])
        except ImportError:  # pragma: no cover - one alias always importable
            continue
        monkeypatch.setattr(module, "authentication_enabled", lambda: False, raising=False)


@pytest.fixture(autouse=True)
def wowhead_hydration_offline(monkeypatch):
    """Default the suite to no network for paste-path name hydration.

    t_5fe563ac: /api/parse-addon hydrates missing item names from Wowhead
    item XML.  Resolving the fetch to None keeps every test offline — names
    stay exactly as parsed.  Tests that exercise hydration monkeypatch
    ``fetch_wowhead_name_and_level`` on the module they drive (same fetch-
    boundary convention as ``fetch_wowhead_tooltip_json`` elsewhere).
    """
    async def _offline(item):
        return None
    for name in ("web.main", "src.web.main"):
        try:
            module = __import__(name, fromlist=["main"])
        except ImportError:  # pragma: no cover - one alias always importable
            continue
        monkeypatch.setattr(module, "fetch_wowhead_name_and_level", _offline, raising=False)
