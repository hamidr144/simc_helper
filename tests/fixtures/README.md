# Test fixtures

## Real nightly SimC output (t_1651ba9b)

These fixtures are **verbatim output of the production SimC nightly
engine** — not hand-written mocks. They exist so the suite certifies the
four P0 failure classes against what the engine actually emits:

| File | What it is |
|---|---|
| `simc_nightly_report_multicopy.html` | HTML report, base actor + 2 gear copies + pet |
| `simc_nightly_report_baseline_only.html` | HTML report, zero-combo baseline run (first player section carries `class="toggle open""`) |
| `simc_nightly_console_multicopy.log` | Engine console output incl. the `DPS Ranking:` block |
| `simc_nightly_simhelper_zero_combo.log` | `sim_helper` stdout for the zero-combo baseline run |
| `simc_nightly_simhelper_multicopy.log` | `sim_helper` stdout for the staged 3-run pipeline |
| `simc_input_zero_combo_real.simc` | Real addon export with all `copy=` blocks removed |
| `simc_input_multicopy_real.simc` | Same export, first 2 `copy=` blocks kept |

Provenance: SimulationCraft 1210-01 for WoW 12.1.0.69933 Live (git build
midnight eaf8c46), running the real Hamidriel Retribution export
(`data/master/inputs/fa2e86c3-c44.simc`, `talents=` line dropped — stale
hash rejected by the nightly) inside `simc_helper-simc-worker-1` on
2026-10-15. Trimming is size-only: per-player sections reduced to header
+ params + first gear rows; progress-bar `\r` spam collapsed. All dps
values, markup and gear links are verbatim.

### Regenerating

```sh
# 1. trim the export (see provenance above), then run inside the worker:
docker cp in.simc simc_helper-simc-worker-1:/tmp/in.simc
docker exec simc_helper-simc-worker-1 python3 /app/src/cli/sim_helper.py \
  simc_path=/app/thirdparties/simc-nightly/simc input_file=/tmp/in.simc start_server=0
# 2. copy the announced /tmp/simc_reports/report_*.html and the console
#    output back out and trim as above (header + params + 3 gear rows).
```

The full-pipeline tests replay these logs through a stub engine; set
`SIMC_ENGINE_BIN` to a real nightly binary (or a docker wrapper for the
worker container) to additionally run
`tests/test_integration.py::TestRealNightlyEngineCertification` against
the live engine.

## Other fixtures

- `simc_report_nightly_snippet.html` — trimmed real report from task
  e4c3035c (t_fdd385ef regression).
- `armory/` — Armory API response fixtures for `test_armory.py`.
- `realms_dropdown.*` — realm-list dropdown harness fixtures.
