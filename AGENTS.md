# Project guide

SimC Helper is a Python/FastAPI master and SimulationCraft worker cluster with a
vanilla JavaScript web UI. Development workflow is supplied by the active agent
harness; this file contains project navigation rather than a second workflow.

- `README.md`: overview, setup and usage.
- `src/web/`: FastAPI master and static browser UI.
- `src/worker.py`, `src/cli/`, `src/core/`: worker execution, simulation commands
  and shared application logic.
- `utils/` and `examples/`: operational tools and safe configuration templates.
- `tests/`: Python regression tests and browser-independent JavaScript fixtures.
- `docs/`: detailed configuration, deployment and application documentation.

The application version comes from `pyproject.toml`; runtime resolution is in
`src/core/version.py`. Start with focused tests for the changed area; the full
Python suite runs with `python3 -m pytest -q`.
