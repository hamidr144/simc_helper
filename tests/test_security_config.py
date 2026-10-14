import importlib
import hashlib
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.core import security


def test_master_cluster_secret_is_ephemeral_when_env_missing(monkeypatch):
    monkeypatch.delenv("CLUSTER_SECRET", raising=False)
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    import web.main as master

    first = importlib.reload(master).CLUSTER_SECRET
    second = importlib.reload(master).CLUSTER_SECRET

    assert first
    assert second
    assert first != second


def test_worker_cluster_secret_is_ephemeral_when_env_missing(monkeypatch):
    monkeypatch.delenv("CLUSTER_SECRET", raising=False)
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    import worker

    first = importlib.reload(worker).CLUSTER_SECRET
    second = importlib.reload(worker).CLUSTER_SECRET

    assert first
    assert second
    assert first != second


def test_explicit_dev_mode_uses_shared_local_secret(monkeypatch):
    monkeypatch.delenv("CLUSTER_SECRET", raising=False)
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")

    import web.main as master
    import worker
    master = importlib.reload(master)
    worker = importlib.reload(worker)

    assert master.CLUSTER_SECRET == "simc_helper_local_dev_secret"
    assert worker.CLUSTER_SECRET == "simc_helper_local_dev_secret"


def test_worker_verifies_tls_certificates_by_default(monkeypatch):
    import ssl
    monkeypatch.setenv("MASTER_URL", "https://master.example")
    monkeypatch.setenv("CLUSTER_SECRET", "secret")
    monkeypatch.delenv("SIMC_HELPER_INSECURE_TLS", raising=False)

    import worker
    reloaded = importlib.reload(worker)

    assert reloaded.ssl_context.check_hostname is True
    assert reloaded.ssl_context.verify_mode == ssl.CERT_REQUIRED


def test_worker_can_explicitly_disable_tls_verification_for_dev(monkeypatch):
    import ssl
    monkeypatch.setenv("MASTER_URL", "https://master.example")
    monkeypatch.setenv("CLUSTER_SECRET", "secret")
    monkeypatch.setenv("SIMC_HELPER_INSECURE_TLS", "1")

    import worker
    reloaded = importlib.reload(worker)

    assert reloaded.ssl_context.check_hostname is False
    assert reloaded.ssl_context.verify_mode == ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Password hashing (audit F3): salted PBKDF2 with transparent legacy upgrade
# ---------------------------------------------------------------------------

def test_pbkdf2_hash_roundtrip_and_format():
    stored = security.hash_password("hunter2-passphrase")
    assert stored.startswith(f"pbkdf2_sha256${security.PBKDF2_ITERATIONS}$")
    assert security.verify_password("hunter2-passphrase", stored)
    assert not security.verify_password("wrong", stored)
    assert not security.password_needs_rehash(stored)


def test_pbkdf2_hashes_are_salted_and_unique():
    a = security.hash_password("same-password")
    b = security.hash_password("same-password")
    assert a != b
    assert security.verify_password("same-password", a)
    assert security.verify_password("same-password", b)


def test_legacy_sha256_hash_still_verifies_and_is_flagged_for_upgrade():
    legacy = hashlib.sha256(b"old-legacy-pw").hexdigest()
    assert security.verify_password("old-legacy-pw", legacy)
    assert not security.verify_password("nope", legacy)
    assert security.password_needs_rehash(legacy)


def test_verify_password_rejects_malformed_hashes():
    for garbage in ("", "not-a-hash", "pbkdf2_sha256$abc$zz$ff", "pbkdf2_sha256$5$zz$ff", "PBKDF2" + "$1$2$3"):
        assert security.verify_password("whatever", garbage) is False


# ---------------------------------------------------------------------------
# Rate limiter (audit F3)
# ---------------------------------------------------------------------------

def test_rate_limiter_opens_after_max_events():
    limiter = security.RateLimiter(max_events=3, window_seconds=60)
    for i in range(3):
        assert not limiter.is_limited("ip", now=float(i))
        limiter.record("ip", now=float(i))
    assert limiter.is_limited("ip", now=3.0)
    assert limiter.retry_after("ip", now=3.0) > 0


def test_rate_limiter_window_slides_and_keys_are_independent():
    limiter = security.RateLimiter(max_events=2, window_seconds=10)
    limiter.record("a", now=0.0)
    limiter.record("a", now=1.0)
    assert limiter.is_limited("a", now=5.0)
    assert not limiter.is_limited("b", now=5.0)
    # first event falls out of the window at t > 10
    assert not limiter.is_limited("a", now=11.0)


def test_rate_limiter_reset():
    limiter = security.RateLimiter(max_events=1, window_seconds=60)
    limiter.record("ip", now=0.0)
    assert limiter.is_limited("ip", now=1.0)
    limiter.reset("ip")
    assert not limiter.is_limited("ip", now=1.0)


# ---------------------------------------------------------------------------
# P1 audit t_622b11ac: redirect pinning, cluster-secret header, admin header
# ---------------------------------------------------------------------------

import asyncio
import httpx

import web.main as master


def _run(coro):
    return asyncio.run(coro)


class _RecordingClient:
    """Stand-in for httpx.AsyncClient that scripts canned responses."""

    def __init__(self, responses):
        self.calls = []
        self._responses = list(responses)

    def __call__(self, *args, **kwargs):  # httpx.AsyncClient(...) construction
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        self.calls.append(url)
        status, headers = self._responses.pop(0)
        return httpx.Response(
            status, headers=headers, request=httpx.Request("GET", url)
        )


def test_nether_fetch_refuses_redirect_to_foreign_host(monkeypatch):
    fake = _RecordingClient([
        (302, {"location": "http://169.254.169.254/latest/meta-data/"}),
    ])
    monkeypatch.setattr(master.httpx, "AsyncClient", fake)
    from fastapi import HTTPException
    try:
        _run(master._nether_fetch("https://nether.wowhead.com/tooltip/item/1"))
        raise AssertionError("expected HTTPException(502)")
    except HTTPException as exc:
        assert exc.status_code == 502
    # The metadata endpoint must never have been fetched.
    assert fake.calls == ["https://nether.wowhead.com/tooltip/item/1"]


def test_nether_fetch_follows_same_host_redirect(monkeypatch):
    fake = _RecordingClient([
        (301, {"location": "https://nether.wowhead.com/tooltip/item/2"}),
        (200, {"content-type": "application/json"}),
    ])
    monkeypatch.setattr(master.httpx, "AsyncClient", fake)
    response = _run(master._nether_fetch("https://nether.wowhead.com/tooltip/item/1"))
    assert response.status_code == 200
    assert fake.calls == [
        "https://nether.wowhead.com/tooltip/item/1",
        "https://nether.wowhead.com/tooltip/item/2",
    ]


def test_cluster_secret_header_wins_and_query_needs_dev_mode(monkeypatch):
    monkeypatch.setattr(master, "CLUSTER_SECRET", "cluster-abc")
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)
    assert master._cluster_secret_ok("cluster-abc", None) is True
    assert master._cluster_secret_ok("wrong", None) is False
    assert master._cluster_secret_ok(None, None) is False
    # Query param alone: refused in production, honoured in dev mode.
    assert master._cluster_secret_ok(None, "cluster-abc") is False
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")
    assert master._cluster_secret_ok(None, "cluster-abc") is True
    assert master._cluster_secret_ok(None, "nope") is False


def test_require_admin_header_only_in_production(monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    monkeypatch.setenv("ADMIN_TOKEN", "admin-xyz")
    monkeypatch.delenv("SIMC_HELPER_DEV_MODE", raising=False)

    def make_request(query=""):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "query_string": query.encode(),
            "headers": [(b"x-admin-token", b"admin-xyz")],
            "client": ("127.0.0.1", 1),
        }
        return Request(scope)

    # Header always works.
    master.require_admin(make_request())
    # Query param without dev mode is ignored -> 403.
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "query_string": b"admin_token=admin-xyz",
        "headers": [],
        "client": ("127.0.0.1", 1),
    }
    try:
        master.require_admin(Request(scope))
        raise AssertionError("expected HTTPException(403)")
    except HTTPException as exc:
        assert exc.status_code == 403
    # ...but works with dev mode on.
    monkeypatch.setenv("SIMC_HELPER_DEV_MODE", "1")
    master.require_admin(Request(scope))


def test_require_own_session_scoping():
    from fastapi import HTTPException
    # Authenticated users may only touch their own id.
    master._require_own_session("me", "me")
    try:
        master._require_own_session("victim", "attacker")
        raise AssertionError("expected HTTPException(403)")
    except HTTPException as exc:
        assert exc.status_code == 403
    # Kill-switch mode ("anonymous") has no session concept to enforce.
    master._require_own_session("anyone", "anonymous")
