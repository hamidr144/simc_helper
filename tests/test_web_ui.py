import os
import sys

from fastapi.testclient import TestClient

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
from web.main import app

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
    assert "<h1>SimC Web Helper</h1>" in html_content
    assert 'id="addon-input"' in html_content
    assert 'id="btn-parse-addon"' in html_content
    assert "1. Setup &amp; Addon" in html_content or "1. Setup & Addon" in html_content


def test_web_ui_uses_dashboard_layout():
    response = client.get("/")
    assert response.status_code == 200
    html_content = response.text

    assert 'class="app-shell"' in html_content
    assert 'class="workflow-rail tabs"' in html_content
    assert 'class="workspace-grid setup-layout"' in html_content
    assert 'class="panel-card"' in html_content


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
    response = client.get("/static/style.css")
    assert response.status_code == 200
    css = response.text

    assert "grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.2fr)" in css
    assert "position: sticky" in css
    assert "@media (max-width: 900px)" in css
    assert "--accent: #5d5bf0" in css  # t_2ab8f3be: fill/text accent split


def test_web_ui_applies_linear_design_system_tokens():
    response = client.get("/static/style.css")
    assert response.status_code == 200
    css = response.text

    assert "--surface-panel: #1d1e20" in css
    assert "--surface-bg: #131415" in css
    assert "--radius-card: 12px" in css
    assert "--radius-control: 6px" in css
    assert "font-weight: 510" in css
    assert "background: var(--surface-panel)" in css
    assert "--border-hairline: rgba(255, 255, 255, 0.10)" in css


def test_gear_selection_uses_midnight_track_rank_upgrades():
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/style.css")
    assert js_response.status_code == 200
    assert css_response.status_code == 200
    js = js_response.text
    css = css_response.text

    assert "seasonTracks()" in js
    assert "gear-track-select" in js
    assert "gear-rank-select" in js
    assert "gear_upgrades: gearUpgrades" in js
    assert "item_levels: itemLevels" not in js
    assert "inferMidnightUpgrade" in js
    assert "itemLevelFromLabel" in js
    assert ".gear-track-select" in css
    assert ".gear-rank-select" in css
    assert ".item-level-input" not in css


def test_gear_selection_uses_compact_icon_tiles_instead_of_text_rows():
    html_response = client.get("/")
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/style.css")
    assert html_response.status_code == 200
    assert js_response.status_code == 200
    assert css_response.status_code == 200

    html = html_response.text
    js = js_response.text
    css = css_response.text

    assert "iconizeLinks: false" in html  # t_2ab8f3be: no DOM mutation of our links
    assert "createWowheadIconLink" in js
    assert "slot-items" in js
    assert "item-option" in js
    assert "item-icon-link" in js
    assert "item-option-name" in js
    assert ".item-icon-grid" in css
    assert ".item-option" in css
    assert ".item-icon-link" in css
    assert "grid-template-columns: repeat(auto-fill, minmax(92px, 1fr))" in css
    assert "sr-only" in css


def test_gear_selection_stacks_cards_vertically():
    """Feature 1 (t_e431c027): gear candidate cards stack one per row at all
    widths — .slot-items must be a single column, never an auto-fill grid."""
    import re

    css_response = client.get("/static/style.css")
    assert css_response.status_code == 200
    css = css_response.text

    def rule_body(selector):
        match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert match, f"missing rule for {selector}"
        return match.group(1)

    for selector in (".slot-items", ".gear-grid-columns"):
        body = rule_body(selector)
        assert "grid-template-columns: 1fr" in body, (
            f"{selector} must be a single-column stack, got: {body.strip()}"
        )
        assert "auto-fill" not in body and "auto-fit" not in body, (
            f"{selector} must not use an auto-fill/auto-fit grid"
        )


def test_zero_combination_run_is_labelled_baseline():
    """t_4485565b: a 0-candidate selection must be offered as a baseline
    current-gear run — never hidden behind a fake '1 combination' or a
    silently-disabled Run button."""
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "Ready to run a baseline current-gear report." in js
    # Run generates input even when the client-side estimate is 0.
    assert "if (!generatedInput) await generateInput();" in js
    # Run stays enabled once a character is loaded.
    assert "runButton.disabled = !(generatedInput || parsedData);" in js
    # The old early-return that froze generation at 0 combinations is gone.
    assert "if (!estimateCombinations()) return;" not in js


def test_gear_selection_allows_marking_voidforged_weapons_and_trinkets():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "voidforge-input" in js
    assert "isVoidforgeEligibleSlot" in js
    assert "voidforged_items: voidforgedItems" in js
    assert "seasonAscension().name" in js


def test_voidforged_control_toggles_itself_inside_item_tile():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "voidforgeInput.addEventListener('change'" in js
    assert "voidforgedItems[slot][item] = event.target.checked;" in js
    assert "classList.toggle('is-active', event.target.checked)" in js


def test_voidforged_items_are_detected_from_season_ascension_data():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "legacy_final_ilvls" in js
    assert "isAlreadyVoidforgedItem" in js
    assert "seasonAscension().name" in js


def test_named_voidforged_items_start_with_ascendant_flag_enabled():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "function isAlreadyVoidforgedItem(slot, item, label = '')" in js
    assert "String(label).toLowerCase().includes(ascendedName)" in js
    assert "voidforgedItems[slot][item] = isAlreadyVoidforgedItem" in js


def test_plain_item_level_labels_do_not_start_with_ascendant_flag_enabled():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "String(label).toLowerCase().includes(ascendedName)" in js
    assert "function finalItemLevelFromLabel(itemLabel)" not in js
    assert "const labelItemLevel = finalItemLevelFromLabel(itemLabel);" not in js


def test_voidforged_items_are_detected_from_bonus_ids_not_plain_item_levels():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "seasonAscension().bonus_ids" in js
    assert "bonuses.some(bonus => ids.includes(bonus))" in js
    assert "13622" not in js


def test_voidforged_track_rank_inference_uses_base_level_before_ascension():
    response = client.get("/static/app.js")
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
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "function isCraftedItem(item)" in js
    assert "crafting_quality=" in js
    assert "crafted_stats=" in js
    assert "if (isCraftedItem(item)) return null;" in js
    assert "Crafted · no grade" in js


def test_gear_selection_hydrates_exact_grades_from_wowhead():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "hydrateWowheadUpgrades(parsedData.items_by_slot);" in js
    assert "apiFetch('api/wowhead-upgrades'" in js  # t_2ab8f3be: 401-banner wrapper
    assert "(gearUpgrades[slot] ||= {})[item] = upgrade;" in js
    assert "renderGear();" in js


def test_user_chosen_upgrades_are_marked_user_selected():
    """t_ef33100b: user-chosen grades carry user_selected so the backend
    keeps them off the baseline; inferred-current entries stay unmarked."""
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    # Track/rank picks mark the entry; export rank 0 ("Current") clears it.
    assert "{ track, rank: 1, user_selected: true }" in js
    assert "entry.user_selected = true;" in js
    assert "if (entry.rank === 0) delete entry.user_selected;" in js
    # Wowhead hydration must not clobber a pick the user already made.
    assert "if (gearUpgrades[slot]?.[item]?.user_selected) continue;" in js
    # The estimator counts a user-chosen upgrade as a real variation.
    assert "Boolean(gearUpgrades[slot]?.[item]?.user_selected)" in js


def test_item_icons_use_local_proxy_without_requiring_wowhead_javascript():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert 'src="api/item-icon/${safeId}"' in js
    assert 'data-wowhead="${tooltipData}"' in js
    assert "domain=ptr" not in js


def test_item_icons_and_names_use_default_wowhead_tooltips():
    page_response = client.get("/")
    assert page_response.status_code == 200
    assert 'src="api/wowhead-tooltips.js?v=20260718-proxy"' in page_response.text
    assert "power.js" not in page_response.text

    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "wowhead-item-link" in js
    assert "data-wowhead" in js
    assert "window.WH.Tooltips.refreshLinks()" in js
    assert "bonus=${safeBonus}" in js


def test_gems_and_enchantments_use_default_wowhead_tooltips():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "function createEnhancementWowheadLink(enhancement, name)" in js
    assert "enhancement.wowhead_url" in js
    assert "enhancement-name-link wowhead-item-link" in js
    assert "createEnhancementWowheadLink(enchant, name)" in js
    assert "createEnhancementWowheadLink(gem, name)" in js
    assert js.count("refreshWowheadLinks();") >= 2


def test_heliotrope_gems_are_not_rendered_as_selectable_gems():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "gems?.standard" in js


def test_current_gear_is_ready_to_run_and_selected_enhancements_are_checked():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "let total = 1;" in js
    assert "equippedEnchants[slot].has(id)" in js
    assert "equippedGems.has(id)" in js
    assert "void generateInput(true);" in js
    assert "PVP_META_NAME_MATCH" in js


def test_report_gear_summary_shows_only_slot_and_item_link():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "const statsTd = statsRow.querySelector('td.small');" not in js
    assert "const stats = statsTd ? statsTd.textContent.trim() : '';" not in js
    assert "${stats}" not in js
    assert '<strong>${escapeHtml(item.slot)}:</strong> ${item.itemLink}' in js


def test_report_separates_baseline_and_only_lists_combo_differences():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "baseline-gear-panel" in js
    assert "Baseline Gear" in js
    assert "selectedItems" in js
    assert "estimateCombinations" in js
    assert "results?task_id=" in js  # t_2ab8f3be: success card link, no auto-redirect


def test_results_page_is_a_dedicated_user_friendly_view():
    response = client.get("/results?task_id=test")
    assert response.status_code == 200
    assert "Best combinations" in response.text
    assert "results.js" in response.text


def test_successful_simulation_exposes_uploaded_report_link():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "message.report_file && message.task_id" in js
    # t_c968bf8d: durable reports live under /reports/<user_id>/<task_id>/, so
    # the frontend resolves the URL via /api/report-url instead of building it.
    assert "api/report-url?task_id=" in js
    assert '>Open full report</a>' in js


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
    js = client.get("/static/app.js").text

    assert "apiFetch('static/realms.json')" in js  # t_2ab8f3be: 401-banner wrapper
    # EU/US optgroups, region-qualified keys (Kel'thuzad exists in both).
    assert "createElement('optgroup')" in js
    assert "const labels = { eu: 'EU', us: 'US' }" in js
    assert "`${region}/${realm.slug}`" in js


def test_realm_dropdown_degrades_gracefully_when_realms_json_missing():
    js = client.get("/static/app.js").text

    load_realms = js.split("async function loadRealms", 1)[1].split("function buildArmoryPayload", 1)[0]
    # Failure path: log-and-keep-hidden only — no user-facing error panel,
    # the manual Name-Realm typing flow keeps working untouched.
    assert "Realm list unavailable" in load_realms
    assert "showParseError" not in load_realms
    # Malformed payloads are rejected before touching the DOM.
    assert "unexpected realms.json shape" in js


def test_realm_dropdown_pick_feeds_armory_payload():
    js = client.get("/static/app.js").text

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
