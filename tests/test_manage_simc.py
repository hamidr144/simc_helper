import os
import sys

from utils import manage_simc

def test_get_clean_env_replaces_orig_path():
    # Set up environment with original and overridden variables
    env = os.environ.copy()
    env["LD_LIBRARY_PATH_ORIG"] = "/original/path"
    env["LD_LIBRARY_PATH"] = "/bad/path"
    # Ensure sys.prefix is in PATH to test removal
    env["PATH"] = os.pathsep.join([sys.prefix, "/usr/bin"])
    # Patch os.environ temporarily
    original_environ = os.environ
    try:
        os.environ.clear()
        os.environ.update(env)
        cleaned = manage_simc.get_clean_env()
        assert cleaned["LD_LIBRARY_PATH"] == "/original/path"
        # The bad entry should be removed from PATH
        assert sys.prefix not in cleaned["PATH"].split(os.pathsep)
    finally:
        os.environ.clear()
        os.environ.update(original_environ)

def test_get_clean_env_removes_without_orig():
    env = os.environ.copy()
    env["DYLD_LIBRARY_PATH"] = "/bad/dyld"
    # Ensure sys.prefix not in PATH
    env["PATH"] = "/usr/bin"
    original_environ = os.environ
    try:
        os.environ.clear()
        os.environ.update(env)
        cleaned = manage_simc.get_clean_env()
        assert "DYLD_LIBRARY_PATH" not in cleaned
    finally:
        os.environ.clear()
        os.environ.update(original_environ)


def test_get_build_jobs_respects_valid_override(monkeypatch):
    monkeypatch.setenv("SIMC_BUILD_JOBS", "2")
    assert manage_simc.get_build_jobs() == 2


def test_get_build_jobs_rejects_invalid_override(monkeypatch):
    monkeypatch.setenv("SIMC_BUILD_JOBS", "0")
    # min() with cpu_count caps the fallback on low-core CI runners; pin it so the assertion is hardware-independent.
    monkeypatch.setattr(manage_simc.multiprocessing, "cpu_count", lambda: 99)
    assert manage_simc.get_build_jobs() == manage_simc.DEFAULT_SIMC_BUILD_JOBS


def test_engine_mode_defaults_to_source(monkeypatch):
    monkeypatch.delenv("SIMC_ENGINE_MODE", raising=False)
    assert manage_simc.engine_mode() == "source"


def test_engine_mode_reads_env_and_normalizes(monkeypatch):
    monkeypatch.setenv("SIMC_ENGINE_MODE", " Nightly ")
    assert manage_simc.engine_mode() == "nightly"
    monkeypatch.setenv("SIMC_ENGINE_MODE", "garbage")
    assert manage_simc.engine_mode() == "source"


def test_nightly_engine_dir_uses_base_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    assert manage_simc.nightly_engine_dir() == str(
        tmp_path / "thirdparties" / "simc-nightly"
    )


def test_nightly_mode_skips_clone_and_build(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMC_ENGINE_MODE", "nightly")
    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    engine = tmp_path / "thirdparties" / "simc-nightly" / "simc"
    engine.parent.mkdir(parents=True)
    engine.write_text("#!/bin/sh\n")

    def no_run(*args, **kwargs):  # pragma: no cover - must never fire
        raise AssertionError("nightly mode must not run git/make")

    monkeypatch.setattr(manage_simc.subprocess, "run", no_run)
    assert manage_simc.main() == 0
    # No git checkout was created next to the nightly engine.
    assert not (tmp_path / "thirdparties" / "simc").exists()


def test_nightly_mode_fails_fast_without_extracted_engine(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMC_ENGINE_MODE", "nightly")
    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    assert manage_simc.main() == 1
