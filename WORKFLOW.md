# simc_helper — Development Workflow

Two long-lived branches, two systems, one rule: **nothing reaches `prod` without a leader-approved milestone.**

## Branches

| Branch | Deploys to | Version scheme |
|--------|-----------|----------------|
| `prod` | Production system (http://127.0.0.1:8000; external TLS front is host infra, not in this repo) | `vMAJOR.MINOR.PATCH` (e.g. `v1.1.0`), tagged on every merge |
| `dev`  | Dev/test system (http://127.0.0.1:8001) | `vMAJOR.MINOR.PATCH-dev.N` (e.g. `v1.2.0-dev.3`), tag each test deploy |
| `feature/<kanban-id>-<slug>` | — (cut from `dev`, short-lived) | — |

Version format is [Semantic Versioning](https://semver.org):
- **MAJOR** — breaking change (API/config/data incompatible)
- **MINOR** — milestone feature merged to prod
- **PATCH** — hotfix on prod, or fix before next milestone
- **`-dev.N`** — SemVer prerelease; the dev line advances N with each deploy to the test system. When dev merges to prod, the version drops the suffix (`1.2.0-dev.7` → `v1.2.0`).

The current release version lives in `pyproject.toml` (`version = ...`) and is bumped in the same merge commit that goes to the target branch.

## Day-to-day: change → dev

1. `git switch dev && git pull`
2. `git switch -c feature/t_xxxxx-slug` — **one Kanban task, one branch.** Never commit directly to `dev` or `prod`.
3. Implement, add/adjust tests.
4. Test on the **dev system** (see below). Never test on prod.
5. Open PR `feature/... → dev`. Reviewer approval + tests green required (author never approves own work).
6. Merge to `dev` → deploy to dev system → tester verifies acceptance criteria on the running system.
7. Delete the feature branch.

## Milestone: dev → prod

A milestone is ready when the main feature is **completed, tested on the dev system, documented (README/docs updated), and approved by the leader.** Only the leader merges `dev → prod`:

```bash
git switch prod && git merge --no-ff dev   # bump version + changelog in merge
git tag v<NEW.VERSION>
git push origin prod --follow-tags
# deploy prod system (see below) and verify /health
```

Every merged milestone bumps the prod version (MINOR for features, MAJOR for breaking, PATCH for prod hotfixes — hotfixes are also cherry-picked back to `dev`).

## The two systems

| | Prod system | Dev system |
|---|---|---|
| Checkout | `~/Hermes-work/simc_helper-prod` (git worktree, branch `prod`) | `~/Hermes-work/simc_helper` (main checkout, branch `dev`) |
| Compose project | `simc_helper` (existing data volumes — **never `down -v`**) | `simc-dev` (disposable data) |
| URL | http://127.0.0.1:8000 (TLS front is host infra, outside this repo) | http://127.0.0.1:8001 |
| Image tags | `simc-helper:latest` / `:latest-amd64` | `simc-helper:dev` / `:dev-amd64` (`IMAGE_TAG=dev` in `.env`) |

### Deploy dev system (after merge to `dev`)

```bash
cd ~/Hermes-work/simc_helper
git pull
docker build -t simc-helper:dev . && docker build --platform linux/amd64 -t simc-helper:dev-amd64 .
docker compose up -d --force-recreate simc-master simc-worker   # .env: IMAGE_TAG=dev, PORT=8001
curl -s http://127.0.0.1:8001/health
```

### Deploy prod system (after leader-approved milestone merge)

```bash
cd ~/Hermes-work/simc_helper-prod
git pull
docker build -t simc-helper:latest . && docker build --platform linux/amd64 -t simc-helper:latest-amd64 .
docker compose up -d --force-recreate simc-master simc-worker
curl -s http://127.0.0.1:8000/health
```

Rollback: `git checkout <last-good-tag>` in the prod worktree, rebuild, `up -d --force-recreate`. Data lives in named volumes and survives either way.

## Quick rules

- Branch from `dev`, merge back to `dev` — never branch from or merge into `prod` directly (except leader milestone merges/hotfixes).
- Prod is never used for testing. Dev system data is disposable; prod data is not.
- Every prod deploy is from a tagged commit; every tag has a version bump in its merge commit.

<!-- GHWR-6 identity-matrix pilot probe (kanban t_90c9f97a, throwaway docs comment; no content intent). -->
