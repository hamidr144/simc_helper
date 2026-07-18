import multiprocessing
import os
import shutil
import subprocess  # nosec B404
import sys


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
        if not os.path.isdir(simc_dir):
            print("SimulationCraft repository not found. Cloning...")
            subprocess.run([git_bin, "clone", "https://github.com/simulationcraft/simc.git", simc_dir], check=True, env=env)  # nosec B603
        else:
            print("SimulationCraft repository found. Pulling latest changes...")
            subprocess.run([git_bin, "pull"], cwd=simc_dir, check=True, env=env)  # nosec B603

        print("Building SimulationCraft Engine...")
        try:
            cores = multiprocessing.cpu_count()
        except NotImplementedError:
            cores = 4

        engine_dir = os.path.join(simc_dir, "engine")
        
        # Simple cross-platform fallback
        subprocess.run([make_bin, "-C", engine_dir, "optimized", f"-j{cores}"], check=True, env=env)  # nosec B603

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
