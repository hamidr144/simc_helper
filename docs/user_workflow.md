# User Simulation Workflow

This document is the product and testing reference for the browser-based gear comparison
workflow. Start the local installation with Docker Compose, then begin with a SimulationCraft
addon export, select alternatives to test, run the comparison, and receive results ranked
against the character's equipped gear.

## Start locally

From the project root:

```bash
cp .env.docker.example .env
docker build -t simc-helper:latest .
docker compose up -d
```

Open `http://127.0.0.1:8000`. The Compose setup starts both the master and worker required for a
comparison. Follow them with `docker compose logs -f simc-master simc-worker` and stop them with
`docker compose down`.

## Workflow summary

```text
Paste addon export -> Parse character -> Select candidates and enhancements
                   -> Run comparison -> Review ranked results
```

The equipped character is always the baseline. Every generated alternative should represent a
change from that baseline, such as another item, upgrade rank, enchant, gem, extra socket, or
Voidforge option.

## 1. Import the character

1. In World of Warcraft, run `/simc` using the SimulationCraft addon.
2. Copy the complete character export.
3. Paste it into **Setup & Addon**.
4. Select **Parse character**.

After a successful parse, the page must show the character's gear grouped by slot. The import
provides the character profile, equipped gear, bag items, item names, and any item-level or
upgrade information available in the export.

Expected behavior:

- Empty input does not start parsing.
- Invalid addon text produces a visible parsing error.
- Equipped items are selected by default.
- If a slot has no recognized equipped item, its first available item is selected as a fallback.
- Rings and trinkets are presented as shared candidate groups for their respective paired slots.

## 2. Select gear candidates

Each item card represents one candidate for its gear slot.

- Keep the equipped item selected to retain it as the baseline choice.
- Select additional items to compare them.
- Clear items that should not participate in the comparison.
- Use the Wowhead link or tooltip to verify an item when needed.

Selecting multiple items in several slots creates combinations across those slots. Users should
select only meaningful candidates because the combination count can grow quickly.

### Upgrade options

For each applicable item, the user may select an upgrade **Track** and **Rank**. The displayed
rank includes its resulting item level. Upgrade information inferred from the addon export or
Wowhead should be preselected when available.

- **No grade** removes the track/rank override.
- Crafted items display **Crafted · no grade** and do not expose upgrade controls.
- Weapons and trinkets expose **Ascendant Voidforged +9**.
- An already Voidforged item should have that option selected automatically.

### Extra sockets

The user may enable **Add/test an extra socket** for a slot. This makes socketed variations part
of the comparison and permits selected standard gems to apply to items in that slot.

## 3. Select gems and enchantments

The enhancement section lists configured choices by applicable slot.

- Only checked enchants are included as alternatives.
- Only checked standard gems are included as alternatives.
- Gems apply to items with an existing socket or to slots where an extra socket is enabled.
- Selecting several enhancements can multiply the number of generated combinations.

A practical approach is to compare a small gear set first, then run a narrower comparison with
the relevant gems and enchants.

## 4. Prepare and run the comparison

The comparison summary updates automatically when selections change. It shows the number of
selected items and candidate combinations. After each meaningful change, the application
regenerates a task-scoped SimulationCraft input.

At least one variation from the equipped baseline is required. A variation can be:

- a different item;
- an enchant or gem;
- an extra socket; or
- a different upgrade or Voidforge state.

When the generated input is ready, the user selects **Run comparison**. The application must:

1. Find an idle worker.
2. Start a task using the generated input.
3. Identify the worker running the task.
4. Stream simulation logs while the task runs.
5. Keep failures visible and actionable if input generation, worker selection, or simulation
   startup fails.
6. Navigate to the task's results only after the worker finishes and uploads the report.

Changing a selection invalidates the previous generated input; the run action must not use stale
combinations.

## 5. Review results

The results page compares every successful alternative with the equipped baseline.

It must show:

- the equipped character's baseline DPS;
- alternatives sorted from highest to lowest DPS;
- a visible **Best** label on the highest-ranked alternative;
- each alternative's DPS difference versus equipped; and
- the gear slots changed from the baseline when that information is available.

If the report contains only the baseline, the page explains that there are no alternatives to
rank. If results are not immediately available, the page retries briefly and then shows a clear
report-loading error. **Start another comparison** returns the user to the import screen.

## Testing contract

Use this workflow as the acceptance reference for web UI and API changes. Automated tests should
cover the behavior at the boundary where it is implemented:

| Workflow area | Required checks | Primary test files |
| --- | --- | --- |
| Import | Valid and invalid parsing, equipped defaults, grouped slots | `tests/test_master_api.py`, `tests/test_web_ui.py` |
| Candidate selection | Items, tracks/ranks, crafted items, Voidforge, sockets, combination updates | `tests/test_web_ui.py`, `tests/test_master_api.py` |
| Enhancements | Checked-only gems/enchants and socket eligibility | `tests/test_web_ui.py`, `tests/test_cli_logic.py` |
| Input generation | Baseline preservation, task-scoped input, stale-input invalidation | `tests/test_master_api.py`, `tests/test_web_ui.py` |
| Execution | Idle-worker selection, progress/log streaming, actionable failures | `tests/test_master_api.py`, `tests/test_worker.py` |
| Results | Baseline, ranking, DPS delta, changed gear, empty/error states | `tests/test_web_ui.py`, `tests/test_master_api.py` |

For a user-facing workflow change, update this document and the corresponding focused regression
tests in the same change. Run at least:

```bash
python3 -m pytest -q tests/test_master_api.py tests/test_web_ui.py tests/test_health.py
git diff --check
```
