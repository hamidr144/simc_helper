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
