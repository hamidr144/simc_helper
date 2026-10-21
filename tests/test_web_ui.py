import json
import os
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import app
from static_assets import read_css, read_js, resp  # t_94a15fe3 split pins

client = TestClient(app)

def test_web_ui_html_content():
    """
    Directly checks the HTTP page content (HTML) returned by the root endpoint.
    Verifies that crucial tags, titles, and UI elements are present in the DOM.
    """
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.text

    # Check for important HTML elements and structure
    assert "<title>SimulationCraft Helper GUI</title>" in html_content
    assert "<h1>Gear</h1>" in html_content
    assert 'id="addon-input"' in html_content
    assert 'id="btn-parse-addon"' in html_content
    assert "Import character" in html_content  # RED-3: import <details> replaces the step-1 card


def test_web_ui_uses_dashboard_layout():
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.text

    assert 'class="top"' in html_content
    assert 'class="qj"' in html_content
    assert 'id="gear-grid"' in html_content
    assert 'class="runbar"' in html_content


def test_web_ui_removes_marketing_copy():
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.text

    assert "Build smarter gear simulations" not in html_content
    assert "dense command center" not in html_content
    assert "Large paste areas" not in html_content
    assert "Choose candidates" not in html_content
    assert "Best first" not in html_content


def test_web_ui_removes_engine_update_controls():
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.text

    assert "SimulationCraft Engine" not in html_content
    assert 'id="btn-update-simc"' not in html_content
    assert 'id="btn-update-simc-main"' not in html_content
    assert 'id="simc-status"' not in html_content


def test_web_ui_styles_include_responsive_dense_layout():
    response = resp(read_css())
    assert response.status_code == 200
    css = response.text

    assert "grid-template-columns:minmax(0,1fr) 300px" in css
    assert "position:sticky" in css
    assert "@media (min-width:900px)" in css  # RED-3: zip scale 900 gear / 1000 results / 430 phone
    assert "@media (max-width:430px)" in css
    assert "@media(min-width:1000px)" in css
    assert "@media (max-width: 900px)" not in css and "@media (max-width:900px)" not in css
    assert "@media (max-width: 1200px)" not in css and "@media (max-width:1200px)" not in css
    assert "--acc:#5b8def" in css  # RED-3: v11 dark accent


def test_web_ui_applies_linear_design_system_tokens():
    response = resp(read_css())
    assert response.status_code == 200
    css = response.text

    assert "--surface:#ffffff" in css
    assert "--canvas:#f5f6f8" in css
    assert "--r-card:10px" in css
    assert "--r-ctl:7px" in css
    assert "font-weight:750" in css
    assert "background:var(--surface)" in css
    assert "--line:#dde1e8" in css


def test_gear_selection_uses_midnight_track_rank_upgrades():
    js_response = resp(read_js())
    css_response = resp(read_css())
    assert js_response.status_code == 200
    assert css_response.status_code == 200
    js = js_response.text
    css = css_response.text

    assert "seasonTracks()" in js
    assert "ranksForItem" in js
    assert "SLOT_SECTIONS" in js
    assert "gear_upgrades: state.gearUpgrades" in js
    assert "item_levels: itemLevels" not in js
    assert "inferMidnightUpgrade" in js
    assert "itemLevelFromLabel" in js
    assert ".vrow" in css
    assert ".eqc" in css
    assert ".item-level-input" not in css


def test_gear_selection_uses_compact_icon_tiles_instead_of_text_rows():
    html_response = client.get("/")
    js_response = resp(read_js())
    css_response = resp(read_css())
    assert html_response.status_code == 200
    assert js_response.status_code == 200
    assert css_response.status_code == 200

    html = html_response.text
    js = js_response.text
    css = css_response.text

    # t_268f5264: icons are app-rendered; wh.js must not iconize/rename links.
    assert "iconizeLinks: false" in html  # t_2ab8f3be: no DOM mutation of our links
    assert "renameLinks: false" in html  # t_27ceb173 (B1): wh.js must not rename our gear links (UI-2)
    assert "createWowheadIconLink" in js
    assert "vrow" in js
    assert "eqc" in js
    assert "item-icon-link" in js
    assert ".vrow" in css
    assert ".eqc" in css
    assert ".item-icon-link" in css
    assert "auto-fill" not in css
    assert "sr-only" in css


def test_gear_selection_stacks_cards_vertically():
    """Feature 1 (t_e431c027): gear candidate cards stack one per row at all
    widths — .slot-items must be a single column, never an auto-fill grid."""
    import re

    css_response = resp(read_css())
    assert css_response.status_code == 200
    css = css_response.text

    def rule_body(selector):
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert match, f"missing rule for {selector}"
        return match.group(1)

    body = rule_body("#gear-grid")
    assert "columns:2" in body, f"#gear-grid must multicol sections, got: {body.strip()}"
    assert "break-inside:avoid" in css, "sections must never split across columns (ruling O-3)"
    for selector in (".vrow", ".slotsec"):
        body = rule_body(selector)
        assert "auto-fill" not in body and "auto-fit" not in body, (
            f"{selector} must not use an auto-fill/auto-fit grid"
        )


def test_zero_combination_run_is_labelled_baseline():
    """t_4485565b: a 0-candidate selection must be offered as a baseline
    current-gear run — never hidden behind a fake '1 combination' or a
    silently-disabled Run button."""
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "Ready to run a baseline current-gear report." in js
    # Run generates input even when the client-side estimate is 0.
    assert "if (!state.generatedInput) await generateInput();" in js
    # Run stays enabled once a character is loaded.
    assert "runButton.disabled = !(state.generatedInput || state.parsedData);" in js
    # The old early-return that froze generation at 0 combinations is gone.
    assert "if (!estimateCombinations()) return;" not in js


def test_gear_selection_allows_marking_voidforged_weapons_and_trinkets():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "row.dataset.vf" in js
    assert "isVoidforgeEligibleSlot" in js
    assert "voidforged_items: state.voidforgedItems" in js
    assert "seasonAscension().name" in js


def test_voidforged_control_toggles_itself_inside_item_tile():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "state.voidforgedItems[slot][item] = vf;" in js
    assert "state.selectedItems[slot].add(item);" in js
    assert "delete state.voidforgedItems[slot]?.[item];" in js


def test_voidforged_items_are_detected_from_season_ascension_data():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "legacy_final_ilvls" in js
    assert "isAlreadyVoidforgedItem" in js
    assert "seasonAscension().name" in js


def test_named_voidforged_items_start_with_ascendant_flag_enabled():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "function isAlreadyVoidforgedItem(slot, item, label = '')" in js
    assert "String(label).toLowerCase().includes(ascendedName)" in js
    assert "voidforgedItems[slot][item] = isAlreadyVoidforgedItem" in js


def test_plain_item_level_labels_do_not_start_with_ascendant_flag_enabled():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "String(label).toLowerCase().includes(ascendedName)" in js
    assert "function finalItemLevelFromLabel(itemLabel)" not in js
    assert "const labelItemLevel = finalItemLevelFromLabel(itemLabel);" not in js


def test_voidforged_items_are_detected_from_bonus_ids_not_plain_item_levels():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "seasonAscension().bonus_ids" in js
    assert "bonuses.some(bonus => ids.includes(bonus))" in js
    assert "13622" not in js


def test_voidforged_track_rank_inference_uses_base_level_before_ascension():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "function inferMidnightUpgrade(slot, item, label)" in js
    assert "hasVoidforgeBonus(item)" in js
    assert "level -= legacyDelta;" in js


def test_upgrade_data_endpoint_serves_season_ladders():
    response = client.get("/api/upgrade-data")
    assert response.status_code == 200
    data = response.json()

    assert data["active_season"] == "midnight-s2"
    season_ids = [season["id"] for season in data["seasons"]]
    assert "midnight-s1" in season_ids and "midnight-s2" in season_ids
    s2 = next(season for season in data["seasons"] if season["id"] == "midnight-s2")
    assert s2["tracks"]["myth"] == [318, 321, 324, 328, 331, 334]
    assert s2["ascension"]["results"] == {"hero": 328, "myth": 340}
    assert 344 in s2["elevated_ilvls"]


def test_generate_accepts_upgrade_season_override():
    payload = {
        "base_profile": "warrior=Test",
        "char_class": "warrior",
        "char_name": "Test",
        "equipped_gear": {"trinket1": "id=2,ilevel=250"},
        "selected_items": {"trinket": ["id=2,ilevel=250"]},
        "selected_enchants": {},
        "selected_gems": [],
        "gear_upgrades": {"trinket": {"id=2,ilevel=250": {"track": "myth", "rank": 6}}},
        "voidforged_items": {},
        "extra_sockets": {},
        "upgrade_season": "midnight-s2",
    }
    response = client.post("/api/generate-simc", json=payload)
    assert response.status_code == 200
    generated = open(response.json()["file_path"]).read()
    # ilvl 250 alone would detect Season 1 (myth 6 = 289); the override wins.
    assert "trinket1=,id=2,ilevel=334" in generated


def test_crafted_items_do_not_auto_infer_midnight_grade_from_item_level_label():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "function isCraftedItem(item)" in js
    assert "crafting_quality=" in js
    assert "crafted_stats=" in js
    assert "if (isCraftedItem(item)) return null;" in js
    # G7 (t_0769a998): the badge derives the tier from crafting_quality;
    # "no grade" survives only as the honest fallback for exports without it.
    assert "Crafted · Quality ${n}/5" in js
    assert "Crafted · Grade ${n}" in js
    assert "Crafted · no grade" in js


def test_voidforge_option_is_hidden_for_elevated_items():
    """t_60c19e5d: ilvl-344 Elevated Myth must not offer Ascendant ascension."""
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert (
        "!ascended && isVoidforgeEligibleSlot(slot) && !isElevatedLevel(Number(parseItemParams(item).ilevel) || null)"
        in js
    )
    # RED-3: ranksForItem gates the Ascendant row twin on that condition —
    # no per-row checkbox markup exists anymore (row click encodes the flag).
    assert "const voidforge = ascensionEligible" not in js
    assert "voidforged: true, label:" in js


def test_crafted_ascension_reveals_ascended_grade_selector():
    """t_98470ac5: ticking Ascendant on a crafted base needs an explicit
    hero/myth grade; the picked track hydrates the gearUpgrades entry the
    backend resolves crafted_results (325/338) from."""
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "ascension.crafted_results?.[upgrade.track]" in js
    assert "function targetUpgradeLevel(slot, item)" in js
    # RED-3: no per-row grade dropdown — a row click encodes (rank, vf);
    # preview.js mirrors the backend crafted_results ilvl resolution.
    assert "source: 'export', rank," in js
    assert "user_selected: true," in js
def test_crafted_upgrade_state_shows_crafted_not_no_grade():
    # C2 (t_0769a998): crafted items print "Crafted" in the popover state
    # line and review-popover Grade column instead of the "No grade" lie.
    js = resp(read_js()).text
    assert "else if (isCraftedItem(item)) bits.push('Crafted');" in js


def test_crafted_badge_mapping_g4():
    # G4 (t_0769a998) synthetic self-check: run the real helpers extracted
    # from app.js through node (skipped where node is unavailable).
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    js = resp(read_js()).text

    def _fn(name):
        start = js.index(f"function {name}")
        return js[start:js.index("\n}", start) + 2]

    # R9 re-pin (t_d7293a57): 464e989 (D-2 row-title move) made
    # craftedBadgeHtml emit raw tooltip text; values pinned to that
    # reviewer-ruled intentional output.
    script = _fn("parseItemParams") + "\n" + _fn("craftedBadgeHtml") + """
const cases = [
  ["chest=,id=1,crafted_stats=36/32", "Crafted \u00b7 no grade (the addon export did not include a crafting quality)"],
  ["chest=,id=1,crafted_stats=36/32,crafting_quality=3", "Crafted \u00b7 Quality 3/5 (from the addon export)"],
  ["chest=,id=1,crafted_stats=36/32,crafting_quality=x5", "Crafted \u00b7 no grade (the addon export did not include a crafting quality)"],
  ["chest=,id=1,crafted_stats=36/32,crafting_quality=7", "Crafted \u00b7 Grade 7 (from the addon export)"],
  ["finger1=,id=251513,crafting_quality=5", "Crafted \u00b7 Quality 5/5 (from the addon export)"],
  ["chest=,id=1,crafted_stats=1/1,crafting_quality=0", "Crafted \u00b7 Quality 0/5 (from the addon export)"],
];
let fail = 0;
for (const [item, want] of cases) {
  const got = craftedBadgeHtml(item).replace(/<[^>]*>/g, "");
  if (got !== want) { console.error(item + " -> " + got + " (want " + want + ")"); fail = 1; }
}
process.exit(fail);
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_gear_row_fold_budget_immune_to_selection():
    # RED-S5F (t_45ab76c5, RED-S5 FAIL 2): foldChips's 3-row budget counts
    # every row whatever its selection state — selecting a visible row must
    # keep the identical visible set and +N count (contract §12 gate 4 "no
    # layout jitter on selection change"), and selected/excluded rows past
    # the fold stay visible (doc 4.2 parity). Real foldChips via node.
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    harness = os.path.join(os.path.dirname(__file__), "fixtures", "fold_chips_harness.mjs")
    result = subprocess.run([node, harness], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"harness failed: {result.stderr[-2000:]}"
    out = json.loads(result.stdout)
    assert out["baseline6"] == {"vis": [0, 1, 2], "chip": "+3"}
    # Pre-fix the two sel cases folded away 0/1 rows and revealed an extra
    # one: sel1of6 was vis [0,1,2,3] chip "+2", sel1of4 vis [0,1,2,3] chip
    # None — the +46px / +15px downstream shifts measured live.
    assert out["sel1of6"] == out["baseline6"]
    assert out["baseline4"] == {"vis": [0, 1, 2], "chip": "+1"}
    assert out["sel1of4"] == out["baseline4"]
    assert out["selLastVisible4"] == out["baseline4"]
    assert out["selBeyondFold"] == {"vis": [0, 1, 2, 4], "chip": "+1"}
    assert out["exBeyondFold"] == {"vis": [0, 1, 2, 5], "chip": "+2"}
    assert out["allBeyondFoldSelected"] == {"vis": [0, 1, 2, 3], "chip": None}
    assert out["expandRevealsAll"] == [0, 1, 2, 3, 4, 5]


def test_row_quality_resolver_and_draft_orphan_drop_node_probe():
    # t_e906dc02: gear-row grade resolves through ONE resolver feeding
    # qualityOf — hydration > Armory payload > param > COMMON (ruling 3) —
    # and draft/payload restore drops candidates absent from items_by_slot
    # (ruling 4). Real modules via node, fold_chips_harness.mjs pattern.
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    harness = os.path.join(os.path.dirname(__file__), "fixtures", "row_quality_harness.mjs")
    result = subprocess.run([node, harness], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, f"harness failed: {result.stderr[-2000:]}"
    out = json.loads(result.stdout)
    # Pre-fix: resolveRowQuality did not exist (harness import failed) and the
    # orphan rows came back from stale localStorage (gear.js params.quality).
    assert out["armoryGrade"] == "Epic"
    assert out["hydrationWins"] == "Rare"
    assert out["paramFallback"] == "Uncommon"
    assert out["commonFallback"] == "Common"
    assert out["draftSelected"] == ["id=268265,bonus_id=6652,ilevel=334"]
    assert out["draftAdded"] == ["id=268265,bonus_id=6652,ilevel=334"]
    assert out["payloadSelected"] == []
    # t_910b4761: committed add-by-id — the tooltip preview quality persists
    # into parsedData.item_qualities (the draft-persisted resolver slot), and
    # the ladder-unplaceable raw-id item still renders one Current rank row.
    assert out["addedCommittedEpic"] == "Epic"
    assert out["addedRows"] == ["null:base:false", "1:344:false"]


def test_add_by_id_commit_persists_preview_quality():
    # t_910b4761: commitAddedItem must persist the tooltip preview's Wowhead
    # quality into parsedData.item_qualities (resolveRowQuality slot 2, which
    # round-trips through the draft) so the committed card renders Epic
    # instead of Common; a null quality writes nothing; removeAddedItem drops
    # the entry again. Function-extraction node probe, slot-guard pattern.
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    assert node
    js = resp(read_js()).text
    commit = js[js.index("function commitAddedItem"):js.index("export function removeAddedItem")]
    rem = js[js.index("export function removeAddedItem"):js.index("function renderSlotAddPreview")] \
        .replace("export function", "function", 1)
    script = """
const state = { parsedData: { items_by_slot: {}, item_names: {} }, selectedItems: {},
  gearUpgrades: {}, voidforgedItems: {}, statScores: {}, addedItems: new Map() };
const inferMidnightUpgrade = () => null;
const renderGear = () => {}, renderCharChip = () => {}, updateSummary = () => {}, selectionChanged = () => {};
""" + commit + "\n" + rem + """
let fail = 0;
commitAddedItem('neck', 268265, { name: 'Aqirbane Reliquary', ilvl: 344, quality: 4 });
if (state.parsedData.item_qualities?.['id=268265'] !== 4) { console.error('preview quality not persisted: ' + JSON.stringify(state.parsedData.item_qualities)); fail = 1; }
commitAddedItem('head', 111, { name: 'NoQuality', ilvl: 100 });
if ('id=111' in (state.parsedData.item_qualities || {})) { console.error('absent quality wrote an entry'); fail = 1; }
removeAddedItem('neck', 'id=268265');
if ('id=268265' in state.parsedData.item_qualities) { console.error('quality not dropped on remove'); fail = 1; }
process.exit(fail);
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_add_by_id_slot_guard_node_probe():
    # t_1699829f: the client-side inventorySlot->slot guard, evaluated in node
    # (same harness pattern as test_crafted_badge_mapping_g4): a mismatch
    # suppresses the Add button and names the item's real slot; a matching
    # slot still adds; unknown ids and failed/absent invslot fail OPEN; gems
    # (id 0) and other known non-equip ids never offer an equip slot.
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    js = resp(read_js()).text
    start = js.index("const INV_SLOT_TABLE")
    table = js[start:js.index("};", start) + 2]
    fn_start = js.index("function slotAddDecision")
    fn = js[fn_start:js.index("\n}", fn_start) + 2]
    # The reject must happen before the Add button is ever rendered.
    assert js.index("if (!decision.offer)") < js.index("slot-add-confirm")
    script = table + "\n" + fn + """
const cases = [
  ["head", { name: "Warhelm", invslot: 1, invslot_name: "Head" }, true, ""],
  ["chest", { name: "Warhelm", invslot: 1, invslot_name: "Head" }, false, "Warhelm fits Head, not chest."],
  ["finger", { name: "Ring", invslot: 11, invslot_name: "Finger" }, true, ""],
  ["trinket", { name: "Trink", invslot: 12, invslot_name: "Trinket" }, true, ""],
  ["back", { name: "Cloak", invslot: 16, invslot_name: "Back" }, true, ""],
  ["shoulder", { name: "Gibbets", invslot: 3, invslot_name: "Shoulder" }, true, ""],
  ["off_hand", { name: "2H", invslot: 17, invslot_name: "Two-Hand" }, true, ""],
  ["chest", { name: "2H", invslot: 17, invslot_name: "Two-Hand" }, false, "2H fits Two-Hand, not chest."],
  ["chest", { name: "Gem", invslot: 0 }, false, "Gem fits no equip slot, not chest."],
  ["chest", { name: "Tabard", invslot: 19, invslot_name: "Tabard" }, false, "Tabard fits Tabard, not chest."],
  ["main_hand", { name: "OneHand", invslot: 13, invslot_name: "One-Hand" }, true, ""],
  ["off_hand", { name: "Shield", invslot: 14, invslot_name: "Off Hand" }, true, ""],
  ["head", { name: "NoSlotInfo" }, true, ""],
  ["head", { name: "Null", invslot: null, invslot_name: null }, true, ""],
  ["head", { name: "Future", invslot: 9042, invslot_name: "Future Slot" }, true, ""],
];
let fail = 0;
for (const [slot, preview, wantOffer, wantMsg] of cases) {
  const got = slotAddDecision(slot, preview);
  if (got.offer !== wantOffer) { console.error(slot + " " + preview.name + " offer=" + got.offer + " want " + wantOffer); fail = 1; }
  if (wantMsg && !(got.message || "").includes(wantMsg)) { console.error(slot + " " + preview.name + " msg=" + got.message + " want " + wantMsg); fail = 1; }
}
if (!slotAddDecision("head", { name: "Future", invslot: 9042, invslot_name: "Future Slot" }).showSlotName) { console.error("unknown id must name the returned slot in the meta line"); fail = 1; }
if (slotAddDecision("head", { name: "Warhelm", invslot: 1, invslot_name: "Head" }).showSlotName) { console.error("a matched slot must not append a slot name"); fail = 1; }
process.exit(fail);
"""
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_setup_boot_surfaces_saved_drafts_in_import_band():
    # t_1699829f: after a session-expiry re-login the empty import band must
    # not contradict the 401 banner — boot renders a persistent note listing
    # every saved-draft character (newest first) with the re-load instruction.
    # Draft lifecycle itself stays unchanged.
    js = resp(read_js()).text
    assert "load that character again (addon export or Armory) and your selections are restored" in js
    assert "drafts-note" in js
    assert "pendingBoot.drafts" in js
    assert ".drafts-note" in read_css()


def test_gear_selection_hydrates_exact_grades_from_wowhead():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "hydrateWowheadUpgrades(state.parsedData.items_by_slot);" in js
    assert "apiFetch('api/wowhead-upgrades'" in js  # t_2ab8f3be: 401-banner wrapper
    assert "(state.gearUpgrades[slot] ||= {})[item] = upgrade;" in js
    assert "renderGear();" in js


def test_user_chosen_upgrades_are_marked_user_selected():
    """t_ef33100b: user-chosen grades carry user_selected so the backend
    keeps them off the baseline; inferred-current entries stay unmarked."""
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    # RED-3: a row click writes the user_selected entry; clicking the
    # selected row again reverts to the equipped baseline (variantMatches).
    assert "user_selected: true," in js
    assert "if (variantMatches(slot, item, rank, vf)) {" in js
    assert "delete state.gearUpgrades[slot]?.[item];" in js
    # Wowhead hydration must not clobber a pick the user already made.
    assert "if (state.gearUpgrades[slot]?.[item]?.user_selected) continue;" in js
    # The estimator counts a user-chosen upgrade as a real variation.
    assert "Boolean(state.gearUpgrades[slot]?.[item]?.user_selected)" in js


def test_item_icons_use_local_proxy_without_requiring_wowhead_javascript():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert 'src="api/item-icon/${safeId}"' in js
    assert 'data-wowhead="${tooltipData}"' in js
    assert "domain=ptr" not in js


def test_item_icons_and_names_use_default_wowhead_tooltips():
    page_response = client.get("/")
    assert page_response.status_code == 200
    assert 'src="api/wowhead-tooltips.js?v=red3-2"' in page_response.text
    assert "power.js" not in page_response.text

    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "wowhead-item-link" in js
    assert "data-wowhead" in js
    assert "window.WH.Tooltips.refreshLinks()" in js
    assert "bonus=${safeBonus}" in js


def test_gems_and_enchantments_use_default_wowhead_tooltips():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "function createEnhancementWowheadLink(enhancement, name)" in js
    assert "enhancement.wowhead_url" in js
    assert "enhancement-name-link wowhead-item-link" in js
    assert "createEnhancementWowheadLink(enchant, name)" in js
    assert "createEnhancementWowheadLink(gem, name)" in js
    assert js.count("refreshWowheadLinks();") >= 2


def test_heliotrope_gems_are_not_rendered_as_selectable_gems():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "gems?.standard" in js


def test_current_gear_is_ready_to_run_and_selected_enhancements_are_checked():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "let total = 1;" in js
    assert "equippedEnchants[slot].has(id)" in js
    assert "equippedGems.has(id)" in js
    assert "void generateInput(true);" in js
    assert "PVP_META_NAME_MATCH" in js


def test_report_gear_summary_shows_only_slot_and_item_link():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "const statsTd = statsRow.querySelector('td.small');" not in js
    assert "const stats = statsTd ? statsTd.textContent.trim() : '';" not in js
    assert "${stats}" not in js
    # (MGE-2 A2, t_94a15fe3) gearSummary was dead in app.js; removed with the card.


def test_report_separates_baseline_and_only_lists_combo_differences():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "changesFromBaseline" in js
    assert "pickBaseline" in js
    assert "selectedItems" in js
    assert "estimateCombinations" in js
    assert "results?task_id=" in js  # t_2ab8f3be: success card link, no auto-redirect


def test_results_page_is_a_dedicated_user_friendly_view():
    response = client.get("/results?task_id=test")
    assert response.status_code == 200
    # TG3-G (t_54bad356): h1 is mode-neutral now; the compare mode is stated
    # by the mode chip rendered from run metadata.
    assert "Best upgrades" in response.text
    assert "results.js" in response.text


def test_results_subtitle_alternative_count_is_singular_correct():
    # RED-3F2 SEV-4 (t_bec1d725): exactly 1 ranked alternative must read
    # "1 alternative ranked", not "1 alternatives ranked".
    js = resp(read_js()).text
    assert "${ranked.length} alternative${ranked.length === 1 ? '' : 's'} ranked against" in js
    node = shutil.which("node")
    if not node:
        pytest.skip("node not on PATH")
    # Node harness (same pattern as test_crafted_badge_mapping_g4): evaluate
    # the served subtitle template itself for n=1 and n=2.
    start = js.index("`${ranked.length} alternative")
    template = js[start:js.index("`", start + 1) + 1]
    script = (
        "const mk = (n, isEquipped) => { const ranked = { length: n }; return "
        + template + "; };"
        "const cases = [[1, '1 alternative ranked against the top candidate.'], "
        "[2, '2 alternatives ranked against your equipped gear.']];"
        "let fail = 0;"
        "for (const [n, want] of cases) {"
        "  const got = mk(n, n !== 1);"
        "  if (got !== want) { console.error(n + ' -> ' + got + ' (want ' + want + ')'); fail = 1; }"
        "}"
        "process.exit(fail);"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_successful_simulation_exposes_uploaded_report_link():
    response = resp(read_js())
    assert response.status_code == 200
    js = response.text

    assert "message.report_file && message.task_id" in js
    # t_c968bf8d: durable reports live under /reports/<user_id>/<task_id>/, so
    # the frontend resolves the URL via /api/report-url instead of building it.
    assert "api/report-url?task_id=" in js
    assert "document.getElementById('btn-open-report')" in js  # MGE-2 A2 hero link (t_94a15fe3), RED-3 static anchor in results.html
    assert "link.hidden = false;" in js


# ---------------------------------------------------------------------------
# Realm dropdown (static realms.json wiring, task t_d4399bc8)
# ---------------------------------------------------------------------------

def test_realms_json_is_served_as_static_asset():
    response = client.get("/static/realms.json")
    assert response.status_code == 200
    data = response.json()

    assert set(data["realms"]) >= {"eu", "us"}
    for region in ("eu", "us"):
        realms = data["realms"][region]
        assert realms, f"{region} group must not be empty"
        for realm in realms:
            assert set(realm) == {"region", "id", "slug", "name", "type", "timezone", "population"}
            assert realm["region"] == region


def test_realm_dropdown_markup_starts_hidden_and_disabled():
    """Graceful-degradation baseline: before realms.json loads (or if it never
    arrives) the select must not be visible or focusable."""
    html = client.get("/").text
    assert 'id="armory-realm"' in html
    assert 'class="armory-realm-select"' in html
    select_tag = html.split('<select id="armory-realm"', 1)[1].split(">", 1)[0]
    assert "disabled" in select_tag and "hidden" in select_tag


def test_app_fetches_static_realms_json_and_groups_by_region():
    js = resp(read_js()).text

    assert "apiFetch('static/realms.json')" in js  # t_2ab8f3be: 401-banner wrapper
    # EU/US optgroups, region-qualified keys (Kel'thuzad exists in both).
    assert "createElement('optgroup')" in js
    assert "const labels = { eu: 'EU', us: 'US' }" in js
    assert "`${region}/${realm.slug}`" in js


def test_realm_dropdown_degrades_gracefully_when_realms_json_missing():
    js = resp(read_js()).text

    load_realms = js.split("async function loadRealms", 1)[1].split("function buildArmoryPayload", 1)[0]
    # Failure path: log-and-keep-hidden only — no user-facing error panel,
    # the manual Name-Realm typing flow keeps working untouched.
    assert "Realm list unavailable" in load_realms
    assert "showParseError" not in load_realms
    # Malformed payloads are rejected before touching the DOM.
    assert "unexpected realms.json shape" in js


def test_realm_dropdown_pick_feeds_armory_payload():
    js = resp(read_js()).text

    build_payload = js.split("function buildArmoryPayload", 1)[1].split("loadRealms();", 1)[0]
    # Pasted Armory links still win outright.
    assert "return { url: value }" in build_payload
    # A dropdown pick supplies realm + its region for a bare character name;
    # a realm typed into the input ("Name-Realm") wins over the pick.
    assert "payload.realm = picked.slug" in build_payload
    assert "payload.region = picked.region" in build_payload
    assert "!/[,-]/.test(value)" in build_payload


def test_static_browser_code_has_no_root_absolute_urls():
    """t_62ff8faa: every browser-side URL must be page-relative.

    Root-absolute paths (fetch('/api/...'), href="/static/...") break when
    the app is served under a path prefix behind a prefix-stripping proxy
    (Caddy handle_path /simc/*). Keep them relative to the page instead.
    """
    import pathlib
    import re

    static_dir = pathlib.Path(__file__).resolve().parent.parent / "src" / "web" / "static"
    pattern = re.compile(r"""['"`(]/(?:api|static|reports|login|register|dashboard|history|results|logout)\b""")
    offenders = [
        f"{path.name}: {match.group(0)!r}"
        for path in [*static_dir.glob("*.html"), *static_dir.glob("*.js")]
        for match in pattern.finditer(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_wowhead_tooltip_config_keeps_gear_icons():
    """t_268f5264 (UI-2): wh.js renameLinks replaces the gear-card <img>
    with a plain text item link (innerHTML = <span>name</span>). The binding
    design-doc ruling (gui-design-doc.md §Step2, t_8655bd7e) is
    iconizeLinks:false + renameLinks:false; the per-link data-wh-rename
    attribute is never read by the lib (it reads data-wh-rename-link)."""
    response = client.get("/static/app.html")
    assert response.status_code == 200
    html = response.text

    assert "iconizeLinks: false" in html
    assert "renameLinks: false" in html
    assert "renameLinks: true" not in html
    assert "iconizeLinks: true" not in html


def test_enhancement_state_chips_on_slot_headers():
    """TG2-A §3.4: step-2 slot headers echo step-3 enhancement state in
    jump-and-open chips (design t_0fbfd0bd §3.1): chip class + label strings,
    section-open target, and the step-3 hint."""
    js = resp(read_js()).text
    assert js, "app.js must be served"

    # RED-3 (contract §6): per-slot enh-chips deleted; the enhancements
    # <details> panel now owns enhancement state. Stable title stamps,
    # checked-count summary labels, and search-driven open/close are pinned.
    assert "section.dataset.enhTitle = title" in js
    assert "'Flawless gems'" in js
    assert "${checked} selected" in js
    assert "'.choice-chip'" in js
    assert "searchOpened.add(section)" in js
    assert "section.open = true" in js
    assert "section.open = false" in js


def test_css_comments_are_balanced():
    # RED-3 live-gate found a `--ic-*/` sequence in a header comment that closed
    # the comment early and swallowed the whole :root light-palette block.
    # Comments must pair up and the palette root must survive comment stripping.
    import re
    from pathlib import Path
    css_dir = Path(__file__).resolve().parents[1] / "src" / "web" / "static" / "css"
    for sheet in css_dir.glob("*.css"):
        text = sheet.read_text(encoding="utf-8")
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        assert "/*" not in stripped and "*/" not in stripped, f"unbalanced CSS comment in {sheet.name}"
    tokens = (css_dir / "tokens.css").read_text(encoding="utf-8")
    assert ":root{" in re.sub(r"/\*.*?\*/", "", tokens, flags=re.S)


def test_chip_render_degrades_on_malformed_tooltip():
    # RED-3 live-gate found one tooltip entry without a name crashing the whole
    # results page (render threw, silent retry loop, page rendered half-empty).
    # Malformed tooltip info must degrade to the pending chip instead.
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "src" / "web" / "static"
          / "js" / "results" / "chips.js").read_text(encoding="utf-8")
    assert js.count("if (!info || !info.name)") == 2
    assert "base && base.name" in js
