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
    assert "--accent-color: #7170ff" in css


def test_web_ui_applies_linear_design_system_tokens():
    response = client.get("/static/style.css")
    assert response.status_code == 200
    css = response.text

    assert "--panel-bg: rgba(255, 255, 255, 0.02)" in css
    assert "--surface-bg: #191a1b" in css
    assert "--radius-card: 12px" in css
    assert "--radius-control: 6px" in css
    assert "font-weight: 510" in css
    assert "background: rgba(255, 255, 255, 0.02)" in css
    assert "--shadow-panel: inset 0 0 12px rgba(0, 0, 0, 0.20)" in css


def test_gear_selection_uses_midnight_track_rank_upgrades():
    js_response = client.get("/static/app.js")
    css_response = client.get("/static/style.css")
    assert js_response.status_code == 200
    assert css_response.status_code == 200
    js = js_response.text
    css = css_response.text

    assert "MIDNIGHT_UPGRADE_TRACKS" in js
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

    assert "iconizeLinks: true" in html
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


def test_gear_selection_allows_marking_voidforged_weapons_and_trinkets():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "voidforge-input" in js
    assert "isVoidforgeEligibleSlot" in js
    assert "voidforged_items: voidforgedItems" in js
    assert "Ascendant Voidforged +9" in js


def test_voidforged_control_toggles_itself_inside_item_tile():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "voidforgeInput.addEventListener('change'" in js
    assert "voidforgedItems[slot][item] = event.target.checked;" in js
    assert "classList.toggle('is-active', event.target.checked)" in js


def test_voidforged_items_are_detected_from_final_item_levels():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "const VOIDFORGE_FINAL_ITEM_LEVELS = [285, 298];" in js
    assert "isAlreadyVoidforgedItem" in js
    assert "Ascendant Voidforged +9" in js


def test_named_voidforged_items_start_with_ascendant_flag_enabled():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "function isAlreadyVoidforgedItem(slot, item, label = '')" in js
    assert "String(label).toLowerCase().includes('voidforged')" in js
    assert "voidforgedItems[slot][item] = isAlreadyVoidforgedItem" in js


def test_plain_item_level_labels_do_not_start_with_ascendant_flag_enabled():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "String(label).toLowerCase().includes('voidforged')" in js
    assert "function finalItemLevelFromLabel(itemLabel)" not in js
    assert "const labelItemLevel = finalItemLevelFromLabel(itemLabel);" not in js


def test_voidforged_items_are_detected_from_bonus_ids_not_plain_item_levels():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "const VOIDFORGE_BONUS_IDS = ['13653', '13654'];" in js
    assert "bonuses.some(bonus => VOIDFORGE_BONUS_IDS.includes(bonus))" in js
    assert "VOIDFORGE_BONUS_IDS.includes('13622')" not in js


def test_voidforged_track_rank_inference_uses_base_level_before_plus_nine():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert "function inferMidnightUpgrade(slot, item, label)" in js
    assert "hasVoidforgeBonus(item)" in js
    assert "level -= 9;" in js


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
    assert "fetch('/api/wowhead-upgrades'" in js
    assert "...itemUpgrades" in js
    assert "renderGear();" in js


def test_item_icons_use_local_proxy_without_requiring_wowhead_javascript():
    response = client.get("/static/app.js")
    assert response.status_code == 200
    js = response.text

    assert 'src="/api/item-icon/${safeId}"' in js
    assert 'data-wowhead="${tooltipData}"' in js
    assert "domain=ptr" not in js


def test_item_icons_and_names_use_default_wowhead_tooltips():
    page_response = client.get("/")
    assert page_response.status_code == 200
    assert 'src="/api/wowhead-tooltips.js?v=20260718-proxy"' in page_response.text
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
    assert "includes('heliotrope')" in js


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
