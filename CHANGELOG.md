# Changelog

All notable user-visible changes to simc_helper are documented here.

Convention: one section per released version (semver tag, date), newest first.
Entries are categorized under `### Features`, `### Improvements`, `### Bug fixes`
— one short line per user-visible change, Kanban task id in parentheses where the
commit carries one. Before each `dev → prod` milestone merge, the entry set for the
new version is prepared and reviewer-approved as a mandatory step (see WORKFLOW.md,
"Milestone: dev → prod"); the `CHANGELOG.md` update ships in the same merge commit
that bumps the version and tag.

## [Unreleased] — next prod milestone

Candidate version: `v1.0.0` — per WORKFLOW.md the first milestone merged from the
`1.0.0-dev.N` line ships as `v1.0.0`; the final number (MINOR/MAJOR/PATCH) is ruled
at merge time. Entries consolidated from `git log prod..dev` (dev at `v1.0.0-dev.29`,
72 commits ahead of `v0.1.1`).

### Features

- Midnight live gear state with support for crafted gear ascension (t_e06d90d1).
- Full web UI redesign: design tokens, auth pages, session banner, progress bar, gear upgrade popover, enhancement search and collapsible sections, results table with sticky columns, history cards, responsive layouts down to 390px (t_2ab8f3be, t_cafaaf01).
- Enchant/gem state chips on gear slot headers showing live counts; clicking a chip jumps to the matching enhancement section (t_5e099a0a, t_61442157).
- Combinations mode: generate simc outputs for multiple finger/trinket pairings at once, with a server-side budget cap (`SIMC_TG_MAX_COMBINATIONS`, default 5000) and a stage-1 time estimate (t_8bf63ec6).
- More accurate results: mean ±error reported end-to-end, with error, %vs-best and sidegrade bands in the comparison table (t_791b16f5, t_590f5317).

### Improvements

- Live task progress on the dashboard now reflects worker status pushes instead of staying idle (t_14e40e6c).
- Login/register form errors show a styled error box after redirect (t_6f351b30).
- Runs survive a master restart via the reconnect/resume protocol; worker temp workspaces are cleaned up and no longer leak across runs (t_acd39188, t_3075ffff).
- User-initiated Stop is terminal — the worker retry loop no longer restarts the sim (t_a0bb3a07).
- The configured sim cooldown is enforced instead of a hardcoded 30 s, with a `SIM_COOLDOWN_SECONDS` env override (t_c610c962).
- 0-DPS pet/utility profiles are filtered out of parsed report results (t_aec3a925).
- Closing one browser tab no longer kills another tab's live progress stream (t_5d6903e4).
- Run attribution and history rows survive a master restart (t_2c718ca6).
- Gear links keep their item icons in tooltips with colored link text (t_268f5264).
- Accessibility: enhancement groups closed by default with a checked-count summary and skip-link fix, results table gets a screen-reader caption and proper column headers, gear slot headers wrap instead of overflowing at 390px, and the whole GUI-redesign chain passed a tab-stop/keyboard audit (t_16e4f177, t_dccc2343, t_ab5b5f2e, t_27ceb173, t_c918da68).

### Bug fixes

- Security hardening (ownership/authz): all API and report endpoints now require a session (`/api/get-results`, `/api/task-status`, `/api/report-url`, `/api/state`, SSE streams, `/reports`, `/inputs`); logout revokes sessions server-side; inputs and tasks are owner-checked per user; a simulation never falls back to another user's input and `latest` results are caller-scoped (t_5071ad92, t_550f7d79, t_8d011d53, t_e1b11498, t_28df6d81, t_2447fdbd, t_0e328148, t_a4ff7b5d, t_2f386596, t_ff260cdb, t_1e5e7fb4).
- Worker upload failures now raise instead of being silently swallowed (t_a13e5be8).
- Non-SimC export text is rejected with a 400 error on addon parsing (t_0cb6af81).

## [0.1.1] — 2026-10-16

First tagged prod release (`v0.1.1`); changes before it were not tracked in this file.
