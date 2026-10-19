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

Three GitHub App bots, three roles (GHWR-5 identity matrix, user-approved 2026-10-18). The shared fine-grained PAT was **revoked 2026-10-19 — no fallback identity exists**; the apps are the only automation identity. The personal account is out of the daily flow too. If a token cannot be minted, block the card — there is nothing to fall back to.

| Role | App (id) | Held by | May |
|------|----------|---------|-----|
| CODING | Hamidr144's Hermes Agent (5371925) | every worker profile (developer, frontend, tester, writer, devops, architect, researcher) | push branches, commit, open PRs, push review fixes |
| REVIEW | Hermes Agent Reviewer (5372752) | reviewer profile only | post review threads + real `APPROVE`/`REQUEST_CHANGES` **state** reviews (permissions: contents/checks/issues **read**, `pull_requests` write); no contents-write access, so its APPROVE is a **non-counting audit marker** — GitHub does not count it toward the required-approvals gate; still never pushes or merges (lane rule; direct pushes are ruleset-blocked anyway) |
| MERGE | Hermes Agent Leader (5372784) | leader profile only | merge PRs — posting its own **counted** `APPROVE` (the ruleset's required 1/1) at the final head immediately before each merge; repo management incl. the only protection-write grant; never pushes branches and does no independent review work beyond that pre-merge approve |

- **Auth plumbing:** every `gh`/`git push` runs on a freshly minted 1h installation token: `GH_TOKEN=$(~/.hermes/bin/gh-mint) gh ...` (helper resolves the app from `$HERMES_PROFILE`: leader→MERGE, reviewer→REVIEW, anything else→CODING). Tokens never touch disk or logs; **never** persist one with `gh auth login`. Keys: `~/.hermes/secrets/*.pem` chmod 600. Gotcha: the mint JWT `alg` must be exactly `RS256` (GitHub's own docs' `Rs256` casing returns 401 on every endpoint).
- **Cross-app identity is the mechanism:** PR authors are always the CODING app; GitHub forbids self-approval, so the counted approval comes from the third identity — the **MERGE (leader) app posts its own real `APPROVE` state review at the head immediately before merging** (that is the ruleset's required 1/1; `VERDICT:` prose alone never counts). The REVIEW app's independent `APPROVE`/`REQUEST_CHANGES` state review is the **audit record** the process runs on (see Review verdicts below); it is not the counting gate.
- **Protection truth:** the repository ruleset `pr-only-dev-prod` (id **25353043**, targeting `refs/heads/dev` and `refs/heads/prod`) is the single protection mechanism: updates restricted, deletions blocked, force-pushes blocked, PR required with **`required_approving_review_count = 1`**, **`dismiss_stale_reviews` on** (any push after an approval invalidates it), **no direct pushes**. Bypass list (live and read-back-verified 2026-10-19): the **repo admin role** (always — the user's browser break-glass) and the **MERGE (leader) app with `pull_requests_only`** — the leader may merge approved PRs but cannot push. Agents never create, edit or delete rulesets or branch protection except on an explicitly leader-authorized card (precedents: GHWR-2, GHWR-5, the 2026-10-19 merge-lane bypass) and then only with the MERGE app's token; the user remains the ultimate authority via the browser.

## Day-to-day: change → dev

All changes reach `dev` (and `prod`) **only through a GitHub PR merged by the leader via the REST merge endpoint (step 8)**. The ruleset rejects **every** direct push to these branches — including pushing the exact head sha of an open PR, which legacy protection alone used to silently accept and auto-merge the PR (t_5f7990f2). There is no local `git merge` into `dev`/`prod` and no `git push origin dev` anymore; don't try, it fails (`GH013: Cannot update this protected ref` / `GH006: Protected branch update failed`).

**CI runs on every PR** whose base is `main`, `dev` or `prod` (`ci.yml` triggers on `pull_request.branches`, which filters on the PR's base branch; there are no path filters, so docs PRs get checks too). If `gh pr checks <pr>` shows *no checks at all*, CI did not run — that is not a pass. The dev line's suite has never run on GitHub runners; expect early red dev-PR runs — treat each as a finding to investigate or fix, not an automatic merge blocker.

1. `git switch dev && git pull`
2. `git switch -c feature/t_xxxxx-slug` — **one Kanban task, one branch.** Never commit directly to `dev` or `prod`.
3. Implement, add/adjust tests.
4. Test on the **dev system** (see below). Never test on prod.
5. Push the branch and open the PR (as the CODING bot — see Identity above). **Push over HTTPS, never SSH**: an `origin` using `git@github.com:` silently authenticates with a personal SSH key, bypassing the bot identity entirely (worktrees inherit the shared remote; fix once per checkout with `git remote set-url origin https://github.com/hamidr144/simc_helper.git` — the global `gh auth git-credential` helper honors `GH_TOKEN`).
   ```bash
   export GH_TOKEN=$(~/.hermes/bin/gh-mint)   # fresh 1h token; re-mint on 401
   git push -u origin feature/t_xxxxx-slug
   gh pr create --base dev --title "t_xxxxx: <summary>" --body "<kanban task id, changes, test evidence>"
   ```
6. Review happens **on the PR as the REVIEW bot** (`GH_TOKEN=$(~/.hermes/bin/gh-mint) gh pr review <pr> --repo hamidr144/simc_helper --approve|--request-changes -b "VERDICT: APPROVE|REQUEST-CHANGES — <summary>"` — keep the `VERDICT:` first line for humans; this state review is the non-counting audit record — the counted approve is the leader's pre-merge one, step 8). Pin the review to the exact head via the API when combining inline comments — `gh pr review` has no inline-comment support:
   ```bash
   GH_TOKEN=$(~/.hermes/bin/gh-mint) gh api repos/hamidr144/simc_helper/pulls/<pr>/reviews --method POST --input review.json
   # review.json: {"commit_id":"<head-sha>","event":"APPROVE|REQUEST_CHANGES","body":"VERDICT: ...",
   #   "comments":[{"path":"<file>","line":<N>,"side":"RIGHT","body":"<note>"}]}
   ```
   (`line` must fall inside a diff hunk or the whole call 422s.) Author addresses **every** comment with follow-up commits pushed to the same branch and replies on each inline thread (`gh api repos/hamidr144/simc_helper/pulls/<pr>/comments/<comment-id>/replies -f body="…"`), then requests re-review.
7. **Version bump:** as the last commit before requesting final review, `git fetch origin dev` and bump `pyproject.toml` to the next `X.Y.Z-dev.N` — recompute N from the freshly fetched tip at that moment (another PR may have merged while you worked). Docs-only PR: skip (version-exempt).
8. Once **the REVIEW bot's audit review sits at the current head** and CI has run, **the leader posts its own counted `APPROVE` with the MERGE identity at that exact head — the ruleset's required 1/1, since GitHub does not count the REVIEW app's approve — and immediately merges via the REST merge endpoint** (the ruleset rejects the merge server-side without a counted approve; only the bypass actors above could override it, and the lane rule forbids merging before the review flow has produced its audit verdict — the leader included). The author never merges their own PR; workers never merge:
   ```bash
   GH_TOKEN=$(~/.hermes/bin/gh-mint) gh api --method PUT repos/hamidr144/simc_helper/pulls/<pr>/merge -f merge_method=merge   # leader profile only
   ```
   **Gotcha — do not "fix" this back to `gh pr merge`:** even with the Leader token, `gh pr merge` aborts in its own precheck (`mergeStateStatus: BLOCKED`) because gh does not apply the PR-context ruleset bypass. The REST `PUT …/merge` call above is what the `pull_requests_only` bypass actually lets through server-side. (The endpoint does not delete the head branch; branch cleanup, if wanted at all, is a separate call — milestone heads must never be deleted.)
9. Tag + deploy: **the leader** tags the merge commit `vX.Y.Z-dev.N` and pushes the tag explicitly. The merge commit exists only on the remote, and `dev` itself needs no push (the merge already updated it; pushing it would hit protection anyway):
   ```bash
   git fetch origin dev                      # brings the merge commit into origin/dev
   git tag vX.Y.Z-dev.N refs/remotes/origin/dev && git push origin vX.Y.Z-dev.N
   # one-shot without fetching: git push origin <merge-sha>:refs/tags/vX.Y.Z-dev.N
   ```
   Note `git push --follow-tags` does not work here: it skips lightweight tags and your local repo doesn't have the merge commit yet. Then deploy to the dev system (below) → tester verifies acceptance criteria on the running system.

### Review verdicts

Reviews are **real state reviews** cast by the REVIEW app (see Identity above): they are the **audit record** of the review process, not the counting gate — the app has no contents-write access, so GitHub does not count its approve toward the ruleset's required-approvals gate. The counted 1/1 is the MERGE app's own `APPROVE`, which the leader posts at the final head immediately before merging (live since 2026-10-19, e2e-proven on GHWR-6). The ruleset **auto-dismisses stale approvals on new pushes** (`dismiss_stale_reviews`), so any fix-round commit voids the previous review state: the reviewer re-approves after the final commit — audit-pin practice, keeping the record pinned to what actually merges (it is not what unblocks the merge). The reviewer still pins the review to the exact head (`commit_id`) and the leader verifies the reviewed head is the merge tip before merging (GHWR-4 practice). Keep the first body line as `VERDICT: APPROVE` / `VERDICT: REQUEST-CHANGES` for human and Kanban parity. The Hermes kanban reviewer card remains the binding process record — the GitHub review is its mirror.

## Milestone: dev → prod

A milestone is ready when the main feature is **completed, tested on the dev system, documented (README/docs updated), and approved by the leader.**

**Mandatory pre-merge step (before opening the PR):** prepare the `CHANGELOG.md` entry for the new version — regenerate/append from `git log --oneline prod..dev`, consolidate to user-visible changes categorized under `### Features` / `### Improvements` / `### Bug fixes` (security fixes go under Bug fixes), and get reviewer approval on the entry set. The `CHANGELOG.md` update ships in the milestone PR branch together with the version bump.

Only the leader opens and merges the `dev → prod` PR:

```bash
# version bump + changelog go in a branch cut from dev (same bump rule as day-to-day), pushed:
gh pr create --base prod --head milestone/<version> --title "milestone: v<NEW.VERSION>" --body "<milestone summary>"
# leader merges once approved and CI has run — same REST merge call as day-to-day (never gh pr merge, see the step-8 gotcha; it never deletes the protected milestone head), then tags the merge commit (same tag mechanics as day-to-day):
gh api --method PUT repos/hamidr144/simc_helper/pulls/<pr>/merge -f merge_method=merge
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
- **The leader merges (MERGE identity, 1 approving review required server-side); the author never merges their own work; workers never merge and never touch branch protection or rulesets** (only leader-authorized protection cards do, via the Leader app token; the user via browser remains ultimate authority).
- CI runs on every PR (dev and prod bases included); no checks ≠ passing checks.
- Prod is never used for testing, and no prod ship without explicit approval. Dev system data is disposable; prod data is not.
- Every prod deploy is from a tagged commit; every tag is a merge commit on its branch, with a version bump in its PR branch.
