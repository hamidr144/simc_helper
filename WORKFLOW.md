# simc_helper — Development Workflow

Two long-lived branches, two systems, one rule: **nothing reaches `prod` without a leader-approved milestone.** This is the accepted GitHub workflow model (GHWR-1, leader-accepted 2026-10-18); it supersedes the PR #4/#6-era text outright.

## Branches

| Branch | Deploys to | Version scheme |
|--------|-----------|----------------|
| `dev`  | Dev/test system (http://127.0.0.1:8001) — **default branch** | `vMAJOR.MINOR.PATCH-dev.N` (e.g. `v1.2.0-dev.3`), tag each test deploy |
| `prod` | Production system (http://127.0.0.1:8000; external TLS front is host infra, not in this repo) | `vMAJOR.MINOR.PATCH` (e.g. `v1.1.0`), tagged on every merged milestone PR |
| `feature/<kanban-id>-<slug>` | — (cut from `dev`, short-lived) | — |

`main` is a CI-sandbox island with no role in this flow; it goes away once its CI test-fix is merged into `dev`. After the `v1.0.0` milestone the team moves to trunk-based development (E2): `dev` becomes the trunk, prod becomes a tag + deploy, and the `prod` branch is retired. Until then, keep the two-line flow below.

Version format is [Semantic Versioning](https://semver.org):
- **MAJOR** — breaking change (API/config/data incompatible)
- **MINOR** — milestone feature merged to prod
- **PATCH** — hotfix on prod, or fix before next milestone
- **`-dev.N`** — SemVer prerelease; the dev line advances N with each deploy to the test system. When dev merges to prod, the version drops the suffix (`1.2.0-dev.7` → `v1.2.0`).

The current release version lives in `pyproject.toml` (`version = ...`). Every PR that changes code (or anything that ships) carries the version bump as its **last commit before final review**, made in the PR branch against a freshly fetched `origin/dev` — never in the merge commit on the target branch. Docs-only PRs are version-exempt: no bump, no tag, no deploy. The dev line's baseline is `1.0.0-dev.0` (the `0.1.x` releases predate this scheme).

Tags always point at the **merge commit** on the target branch, never at a pre-merge PR head (`v1.0.0-dev.32` had to be retagged to its merge commit `c611489` for exactly this reason).

## Identity and permissions

All automation runs under identities the user controls; there is no per-profile GitHub identity.

- **Target identity: the GitHub App bot.** The user created a dedicated GitHub App for the team; it becomes the bot identity (short-lived installation tokens) for push, PR, review, merge and tag operations.
- **Fallback identity while the App is being wired up: the shared fine-grained PAT** — one GitHub account (`hamidr144`), held in the macOS keyring by every Hermes profile. Minimum matrix on it, repo-scoped to `simc_helper`: **Contents: RW, Pull requests: RW, Checks/Actions: read, Metadata: read** — and **no `Administration`** once protection has converged (below). Ruleset/branch-protection/default-branch edits then happen **in the browser by the user**.
- **The account cannot approve its own PRs** — GitHub rejects self-approval by design ([about pull request reviews](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews)). Required-approval-count settings are therefore never used; the `VERDICT:` comment convention below carries reviews.

**Protection truth:** the repository ruleset `pr-only-dev-prod` (targeting `refs/heads/dev` and `refs/heads/prod`) is the single protection mechanism: PR required with no approval count, updates restricted (admin bypass allowed *via pull requests only*), deletions blocked, force-pushes blocked. **Agents never create, edit or delete rulesets or branch protection — the user does that in the browser.** The older classic branch protection on `dev`/`prod` is removed only after the ruleset carries the deletion and force-push rules too (no window of weakness); until that convergence completes both layers may still exist, and all applicable rules stack, most-restrictive wins ([about rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)).

## Day-to-day: change → dev

All changes reach `dev` (and `prod`) **only through a GitHub PR merged by the leader via `gh`**. The ruleset rejects **every** direct push to these branches — including pushing the exact head sha of an open PR, which legacy protection alone used to silently accept and auto-merge the PR (t_5f7990f2). There is no local `git merge` into `dev`/`prod` and no `git push origin dev` anymore; don't try, it fails (`GH013: Cannot update this protected ref` / `GH006: Protected branch update failed`).

**CI runs on every PR** whose base is `main`, `dev` or `prod` (`ci.yml` triggers on `pull_request.branches`, which filters on the PR's base branch; there are no path filters, so docs PRs get checks too). If `gh pr checks <pr>` shows *no checks at all*, CI did not run — that is not a pass. The dev line's suite has never run on GitHub runners; expect early red dev-PR runs — treat each as a finding to investigate or fix, not an automatic merge blocker.

1. `git switch dev && git pull`
2. `git switch -c feature/t_xxxxx-slug` — **one Kanban task, one branch.** Never commit directly to `dev` or `prod`.
3. Implement, add/adjust tests.
4. Test on the **dev system** (see below). Never test on prod.
5. Push the branch and open the PR:
   ```bash
   git push -u origin feature/t_xxxxx-slug
   gh pr create --base dev --title "t_xxxxx: <summary>" --body "<kanban task id, changes, test evidence>"
   ```
6. Review happens **on the PR**. Reviewer: `gh pr view <pr>` / `gh pr diff <pr>`, then posts findings as a comment-type review — `gh pr review <pr> --repo hamidr144/simc_helper --comment -b "VERDICT: APPROVE|REQUEST-CHANGES — <summary>"` (see the single-account section below: only comment-type reviews go through for this account, and its `VERDICT:` first line carries the verdict). Inline comments go through the API — `gh pr review` has no inline-comment support:
   ```bash
   gh api repos/hamidr144/simc_helper/pulls/<pr>/reviews --method POST --input review.json
   # review.json: {"commit_id":"<head-sha>","event":"COMMENT","body":"<summary>",
   #   "comments":[{"path":"<file>","line":<N>,"side":"RIGHT","body":"<note>"}]}
   ```
   (`line` must fall inside a diff hunk or the whole call 422s.) Author addresses **every** comment with follow-up commits pushed to the same branch and replies on each inline thread (`gh api repos/hamidr144/simc_helper/pulls/<pr>/comments/<comment-id>/replies -f body="…"`), then requests re-review.
7. **Version bump:** as the last commit before requesting final review, `git fetch origin dev` and bump `pyproject.toml` to the next `X.Y.Z-dev.N` — recompute N from the freshly fetched tip at that moment (another PR may have merged while you worked). Docs-only PR: skip (version-exempt).
8. Once approved (see single-account rule below) and CI has run, **the leader merges. The author never merges their own PR; workers never merge.** The rule is process-enforced (identities may share one token), so honor it even when the API would let you:
   ```bash
   gh pr merge <pr> --merge --delete-branch   # leader only
   ```
9. Tag + deploy: **the leader** tags the merge commit `vX.Y.Z-dev.N` and pushes the tag explicitly. The merge commit exists only on the remote, and `dev` itself needs no push (the merge already updated it; pushing it would hit protection anyway):
   ```bash
   git fetch origin dev                      # brings the merge commit into origin/dev
   git tag vX.Y.Z-dev.N refs/remotes/origin/dev && git push origin vX.Y.Z-dev.N
   # one-shot without fetching: git push origin <merge-sha>:refs/tags/vX.Y.Z-dev.N
   ```
   Note `git push --follow-tags` does not work here: it skips lightweight tags and your local repo doesn't have the merge commit yet. Then deploy to the dev system (below) → tester verifies acceptance criteria on the running system.

### Review verdicts: the single-account limitation

All team bots share one GitHub identity, and GitHub rejects self-approval, so an approving review button-press is impossible for anyone here. Instead the reviewer posts a **comment-type review** (`gh pr review --comment`) whose **first line is exactly `VERDICT: APPROVE` or `VERDICT: REQUEST-CHANGES`**; the leader treats `VERDICT: APPROVE` as the approval. The Hermes kanban reviewer card remains the binding process record — the GitHub review is its mirror.

## Milestone: dev → prod

A milestone is ready when the main feature is **completed, tested on the dev system, documented (README/docs updated), and approved by the leader.**

**Mandatory pre-merge step (before opening the PR):** prepare the `CHANGELOG.md` entry for the new version — regenerate/append from `git log --oneline prod..dev`, consolidate to user-visible changes categorized under `### Features` / `### Improvements` / `### Bug fixes` (security fixes go under Bug fixes), and get reviewer approval on the entry set. The `CHANGELOG.md` update ships in the milestone PR branch together with the version bump.

Only the leader opens and merges the `dev → prod` PR:

```bash
# version bump + changelog go in a branch cut from dev (same bump rule as day-to-day), pushed:
gh pr create --base prod --head milestone/<version> --title "milestone: v<NEW.VERSION>" --body "<milestone summary>"
# leader merges once approved and CI has run (no --delete-branch: the milestone head is a protected long-lived branch — gh would try to delete it), then tags the merge commit (same tag mechanics as day-to-day):
gh pr merge <pr> --merge
git fetch origin prod && git tag vX.Y.Z refs/remotes/origin/prod && git push origin vX.Y.Z
# deploy prod system (see below) and verify /health
```

Every merged milestone bumps the prod version (MINOR for features, MAJOR for breaking, PATCH for prod hotfixes — hotfixes are also cherry-picked back to `dev` through a normal PR). A prod deploy is a deliberate, user-approved event — never merge-and-ship on autopilot.

## The two systems

| | Prod system | Dev system |
|---|---|---|
| Checkout | `~/Hermes-work/simc_helper-prod` (git worktree, branch `prod`) | `~/Hermes-work/simc_helper` (main checkout, branch `dev`) |
| Compose project | `simc_helper` (existing data volumes — **never `down -v`**) | `simc-dev` (disposable data) |
| URL | http://127.0.0.1:8000 (TLS front is host infra, outside this repo) | http://127.0.0.1:8001 |
| Image tags | `simc-helper:latest` / `:latest-amd64` | `simc-helper:dev` / `:dev-amd64` (`IMAGE_TAG=dev` in `.env`) |

Always pass `-p` explicitly on deploy commands. The main checkout's directory name (`simc_helper`) equals the prod compose project name, so an unqualified `docker compose` command run there targets the **prod** volumes whenever `.env` is missing or stale. `-p` overrides `COMPOSE_PROJECT_NAME` from `.env`; the `.env` values (`simc-dev` / `simc_helper`) stay as the safety net for interactive commands.

### Deploy dev system (after merged + tagged PR)

```bash
cd ~/Hermes-work/simc_helper
git pull
docker build -t simc-helper:dev . && docker build --platform linux/amd64 -t simc-helper:dev-amd64 .
docker compose -p simc-dev up -d --force-recreate simc-master simc-worker
curl -s http://127.0.0.1:8001/health
```

### Deploy prod system (after leader-approved milestone PR merge)

```bash
cd ~/Hermes-work/simc_helper-prod
git pull
docker build -t simc-helper:latest . && docker build --platform linux/amd64 -t simc-helper:latest-amd64 .
docker compose -p simc_helper up -d --force-recreate simc-master simc-worker
curl -s http://127.0.0.1:8000/health
```

Rollback: `git checkout <last-good-tag>` in the prod worktree, rebuild, `docker compose -p simc_helper up -d --force-recreate`. `git checkout <tag>` detaches HEAD, so re-attach before the next deploy: `git checkout prod && git pull`. Data lives in named volumes and survives either way.

## Quick rules

- Branch from `dev`, open PRs back to `dev` — direct push to `dev`/`prod` is blocked server-side for every push class, PR-head shas included (`GH013`/`GH006`); hotfixes reach prod through a PR too (then cherry-pick back to `dev` through a PR).
- **The leader merges; the author never merges their own work; workers never merge and never touch branch protection or rulesets** (the user edits those in the browser).
- CI runs on every PR (dev and prod bases included); no checks ≠ passing checks.
- Prod is never used for testing, and no prod ship without explicit approval. Dev system data is disposable; prod data is not.
- Every prod deploy is from a tagged commit; every tag is a merge commit on its branch, with a version bump in its PR branch.
