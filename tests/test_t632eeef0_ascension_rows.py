"""t_632eeef0 (CRIT v1.2.0): ranksForItem season-ladder fallback.

Real addon exports / Armory loads carry no `# upgrade_levels=` comments, so
exportRanksFor is null for every real character and rank/Ascendant rows were
unreachable (t_6b3f65d6). The fallback expands the season ladder from the
Wowhead-hydrated / inferred {track, rank} grade in state.gearUpgrades, with a
flood guard (equipped / selected / added items only) and crafted skip.

Behaviour test over the real ES modules through node (offline fallback
season: myth [272,276,279,282,285,289], hero [259..276], cost_per_rank 20
Dawncrest, Ascendant Voidforged cost 5, results hero 285 / myth 298).
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "web" / "static"


def _node_binary() -> str:
    # same lookup as test_gui_rewrite_gates._node_binary
    node = shutil.which("node")
    if node:
        return node
    bundled = sorted(
        Path.home().glob(".hermes/tools/node-*/bin/node"),
        key=lambda p: p.parts[-4] if len(p.parts) > 3 else str(p),
    )
    if bundled:
        return str(bundled[-1])
    pytest.skip("node not available; ranksForItem harness needs it")


HARNESS = r"""
const J = (r) => 'file://__STATIC__/js/' + r;
const { state } = await import(J('core/state.js'));
const { ranksForItem } = await import(J('core/items.js'));

const eq       = 'trinket1=,id=1,ilevel=285';  // equipped myth 5/6
const eqTop    = 'trinket2=,id=2,ilevel=289';  // equipped myth 6/6, eligible slot
const eqHero   = 'trinket1=,id=3,ilevel=276';  // selected candidate, hero 6/6
const plain    = 'trinket1=,id=4,ilevel=285';  // candidate, hydrated: guard rejects
const sel      = 'trinket1=,id=5,ilevel=285';  // selected candidate
const added    = 'trinket1=,id=6';             // added by ID (no ilevel param)
const crafted  = 'trinket1=,id=7,ilevel=285,crafting_quality=4'; // selected crafted
const ascended = 'trinket1=,id=8,ilevel=289,bonus_id=13653';     // selected myth 6/6 already VF
const exported = 'trinket1=,id=9,ilevel=279';  // carries an export ladder
const noGu     = 'neck=,id=10,ilevel=279';     // equipped, NO gearUpgrades entry (post-deselect)
const bareSel  = 'trinket1=,id=11,ilevel=279';  // selected; entry lacks track (onRowClick select write)

state.parsedData = {
  item_upgrades: { [exported]: { levels: [{ upgrade_level: 1, ilvl_increment: 3 }] } },
  item_names: { [added]: 'Added Trinket (289)' },
  equipped_gear: { trinket1: eq, trinket2: eqTop, neck: noGu },
  items_by_slot: { trinket: [eq, eqTop, eqHero, plain, sel, crafted, ascended, exported] },
};
state.selectedItems = { trinket: new Set([sel, eqHero, ascended, crafted, bareSel]) };
state.addedItems = new Map([[added, 'trinket']]);
state.gearUpgrades = { trinket: {
  [eq]: { track: 'myth', rank: 5 },
  [eqTop]: { track: 'myth', rank: 6 },
  [eqHero]: { track: 'hero', rank: 6 },
  [plain]: { track: 'myth', rank: 5 },
  [sel]: { track: 'myth', rank: 5 },
  [added]: { track: 'myth', rank: 6 },
  [crafted]: { track: 'myth', rank: 5 },
  [ascended]: { track: 'myth', rank: 6 },
  [exported]: { source: 'export', rank: 0, item_level: 279 },
  [bareSel]: { source: 'export', rank: 6, item_level: 289, user_selected: true },
} };
state.voidforgedItems = { trinket: {} };

const out = {};
for (const [name, item] of Object.entries(
    { eq, eqTop, eqHero, plain, sel, added, crafted, ascended, exported, bareSel })) {
  out[name] = ranksForItem('trinket', item)
    .filter(r => r.rank !== null)
    .map(r => ({ rank: r.rank, ilvl: r.ilvl, vf: r.voidforged, label: r.label }));
}
out.noGu = ranksForItem('neck', noGu)
  .filter(r => r.rank !== null)
  .map(r => ({ rank: r.rank, ilvl: r.ilvl, vf: r.voidforged, label: r.label }));
console.log(JSON.stringify(out));
"""


def _run_harness() -> dict:
    script = HARNESS.replace("__STATIC__", str(STATIC))
    result = subprocess.run(
        [_node_binary(), "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"ranksForItem harness failed: {result.stderr[-2000:]}"
    return json.loads(result.stdout)


def test_season_fallback_rows_and_flood_guard():
    out = _run_harness()

    # Rank rows up the myth ladder with the season crest cost, no VF below top.
    assert out["eq"] == [{"rank": 6, "ilvl": 289, "vf": False,
                          "label": "Myth 6/6 ×20 Dawncrest"}]

    # Top-rank eligible slot: Ascendant twin row at the ascension results ilvl.
    assert out["eqTop"] == [{"rank": 6, "ilvl": 298, "vf": True,
                             "label": "Ascendant Voidforged ×5"}]
    assert out["eqHero"] == [{"rank": 6, "ilvl": 285, "vf": True,
                              "label": "Ascendant Voidforged ×5"}]

    # Flood guard: hydrated but unselected, non-equipped, non-added candidates
    # keep the single base row.
    assert out["plain"] == []

    # Selected / added candidates expand.
    assert [r["rank"] for r in out["sel"]] == [6]
    assert out["added"] == [{"rank": 6, "ilvl": 298, "vf": True,
                             "label": "Ascendant Voidforged ×5"}]

    # Crafted items skip the fallback (off-track, leader ruling comment 1885).
    assert out["crafted"] == []

    # Already-Voidforged top pieces never get a second ascension row.
    assert out["ascended"] == []

    # The export ladder stays preferred: rows carry export labels only.
    assert [r["label"] for r in out["exported"] if "Myth" in (r["label"] or "")] == []
    assert out["exported"][0] == {"rank": 1, "ilvl": 282, "vf": False, "label": "Upgrade 1"}

    # Deselect drops the gearUpgrades entry (onRowClick); the fallback reseeds
    # from the same ilvl→ladder inference state.js uses, so rows survive.
    assert [r["rank"] for r in out["noGu"]] == [4, 5, 6]
    assert out["noGu"][-1]["label"] == "Myth 6/6 ×20 Dawncrest"

    # A selected item whose entry lacks a track (onRowClick's bare write) also
    # reseeds instead of losing its rows.
    assert [r["rank"] for r in out["bareSel"]] == [4, 5, 6]
    assert all(not r["vf"] for r in out["bareSel"])
