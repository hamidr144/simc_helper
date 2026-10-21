from static_assets import read_css, read_js, resp  # t_94a15fe3 split pins
"""Tests for GET /api/wowhead/tooltip - server-side Wowhead tooltip preview proxy.

The tooltip fixtures are REAL payloads captured from
``https://nether.wowhead.com/tooltip/item/276000`` (Stonehide Vambraces,
Midnight S2) with and without ``ilvl=289``, so the parser is pinned against
the upstream's actual shape.
"""

import asyncio
import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
import web.main as main  # noqa: E402
from web.main import (  # noqa: E402
    app,
    parse_wowhead_tooltip,
    wowhead_tooltip_delta,
    wowhead_tooltip_json_cache,
)

client = TestClient(app)

REAL_BASE = {"name": "Stonehide Vambraces", "quality": 3, "icon": "inv_bracer_plate_outdooramaniloa_c_01", "tooltip": "<table><tr><td><!--nstart--><b class=\"q3\">Stonehide Vambraces</b><!--nend--><!--ndstart--><!--ndend--><span class=\"q\"><br>Item Level <!--ilvl-->272</span><br><span class=\"q\">Upgrade Level: Adventurer <!--uindex-->3/6</span><!--bo--><br>Binds when equipped<!--ue--><!--ue--><table width=\"100%\"><tr><td>Wrist</td><th><!--scstart4:4--><span class=\"q1\">Plate</span><!--scend--></th></tr></table><!--rf--><span><!--amr-->147 Armor</span><br><span><!--stat74-->+60 [Strength or Intellect]</span><br><span><!--stat7-->+1,061 Stamina</span><!--ebstats--><br><span class=\"q2\">+<!--rtg32-->37 Critical Strike</span><br><span class=\"q2\">+<!--rtg40-->48 Versatility</span><!--egstats--><!--eistats--><!--nameDescStats--><!--rs--><!--e--><!--ps--><br>Durability 50 / 50</td></tr></table><table><tr><td><!--rr--><!--itemEffects:0-->Requires Level <!--rlvl-->90<br><!--pvpEquip--><!--pvpEquip--><div class=\"whtt-sellprice\">Sell Price: <span class=\"moneygold\">21</span> <span class=\"moneysilver\">69</span> <span class=\"moneycopper\">65</span></div></td></tr></table>", "spells": []}
REAL_289 = {"name": "Stonehide Vambraces", "quality": 3, "icon": "inv_bracer_plate_outdooramaniloa_c_01", "tooltip": "<table><tr><td><!--nstart--><b class=\"q3\">Stonehide Vambraces</b><!--nend--><!--ndstart--><!--ndend--><span class=\"q\"><br>Item Level <!--ilvl-->289</span><br><span class=\"q\">Upgrade Level: Adventurer <!--uindex-->3/6</span><!--bo--><br>Binds when equipped<!--ue--><!--ue--><table width=\"100%\"><tr><td>Wrist</td><th><!--scstart4:4--><span class=\"q1\">Plate</span><!--scend--></th></tr></table><!--rf--><span><!--amr-->163 Armor</span><br><span><!--stat74-->+70 [Strength or Intellect]</span><br><span><!--stat7-->+1,309 Stamina</span><!--ebstats--><br><span class=\"q2\">+<!--rtg32-->40 Critical Strike</span><br><span class=\"q2\">+<!--rtg40-->52 Versatility</span><!--egstats--><!--eistats--><!--nameDescStats--><!--rs--><!--e--><!--ps--><br>Durability 50 / 50</td></tr></table><table><tr><td><!--rr--><!--itemEffects:0-->Requires Level <!--rlvl-->90<br><!--pvpEquip--><!--pvpEquip--><div class=\"whtt-sellprice\">Sell Price: <span class=\"moneygold\">21</span> <span class=\"moneysilver\">88</span> <span class=\"moneycopper\">16</span></div></td></tr></table>", "spells": []}


@pytest.fixture(autouse=True)
def clear_tooltip_cache():
    wowhead_tooltip_json_cache.clear()
    yield
    wowhead_tooltip_json_cache.clear()


class FakeUpstream:
    """Serve the real payloads by URL, recording every upstream request."""

    def __init__(self, fail=False, not_found=False):
        self.urls = []
        self.fail = fail
        self.not_found = not_found

    async def __call__(self, upstream_url):
        self.urls.append(upstream_url)
        if self.fail:
            raise httpx.ConnectError("upstream down")
        if self.not_found:
            return {"error": "Entity not found"}
        if "ilvl=" in upstream_url:
            return REAL_289
        return REAL_BASE


@pytest.fixture
def fake_upstream(monkeypatch):
    fake = FakeUpstream()
    monkeypatch.setattr(main, "fetch_wowhead_tooltip_json", fake)
    return fake


# ---------- parser (real upstream payloads) ----------

def test_parse_real_tooltip():
    preview = parse_wowhead_tooltip(REAL_BASE)
    assert preview["name"] == "Stonehide Vambraces"
    assert preview["quality"] == 3
    assert preview["quality_color"] == "#40c0ff"
    assert preview["ilvl"] == 272
    assert preview["upgrade_level"] == "Adventurer 3/6"
    stats = {stat["label"]: stat["value"] for stat in preview["stats"]}
    assert stats["Armor"] == 147
    assert stats["Stamina"] == 1061
    assert stats["Critical Strike"] == 37
    assert stats["Versatility"] == 48
    assert stats["Strength or Intellect"] == 60
    # Non-stat lines never leak into stats.
    assert not [s for s in preview["stats"] if "Durability" in s["label"] or "Level" in s["label"]]
    assert "Armor" in preview["top_stats"]


def test_parse_rejects_payload_without_tooltip():
    assert parse_wowhead_tooltip({"name": "x"}) is None


def test_delta_between_real_states():
    delta = wowhead_tooltip_delta(
        parse_wowhead_tooltip(REAL_BASE), parse_wowhead_tooltip(REAL_289)
    )
    assert delta["ilvl"] == 17
    by_label = {stat["label"]: stat for stat in delta["stats"]}
    assert by_label["Armor"]["delta"] == 16
    assert by_label["Stamina"]["delta"] == 248
    assert by_label["Armor"]["before"] == 147
    assert by_label["Armor"]["after"] == 163


def test_delta_none_without_current():
    assert wowhead_tooltip_delta(None, parse_wowhead_tooltip(REAL_BASE)) is None


# ---------- endpoint (mocked upstream) ----------

def test_endpoint_returns_parsed_preview_with_delta(fake_upstream):
    response = client.get("/api/wowhead/tooltip", params={"item": 276000, "ilvl": 289})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["preview"]["ilvl"] == 289
    assert body["preview"]["quality_color"] == "#40c0ff"
    assert body["current"]["ilvl"] == 272
    assert body["delta"]["ilvl"] == 17
    assert {stat["label"] for stat in body["delta"]["stats"]} >= {"Armor", "Stamina"}
    # Two upstream fetches: preview (with ilvl) and current (without).
    assert len(fake_upstream.urls) == 2
    assert any("ilvl=289" in url for url in fake_upstream.urls)
    assert sum(1 for url in fake_upstream.urls if "ilvl=289" in url) == 1


def test_endpoint_without_override_skips_current(fake_upstream):
    response = client.get("/api/wowhead/tooltip", params={"item": 276000})
    assert response.status_code == 200
    body = response.json()
    assert body["preview"]["ilvl"] == 272
    assert body["current"] is None
    assert body["delta"] is None
    assert len(fake_upstream.urls) == 1


def test_endpoint_one_fetch_per_distinct_state(fake_upstream):
    for _ in range(3):
        assert client.get("/api/wowhead/tooltip", params={"item": 276000, "ilvl": 289}).status_code == 200
    # The endpoint fetches exactly once per distinct upstream URL; the TTL cache
    # lives inside fetch_wowhead_tooltip_json (covered by the fetch tests below).
    assert len(fake_upstream.urls) == 6


def test_fetch_ttl_cache_hits(monkeypatch):
    calls = []

    class FakeResponse:
        content = b"{}"

        def raise_for_status(self):
            return None

        def json(self):
            return {"name": "x", "tooltip": ""}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url):
            calls.append(url)
            return FakeResponse()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)

    async def run():
        url = "https://nether.wowhead.com/tooltip/item/42?dataEnv=1&locale=en"
        first = await main.fetch_wowhead_tooltip_json(url)
        second = await main.fetch_wowhead_tooltip_json(url)
        assert first is second
        assert calls == [url]  # second call served from TTL cache

    asyncio.run(run())


def test_endpoint_ptr_variant(fake_upstream):
    response = client.get("/api/wowhead/tooltip", params={"item": 276000, "env": "ptr"})
    assert response.status_code == 200
    assert "/ptr/tooltip/item/276000" in fake_upstream.urls[0]
    assert "dataEnv=2" in fake_upstream.urls[0]


def test_endpoint_passes_all_override_params(fake_upstream):
    response = client.get("/api/wowhead/tooltip", params={
        "item": 276000, "bonus": "9929/9930", "upgd": 3, "gems": "1,2",
        "ench": "7", "ilvl": 289, "lvl": 90,
    })
    assert response.status_code == 200
    url = fake_upstream.urls[0]
    assert "bonus=9929%3A9930" in url
    assert "gems=1%3A2" in url
    assert "ench=7" in url
    assert "upgd=3" in url
    assert "ilvl=289" in url
    assert "lvl=90" in url


def test_endpoint_rejects_non_numeric_bonus(fake_upstream):
    response = client.get("/api/wowhead/tooltip", params={"item": 1, "bonus": "9929; DROP"})
    assert response.status_code == 400
    assert fake_upstream.urls == []


def test_endpoint_rejects_bad_env(fake_upstream):
    response = client.get("/api/wowhead/tooltip", params={"item": 1, "env": "beta"})
    assert response.status_code == 422


def test_endpoint_upstream_failure_is_502(monkeypatch):
    monkeypatch.setattr(main, "fetch_wowhead_tooltip_json", FakeUpstream(fail=True))
    response = client.get("/api/wowhead/tooltip", params={"item": 276000})
    assert response.status_code == 502
    assert response.json()["detail"] == "Wowhead tooltip unavailable"


def test_endpoint_entity_not_found_is_404(monkeypatch):
    monkeypatch.setattr(main, "fetch_wowhead_tooltip_json", FakeUpstream(not_found=True))
    response = client.get("/api/wowhead/tooltip", params={"item": 9999999})
    assert response.status_code == 404


def test_endpoint_upstream_http_404_is_404(monkeypatch):
    async def raise_404(url):
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("not found", request=request, response=httpx.Response(404, request=request))

    monkeypatch.setattr(main, "fetch_wowhead_tooltip_json", raise_404)
    response = client.get("/api/wowhead/tooltip", params={"item": 9999999})
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found on Wowhead"


# ---------- fetch helper guards (no network: only failure paths) ----------

@pytest.mark.asyncio
async def test_fetch_rejects_oversized_payload(monkeypatch):
    class TooBig:
        content = b"x" * (main.WOWHEAD_TOOLTIP_MAX_BYTES + 1)

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url):
            return TooBig()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    with pytest.raises(ValueError):
        await main.fetch_wowhead_tooltip_json("https://nether.wowhead.com/tooltip/item/1")


# ---------- frontend wiring ----------

def _static(name):
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'web', 'static', name)
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_app_js_wires_debounced_preview():
    # D-9 light (RED-3): in-card .upgrade-preview DOM is gone; the same Wowhead
    # tooltip delta renders as the candidate row's native title on hover/focus.
    js = read_js()
    assert "api/wowhead/tooltip" in js
    assert "UPGRADE_PREVIEW_DEBOUNCE_MS = 400" in js
    assert "scheduleUpgradePreview" in js
    assert "row.title = text" in js  # the delta lands on the native row title
    assert js.count("scheduleUpgradePreview(slot, row.dataset.item, row);") == 1  # section hover delegation
    assert "querySelectorAll('.upgrade-preview')" not in js  # no in-card preview host left


def test_style_css_defines_preview_classes():
    # D-9 light: the preview surface classes are deleted from the design;
    # candidate rows carry the delta natively. Add-by-ID keeps its inline panel.
    css = read_css()
    for removed in (".upgrade-preview", ".upgrade-preview-delta",
                    ".upgrade-preview-stat", ".upgrade-preview-stats"):
        assert removed not in css
    for selector in (".slot-add-preview", ".slot-add-meta", ".vrow"):
        assert selector in css


def test_app_html_cache_busted():
    html = _static("app.html")
    assert "tokens.css?v=red3-2" in html  # MGE-2 split assets (t_94a15fe3)
    assert "pages/setup.js?v=red3-2" in html  # MGE-2 split assets (t_94a15fe3)
