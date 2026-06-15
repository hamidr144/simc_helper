import importlib
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))


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
