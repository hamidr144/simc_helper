# Simcraft Helper Suite Docs

Simcraft Helper Suite is a Python/FastAPI toolchain for parsing World of Warcraft addon exports, generating SimulationCraft profile combinations, and coordinating a master/worker SimC cluster.

## Navigation

*   [**System Architecture**](architecture.md) – Components, network protocol, directory layout, and build pipeline.
*   [**Master Node Guide**](master_node.md) – FastAPI master server, REST API reference, SSE log streaming, and worker management.
*   [**Worker Node Guide**](worker_node.md) – Headless worker daemon, PTY log streaming, and SimC compilation.
*   [**Deployment Guide**](deployment.md) – CMake packaging targets and `utils/deploy.py` commands.
*   [**Configuration Reference**](configuration.md) – `config.json`, deployment JSON schema, and all environment variables.

---

## Quickstart (Local Development)

```bash
# 1. Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy config template
cp examples/config.example.json config.json

# 3. Paste your /simc addon export into char_simc_addon.txt, then start:
python3 src/web/main.py
```

Default URL: `http://127.0.0.1:8000`

> [!NOTE]
> A `.env` file is only needed for Docker Compose deployments. For local dev, export variables directly in your shell or rely on the defaults.

---

## Core Philosophy

```text
Addon Export ──> Parsed Gear ──> Combo Generator ──> Cluster Dispatch ──> Live Log Stream ──> HTML Report
```

*   **Zero Manual Editing**: Automatically generates profile overrides for enchants, gems, tracks, and Voidforge.
*   **Security Focused**: Deployment configs and secrets never live in Git. All sensitive values go in `deploy_configs/` (gitignored) via the `env` block.
*   **Robust Scaling**: Master coordinates task queues; workers run SimC via PTY and upload final HTML/ZIP results.
