# Deferred Work

Durable record of wish-list scope that was cancelled off the kanban board
without being implemented, so nothing is silently lost. Every entry keeps its
original task ID; revive an item by opening a fresh task that links it (see
[Reviving an item](#reviving-an-item)).

## Why these items were deferred

The wish-list backlog was first "parked" as *ready at priority 0* (motion
`t_ca11a5d5`, 2026-10-14). That is not parking: `ready` is dispatchable by
definition, and when every queued task sits at p0, dispatch degenerates to
pure FIFO — so the oldest wish-list items kept seizing the single serial
dispatch slot while the stop-condition closing tasks never ran. Motion
`t_4e4945ff` (adopted 2026-10-14) resolved this by cancelling the remaining
wish-list rows outright and recording them here.

**Mechanism lesson for future phases:** to park work, cancel it with a written
record like this one (or move it to a non-dispatchable state). Never park work
by leaving it `ready` at a low priority.

## Cancelled wish-list items

Cancelled in the `t_4e4945ff` queue-surgery batch, 2026-10-14/15.

### Voidforged property redo — `t_73aa289c` — **next-phase priority**

- **Intent:** Rework the voidforged property: a new patch renamed and changed
  the condition of the equivalent feature. Analyze current behavior against
  Wowhead, IcyVeins, and Method, and find further sources.
- **Cancelled:** 2026-10-14, out of scope for the stop condition.
- **Why next-phase priority:** this touches the same gear surface as the
  shipped gear-stack feature and P0 fix `t_ef33100b`. Voidforged flags will
  silently rot patch over patch — the results-page parser regex is this
  project's cautionary tale of exactly that failure class (637 green tests
  coexisting with a broken pipeline). Do not let this sit.

### User database, registration, and results history — `t_13aeb029`

- **Intent:** User database with registration, authorization, and persistence
  of previous results.
- **Cancelled:** 2026-10-15 (in-flight when the batch ran).
- **Already shipped at cancellation:** users table, register/login/logout and
  session-cookie authorization (`src/core/db.py`, `src/web/main.py`).
- **Successors (live, from motion `t_9b812b05`):** the remaining results-history
  scope was decomposed into `t_c968bf8d` (move `REPORTS_DIR` to durable
  storage), `t_b3b78acd` (`run_history` table), `t_d34ced81` (`/history`
  page), and `t_c5d47786` (restart-persistence acceptance test).

### Non-public admin panel — `t_7ea892e2`

- **Intent:** Admin panel that is not exposed outside the LAN (host network:
  outside port 80 forwards to `192.168.0.4:8000`).
- **Cancelled:** 2026-10-14, out of scope for the stop condition.
- **Open design question at cancellation:** LAN-only admin port absent from
  the Caddyfile vs. Caddy `/admin` path gating with an IP allowlist.
  Re-decide against the shipped TLS fronting (`docs/tls-fronting.md`).

### Prod/test two-system rollout — `t_f7759d5c`

- **Intent:** Roll out two systems: a prod instance (exposed) and a test
  instance (for workflow testing).
- **Cancelled:** 2026-10-14, out of scope for the stop condition.
- **Partially superseded:** prod-exposure hardening shipped as TLS fronting
  (`t_d034f7e9`, `docs/tls-fronting.md`). Remaining scope — a separate test
  deployment — is deferred.

### Dungeon-slice fight duration — `t_8fcfd5e2`

- **Intent:** Confirm the default dungeon-slice duration; expectation is at
  least 20 minutes (30 preferred).
- **Cancelled:** 2026-10-14, out of scope for the stop condition.
- **Related shipped work:** `single_boss` fighting style emits
  `duration=300` (5-minute fight, commit `8bf5ae3`). Dungeon-slice duration
  tuning remains an open question.

### Deploy-config restructure — `t_231d9011`

- **Intent:** Move deploy configs out of the project git directory and give
  them a backup option.
- **Cancelled:** 2026-10-14, out of scope for the stop condition.
- **Successor:** none.

## Superseded earlier (2026-10-14)

Wish-list rows cancelled before the surgery batch because shipped work or the
security epic already covered them:

- **Security analysis of the exposed deployment** — `t_55a6d01a`. Superseded
  by security epic `t_622b11ac` and its related security tasks (`t_0fef205c`
  dev-mode lockdown, `t_d034f7e9` TLS fronting, `t_7b2796f7` CLUSTER_SECRET
  leak — all closed).
- **Official realm-list source of truth** — `t_b95aae0e`. Superseded by the
  shipped source-authoritative realm data (`realms.json` +
  `refresh_realms.py`, added in commits `28c0292`/`f399e16`; source-slug
  preservation for non-ASCII names followed in `b770b10`).

## Explicitly not deferred

- `t_7b2796f7` (CLUSTER_SECRET leaking into master access logs) is **security
  work, not wish-list**. Motion `t_ca11a5d5` adopted an explicit security
  carve-out keeping it — with epic `t_622b11ac` and `t_d034f7e9` — in the
  queue through the backlog cancellation; it closed 2026-10-14.
  Do not sweep it into any deferred-work cleanup.

## Reviving an item

1. Open a new kanban task and link the original task ID listed above.
2. Re-verify scope against current code first — parts of these items have
   already shipped (e.g. `t_13aeb029`'s auth work).
3. Assign a real priority; if the item touches the gear or parser surfaces,
   re-check for patch drift before estimating (see the voidforged note above).
