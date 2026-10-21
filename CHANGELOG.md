# Changelog

All notable user-visible changes to simc_helper are documented here.

Convention: one section per released version (semver tag, date), newest first.
Entries are categorized under `### Features`, `### Improvements`, `### Bug fixes`
— one short line per user-visible change, Kanban task id in parentheses where the
commit carries one. Before each `dev → prod` milestone merge, the entry set for the
new version is prepared and reviewer-approved as a mandatory step (see WORKFLOW.md,
"Milestone: dev → prod"); the `CHANGELOG.md` update ships in the same merge commit
that bumps the version and tag.

## [1.2.0] — 2026-10-21

MINOR milestone carrying the full UI redesign epic from the `1.1.1-dev.N`
line (MINOR per WORKFLOW.md milestone rule; the version number is the
leader-ruled one-ship prod boundary). Merged from dev at tag `v1.1.1-dev.2`
(`3d44e68`). Entries regenerated from `git log prod..dev`.

### Features

- Complete web UI redesign (headline): a design-token layer with light and
dark palettes and a three-state System/Light/Dark theme stored across visits
and applied before first paint; all five pages rebuilt — setup/gear, results,
run, login (t_0fb5fde9).
- Gear page rebuilt as per-slot sections with enriched equipped cards and
always-visible compact candidate rows: one click to select, second click to
revert, per-slot locks, sort and Add-by-ID, per-slot enchant/gem sections,
and a run bar with stage-1 time estimate (t_0fb5fde9).
- Results page: verdict band up top; a "Best combination — full set" panel
covering all 14 slots with swapped and kept slots instantly distinguished,
gems and source-labelled recommended enchants/gems shown, and one-click
apply-set; per-slot Recommended upgrades rows with a Use-this flow back to
gear; a combinations register for combination runs (per-slot quality chips,
one bundle-level delta); the ranked table in raw engine order with a
±error sidegrade band; a runs panel with report links; and a quarantine
panel that states honestly why failed or meaningless runs were excluded
(t_0fb5fde9, t_417d5646, t_437af933, t_caa8448f).
- Draft persistence: the pasted export and all selections survive reloads and
navigation; applying from results queues the choice and lands back on gear
with it selected (t_0fb5fde9).

### Improvements

- Every rendered text pair meets WCAG AA contrast (≥4.5:1) in both palettes
(C-2 ruling; guarded by a programmatic sweep) (t_0fb5fde9).
- Layouts hold down to 390px: the two-column gear grid collapses to one
column and pages no longer scroll sideways on phones (t_0fb5fde9).
- Honest-absence surfaces: pre-run deltas are ilvl-only (never fake
percentages), recommendation chips are always dashed and source-labelled,
and data the engine does not output renders as nothing instead of zeros
(t_0fb5fde9).

### Bug fixes

- One malformed Wowhead tooltip entry no longer crashes the whole results
render; it degrades to a pending chip (t_0fb5fde9).
- A stray comment terminator in the token stylesheet could swallow the
entire colour palette and leave the app unstyled; fixed and pinned by a
comment-balance guard test (t_0fb5fde9).

## [1.1.1] — 2026-10-20

PATCH milestone merged from the `1.1.1-dev.N` line for the ship-blocking
run-bar defect (t_754e1374). Merged from dev at tag `v1.1.1-dev.1`
(`ae83356`). Entries regenerated from `git log prod..dev`.

### Bug fixes

- Run button no longer hidden on narrower windows: the run bar now wraps
  within the viewport instead of overflowing, fixing the Run CTA being
  clipped below ~1510px width; the sheet-band summary also reflows so it no
  longer overflows at 390px mobile width (t_754e1374).

## [1.1.0] — 2026-10-20

MINOR milestone merged from the `1.0.0-dev.N` line carrying the Midnight GUI
epic (features, per WORKFLOW.md MINOR rule). Merged from dev at tag
`v1.0.0-dev.38` (`d4d1dd6`), 15 commits ahead of `v1.0.1`. Entries consolidated
from `git log prod..dev`.

### Features

- Midnight gems and enchant selection: the full Midnight catalog ships in the
  config (44 selectable enchants plus 35 + 4 gems), and the server maps
  enchant groups to gear slots when generating simc input (t_3da0efb2,
  t_94a15fe3).
- Results open automatically when a run finishes: the top-ranked combination
  per slot plus the other combinations as rows diffed against the best,
  listing only the changed items with their DPS and delta (t_94a15fe3).
- Gear setup rebuilt as a two-column paper-doll layout following the in-game
  character/armory slot order; every slot and enhancement section is shown
  instead of hidden, while only equipped items stay selected by default
  (t_94a15fe3).
- The running app version is displayed in the page footer and served at the
  public `GET /api/version` endpoint (t_3da0efb2, t_94a15fe3).

### Improvements

- Smarter stage splitting for combination runs: a survivor floor of
  `max(4, ceil(N/4))` keeps the last stage meaningful, stage 1 is skipped
  below 17 combos and all stages below 5, so small-combination runs no longer
  end in a one-combo last stage; explicit stage-percent overrides opt out of
  the floor (t_3da0efb2).
- The page stays static when simulation options change — elements no longer
  shift position (t_94a15fe3).
- More space between page elements (t_94a15fe3).
- Docs: the docker-compose `config.json` bind-mount caveat — a missing file
  becomes an empty directory and the app silently falls back to defaults
  (t_2ec06f33).

## [1.0.1] — 2026-10-19

PATCH milestone merged from the `1.0.0-dev.N` line (single user-visible fix, per
WORKFLOW.md PATCH rule). Merged from dev at tag `v1.0.0-dev.36` (`5df8e33`).
Entries consolidated from `git log prod..dev`.

### Bug fixes

- Crafted gear cards no longer claim `Crafted · no grade`: the badge, the upgrade
  popover state line and the review Grade column now show the real craft tier from
  the addon export (`Crafted · Quality N/5`), falling back to no-grade only when the
  export genuinely carries no `crafting_quality` (t_0769a998, t_16385044).

## [1.0.0] — 2026-10-19

First milestone merged from the `1.0.0-dev.N` line to prod; per WORKFLOW.md the
prerelease suffix drops (`1.0.0-dev.35` → `v1.0.0`; MINOR/MAJOR/PATCH confirmation
is ruled at merge time). Merged from dev at tag `v1.0.0-dev.35` (`e8daea6`),
131 commits ahead of `v0.1.1`. Entries consolidated from `git log prod..dev`.

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
- Gear selection rows are compact single-line cards, fitting the reference export without scrolling (t_9fdd2c1b).
- Slot-conflict guard: selecting an off-hand together with a two-handed weapon is rejected instead of building an invalid gear set (t_8d577e52).
- Results view polish: run mode chip, a single ranked comparison table, and replaced-context tooltips.
- Accessibility: enhancement groups closed by default with a checked-count summary and skip-link fix, results table gets a screen-reader caption and proper column headers, gear slot headers wrap instead of overflowing at 390px, and the whole GUI-redesign chain passed a tab-stop/keyboard audit (t_16e4f177, t_dccc2343, t_ab5b5f2e, t_27ceb173, t_c918da68).

### Bug fixes

- Security hardening (ownership/authz): all API and report endpoints now require a session (`/api/get-results`, `/api/task-status`, `/api/report-url`, `/api/state`, SSE streams, `/reports`, `/inputs`); logout revokes sessions server-side; inputs and tasks are owner-checked per user; the `/reports` mount is per-owner; a simulation never falls back to another user's input and `latest` results are caller-scoped (t_5071ad92, t_550f7d79, t_8d011d53, t_e1b11498, t_28df6d81, t_2447fdbd, t_0e328148, t_a4ff7b5d, t_2f386596, t_ff260cdb, t_1e5e7fb4, t_71013ac2).
- Worker upload failures now raise instead of being silently swallowed (t_a13e5be8).
- Non-SimC export text is rejected with a 400 error on addon parsing (t_0cb6af81).
- 344-level Elevated Mythic gear no longer offers the Ascendant Venomstone option, and crafted-base ascension now actually generates the ascended override via an explicit Hero/Mythic grade selector (t_60c19e5d, t_98470ac5).
- Combinations results are no longer skewed by relocated profile options, and culled copy sources no longer crash the sim run (t_662ff323).
- Oversized combinations requests are budget-checked on the pre-dedup product before any generation, answering 422 instead of exhausting server memory; baseline integrity is enforced upload→generate→dispatch (t_acfe75a9, t_2afcc382).
- Gear labels in nightly reports are whitespace-normalized so they match the slot map, and item names parsed from addon exports are no longer corrupted by export meta comments (t_ebcd03f1, t_f3a2ec36).
- Long workflow-status messages in the run bar clamp to two lines with an ellipsis and tooltip instead of breaking the layout (t_5c33fefb).

## [0.1.1] — 2026-10-16

First tagged prod release (`v0.1.1`); changes before it were not tracked in this file.
