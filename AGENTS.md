# Repository workflow

Follow **WORKFLOW.md** at the repo root. Summary: cut a `feature/<kanban-id>-<slug>` branch from `dev`, test on the dev system (port 8001), merge to `dev` via reviewed PR. `prod` is merged only by the leader at approved milestones. Never commit directly to `dev` or `prod`.
