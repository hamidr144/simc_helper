# Repository workflow

Follow **WORKFLOW.md** at the repo root. Summary: cut a `feature/<kanban-id>-<slug>` branch from `dev`, test on the dev system (port 8001), open a PR via `gh pr create --base dev`, review happens on the PR via `gh pr review` (first line `VERDICT: APPROVE`/`VERDICT: REQUEST-CHANGES` — shared account, no self-approval), merge via `gh pr merge --merge`. `prod` gets its PR only from the leader at approved milestones. Never commit, merge or push directly to `dev` or `prod` — branch protection rejects it server-side.
