"""Tests for Step 4: add-an-item by Wowhead id, slot sorting, stat priorities.

Covers:
- ``src/core/data/stat_priorities.json`` shape + the loader/scoring helpers.
- ``GET /api/stat-priorities``.
- ``POST /api/wowhead/tooltips/batch`` (mocked at the fetch boundary, using
  the same real captured tooltip payload as the single-tooltip tests).
- Frontend wiring (source-text snapshots, supplementary to the endpoint tests).
"""

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
import web.main as main  # noqa: E402
from core.stat_priorities import (  # noqa: E402
    load_stat_priorities,
    score_stats,
    weights_for_class,
)
from web.main import app, wowhead_tooltip_json_cache  # noqa: E402

client = TestClient(app)

# Real captured payload (Stonehide Vambraces, ilvl 272) — same fixture as
# tests/test_wowhead_tooltip.py so both endpoints are pinned to one upstream shape.
REAL_BASE = json.loads(json.dumps({
    "name": "Stonehide Vambraces", "quality": 3,
    "icon": "inv_bracer_plate_outdooramaniloa_c_01",
    "tooltip": "<table><tr><td><!--nstart--><b class=\"q3\">Stonehide Vambraces</b><!--nend--><!--ndstart--><!--ndend--><span class=\"q\"><br>Item Level <!--ilvl-->272</span><br><span class=\"q\">Upgrade Level: Adventurer <!--uindex-->3/6</span><!--bo--><br>Binds when equipped<!--ue--><!--ue--><table width=\"100%\"><tr><td>Wrist</td><th><!--scstart4:4--><span class=\"q1\">Plate</span><!--scend--></th></tr></table><!--rf--><span><!--amr-->147 Armor</span><br><span><!--stat74-->+60 [Strength or Intellect]</span><br><span><!--stat7-->+1,061 Stamina</span><!--ebstats--><br><span class=\"q2\">+<!--rtg32-->37 Critical Strike</span><br><span class=\"q2\">+<!--rtg40-->48 Versatility</span><!--egstats--><!--eistats--><!--nameDescStats--><!--rs--><!--e--><!--ps--><br>Durability 50 / 50</td></tr></table><table><tr><td><!--rr--><!--itemEffects:0-->Requires Level <!--rlvl-->90<br><!--pvpEquip--><!--pvpEquip--><div class=\"whtt-sellprice\">Sell Price: <span class=\"moneygold\">21</span> <span class=\"moneysilver\">69</span> <span class=\"moneycopper\">65</span></div></td></tr></table>",
    "spells": [],
}))


@pytest.fixture(autouse=True)
def clear_tooltip_cache():
    wowhead_tooltip_json_cache.clear()
    yield
    wowhead_tooltip_json_cache.clear()


class FakeUpstream:
    def __init__(self, not_found_ids=()):
        self.urls = []
        self.not_found_ids = set(not_found_ids)

    async def __call__(self, upstream_url):
        self.urls.append(upstream_url)
        if any(f"/item/{item_id}" in upstream_url for item_id in self.not_found_ids):
            return {"error": "Entity not found"}
        return REAL_BASE


@pytest.fixture
def fake_upstream(monkeypatch):
    fake = FakeUpstream()
    monkeypatch.setattr(main, "fetch_wowhead_tooltip_json", fake)
    return fake


# ---------- data file + helpers ----------

def test_stat_priorities_data_file_shape():
    data = load_stat_priorities()
    assert data["heuristic"] is True  # the UI labels the sort from this flag
    assert data["default_weights"]["Strength"] > 0
    assert data["default_weights"]["Stamina"] < data["default_weights"]["Strength"]
    # Every WoW class present, weights numeric and positive.
    classes = data["classes"]
    assert set(classes) >= {
        "deathknight", "demonhunter", "druid", "evoker", "hunter", "mage",
        "monk", "paladin", "priest", "rogue", "shaman", "warlock", "warrior",
    }
    for entry in classes.values():
        assert entry.get("name")
        for label, weight in entry["weights"].items():
            assert isinstance(weight, (int, float)) and weight > 0, label


def test_weights_for_class_merges_defaults_and_falls_back():
    paladin = weights_for_class("Paladin")  # case-insensitive
    assert paladin["mastery"] == 0.75       # class override
    assert paladin["stamina"] == 0.15       # from defaults
    unknown = weights_for_class("notaclass")
    assert unknown == weights_for_class(None)
    assert unknown["mastery"] == 0.6        # default weight, no class merge


def test_score_stats_weighted_sum_and_or_fallback():
    weights = {"strength": 1.0, "intellect": 0.5, "stamina": 0.15, "mystery": 9}
    stats = [
        {"label": "Strength", "value": 100},
        {"label": "Stamina", "value": 1000},
        {"label": "Strength or Intellect", "value": 60},  # max(1.0, 0.5)
        {"label": "Unknown Stat", "value": 500},          # ignored
    ]
    # 100*1.0 + 1000*0.15 + 60*1.0 = 310
    assert score_stats(stats, weights) == 310.0
    assert score_stats([], weights) == 0.0
    assert score_stats(None, weights) == 0.0


# ---------- GET /api/stat-priorities ----------

def test_stat_priorities_endpoint():
    response = client.get("/api/stat-priorities")
    assert response.status_code == 200
    body = response.json()
    assert body["heuristic"] is True
    assert "paladin" in body["classes"]


# ---------- POST /api/wowhead/tooltips/batch ----------

def test_batch_resolves_and_scores_items(fake_upstream):
    response = client.post("/api/wowhead/tooltips/batch", json={
        "char_class": "paladin",
        "items": [
            {"item": 276000, "bonus": "3170/3171"},
            {"item": 276001},
        ],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["heuristic"] is True
    results = body["results"]
    assert [r["index"] for r in results] == [0, 1]
    assert all(r["ok"] for r in results)
    first = results[0]
    assert first["name"] == "Stonehide Vambraces"
    assert first["ilvl"] == 272
    assert first["quality_color"] == "#40c0ff"
    # Paladin weights: Armor 147*0.02 + Str-or-Int 60*1.0 + Stamina 1061*0.15
    #                  + Crit 37*0.6 + Versatility 48*0.45 = 265.89 -> 265.9
    assert first["score"] == pytest.approx(265.9, abs=0.1)
    # Bonus ids normalised into the upstream URL; plain item has no bonus param.
    assert "bonus=3170%3A3171" in fake_upstream.urls[0]
    assert "bonus" not in fake_upstream.urls[1].split("?", 1)[1]


def test_batch_per_item_failure_keeps_batch_200(monkeypatch):
    fake = FakeUpstream(not_found_ids=(9999999,))
    monkeypatch.setattr(main, "fetch_wowhead_tooltip_json", fake)
    response = client.post("/api/wowhead/tooltips/batch", json={
        "char_class": "mage",
        "items": [{"item": 276000}, {"item": 9999999}],
    })
    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert results[1]["error"] == "Entity not found"


def test_batch_rejects_too_many_items(fake_upstream):
    response = client.post("/api/wowhead/tooltips/batch", json={
        "items": [{"item": 1000 + i} for i in range(main.WOWHEAD_TOOLTIP_BATCH_MAX_ITEMS + 1)],
    })
    assert response.status_code == 400
    assert fake_upstream.urls == []


def test_batch_rejects_bad_bonus_with_400(fake_upstream):
    response = client.post("/api/wowhead/tooltips/batch", json={
        "items": [{"item": 276000, "bonus": "9929; DROP"}],
    })
    assert response.status_code == 400
    assert fake_upstream.urls == []


def test_batch_rejects_non_numeric_item(fake_upstream):
    response = client.post("/api/wowhead/tooltips/batch", json={
        "items": [{"item": "abc"}],
    })
    assert response.status_code == 422


def test_batch_empty_items_is_fine(fake_upstream):
    response = client.post("/api/wowhead/tooltips/batch", json={"items": []})
    assert response.status_code == 200
    assert response.json()["results"] == []


# ---------- frontend wiring (source-text snapshots) ----------

def _static(name):
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'web', 'static', name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_app_js_wires_sorting():
    js = _static("app.js")
    assert "function sortItemsForSlot(slot, items)" in js
    assert "for (const item of sortItemsForSlot(slot, items))" in js
    assert "slotSorts[slot] = sortSelect.value;" in js
    assert "async function ensureStatScores(slot, items, selectEl)" in js
    assert "api/wowhead/tooltips/batch" in js
    # Sort state resets with a fresh export (initializeSelections clears all three).
    init = js.split("function initializeSelections()")[1]
    for reset in ("slotSorts = {}", "statScores = {}", "addedItems = new Map()"):
        assert reset in init.split("\n\n")[0], reset


def test_app_js_wires_add_item():
    js = _static("app.js")
    assert "function wireSlotAddForm(group, slot)" in js
    assert "wireSlotAddForm(group, slot);" in js
    assert "function commitAddedItem(slot, itemId, preview)" in js
    assert "function removeAddedItem(slot, item)" in js
    assert "api/wowhead/tooltip?item=" in js
    # Added items land in the same state generation reads from.
    assert "parsedData.items_by_slot[slot]" in js
    assert "selectedItems[slot].add(key)" in js
    assert "added-badge" in js


def test_style_css_defines_step4_classes():
    css = _static("style.css")
    for selector in (".slot-sort-select", ".slot-add-form", ".slot-add-input",
                     "button.slot-add-button", ".slot-add-preview", ".slot-add-preview.is-error",
                     ".added-badge", "button.slot-remove-added"):
        assert selector in css


def test_app_html_cache_busted_step4():
    html = _static("app.html")
    assert "style.css?v=20261016-gui-redesign-1" in html
    assert "app.js?v=20261016-gui-redesign-1" in html
