"""Single-source running version (MGE-3, epic item 6).

WORKFLOW.md bumps ``pyproject.toml`` per PR, so pyproject is the only version
string; this module resolves the *running* version from it. Preference order:

1. the repo-root ``pyproject.toml`` next to the running code — the checkout /
   Docker image (``COPY . /app``) that the code actually came from;
2. installed-package metadata, for pip/wheel deployments where pyproject is
   not shipped next to ``src/``;
3. ``"0.0.0+unknown"`` — honest absence, never a stale literal.
"""

import os
import re

UNKNOWN_VERSION = "0.0.0+unknown"


def get_app_version() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, *[".."] * 2))
    try:
        with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
            match = re.search(r'^version = "([^"]+)"', f.read(), re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("simc-helper")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    return UNKNOWN_VERSION
