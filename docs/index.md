# Simcraft Helper Suite Docs

Simcraft Helper Suite is a Python/FastAPI toolchain for parsing World of Warcraft addon exports, generating SimulationCraft profile combinations, and coordinating a master/worker SimC cluster.

## Navigation

*   [**System Architecture**](architecture.md) – Components, network protocol, directory layout, and build pipeline.
*   [**User Simulation Workflow**](user_workflow.md) – Importing a character, selecting gear and enhancements, running comparisons, and testing expectations.
*   [**Master Node Guide**](master_node.md) – FastAPI master server, REST API reference, SSE log streaming, and worker management.
*   [**Worker Node Guide**](worker_node.md) – Headless worker daemon, PTY log streaming, and SimC compilation.
*   [**Deployment Guide**](deployment.md) – CMake packaging targets and `utils/deploy.py` commands.
*   [**Configuration Reference**](configuration.md) – `config.json`, deployment JSON schema, and all environment variables.

---

## Quickstart (Local Docker)

```bash
# 1. Configure local secrets
cp .env.docker.example .env

# 2. Build and start the master + worker
docker build -t simc-helper:latest .
docker compose up -d
```

Default URL: `http://127.0.0.1:8000`

Stop with `docker compose down`; use `docker compose logs -f simc-master simc-worker` to follow the local run.

> [!NOTE]
> The local workflow uses Docker Compose. The source-based Python commands in the node guides are intended for maintainers and troubleshooting.

---

## Core Philosophy

```text
Addon Export ──> Parsed Gear ──> Combo Generator ──> Cluster Dispatch ──> Live Log Stream ──> HTML Report
```

*   **Zero Manual Editing**: Automatically generates profile overrides for enchants, gems, tracks, and Voidforge.
*   **Security Focused**: Deployment configs and secrets never live in Git. All sensitive values go in `deploy_configs/` (gitignored) via the `env` block.
*   **Robust Scaling**: Master coordinates task queues; workers run SimC via PTY and upload final HTML/ZIP results.
