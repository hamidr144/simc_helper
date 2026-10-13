import multiprocessing
import os
import shutil
import subprocess  # nosec B404
import sys
from datetime import datetime, timezone


DEFAULT_SIMC_BUILD_JOBS = 4


def engine_mode() -> str:
    """Return the configured SimC engine workflow: 'nightly' or 'source'.

    'nightly' (compose default): the engine binary is extracted from the
    pinned official SimC Docker nightly image by the 'engine-update' one-shot
    service into the simc-engine volume — no clone, no compile.
    'source' (fallback / local default): clone + compile from the GitHub
    checkout under BASE_DIR/thirdparties/simc (legacy behaviour).
    """
    mode = os.environ.get("SIMC_ENGINE_MODE", "source").strip().lower()
    return mode if mode in ("nightly", "source") else "source"


def nightly_engine_dir() -> str:
    """Directory holding the nightly engine extracted into the volume."""
    base_dir = os.environ.get("BASE_DIR")
    if base_dir:
        return os.path.join(base_dir, "thirdparties", "simc-nightly")
    return os.path.expanduser("~/.simc-nightly")


def get_build_jobs() -> int:
    """Return a bounded parallelism level suitable for local and Docker builds."""
    configured_jobs = os.environ.get("SIMC_BUILD_JOBS")
    if configured_jobs:
        try:
            jobs = int(configured_jobs)
            if jobs > 0:
                return jobs
        except ValueError:
            pass
        print(
            f"Ignoring invalid SIMC_BUILD_JOBS={configured_jobs!r}; "
            f"using {DEFAULT_SIMC_BUILD_JOBS}."
        )

    try:
        return min(multiprocessing.cpu_count(), DEFAULT_SIMC_BUILD_JOBS)
    except NotImplementedError:
        return DEFAULT_SIMC_BUILD_JOBS


def get_clean_env():
    env = os.environ.copy()
    # PyInstaller sets these, which can break system binaries (symbol lookup errors)
    for var in ["LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"]:
        orig = var + "_ORIG"
        if orig in env:
            env[var] = env[orig]
        elif var in env:
            del env[var]
    
    # Also ensure the bundled bin path isn't first in PATH
    if "PATH" in env and sys.prefix in env["PATH"]:
        # Remove any entries containing the PyInstaller temporary directory
        paths = env["PATH"].split(os.pathsep)
        clean_paths = [p for p in paths if sys.prefix not in p]
        env["PATH"] = os.pathsep.join(clean_paths)
        
    return env

def main():
    if engine_mode() == "nightly":
        engine = os.path.join(nightly_engine_dir(), "simc")
        print(
            "SIMC_ENGINE_MODE=nightly: engine comes from the official SimC "
            "Docker nightly image (extracted by the 'engine-update' compose "
            f"service into the simc-engine volume). Skipping clone/build. "
            f"Engine: {engine}"
        )
        if not os.path.isfile(engine):
            print(
                "ERROR: nightly engine wrapper not found. Start the "
                "'engine-update' compose service first "
                "(docker compose up -d --build engine-update), or set "
                "SIMC_ENGINE_MODE=source to fall back to the source build."
            )
            return 1
        return 0

    base_dir = os.environ.get("BASE_DIR")
    if base_dir:
        simc_dir = os.path.join(base_dir, "thirdparties", "simc")
    else:
        simc_dir = os.path.expanduser("~/.simc")
        
    env = get_clean_env()
    git_bin = shutil.which("git") or "git"
    make_bin = shutil.which("make") or "make"
    print(f"Checking SimulationCraft repository at {simc_dir}...")

    try:
        git_dir = os.path.join(simc_dir, ".git")
        if os.path.isdir(simc_dir) and not os.path.isdir(git_dir):
            backup_dir = f"{simc_dir}.invalid-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            print(f"SimulationCraft directory is not a Git checkout. Preserving it as {backup_dir}.")
            shutil.move(simc_dir, backup_dir)

        if not os.path.isdir(simc_dir):
            print("SimulationCraft repository not found. Cloning...")
            subprocess.run([git_bin, "clone", "https://github.com/simulationcraft/simc.git", simc_dir], check=True, env=env)  # nosec B603
        else:
            print("SimulationCraft repository found. Pulling latest changes...")
            subprocess.run([git_bin, "pull"], cwd=simc_dir, check=True, env=env)  # nosec B603

        print("Building SimulationCraft Engine...")
        jobs = get_build_jobs()
        print(f"Building with {jobs} parallel job(s). Set SIMC_BUILD_JOBS to override.")

        engine_dir = os.path.join(simc_dir, "engine")
        
        # Simple cross-platform fallback
        subprocess.run([make_bin, "-C", engine_dir, "optimized", f"-j{jobs}"], check=True, env=env)  # nosec B603

        print("Build complete.")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return e.returncode
    except FileNotFoundError as e:
        print(f"Command not found: {e.filename}. On Windows, ensure 'git' and 'make' are installed and in PATH.")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
