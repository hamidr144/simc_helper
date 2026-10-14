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
