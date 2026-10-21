"""t_a856571d: GET /api/config exposes WoW quality on enchant/gem records.

Purely additive: every enchant and gem record gains an integer ``quality``
derived through the EXISTING cached Wowhead XML path
(fetch_wowhead_upgrade -> parse_wowhead_quality -> wowhead_quality_cache),
None when unresolvable — response shape otherwise unchanged and combination
generation untouched. The fetch is bounded (one call per unique cache miss,
never re-issued once warm) and fail-soft (upstream error -> quality None,
200, no crash). Fetch boundary patched per-test, same convention as
fetch_wowhead_name_and_level in tests/conftest.py.
"""

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))
import web.main as master
from web.main import app

client = TestClient(app)

# Live config shape: the enchant record id is a SPELL id; its wowhead_url
# carries the real item id (7989 -> item=243979). Gems: id == item id.
ENCHANT = {"id": 7989, "name": "Enchant Helm - Blessing of Speed",
           "wowhead_url": "https://www.wowhead.com/item=243979"}
GEM = {"id": 240983, "name": "Indecipherable Eversong Diamond",
       "wowhead_url": "https://www.wowhead.com/item=240983",
       "stats": {"mastery": 81}}


def _serve_config(monkeypatch, tmp_path, config):
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def test_quality_attached_from_warm_cache_without_fetch(monkeypatch, tmp_path):
    _serve_config(monkeypatch, tmp_path,
                  {"enchantments": {"head": [ENCHANT]}, "gems": {"standard": [GEM]}})
    monkeypatch.setattr(master, "wowhead_quality_cache", {
        master.wowhead_xml_url("id=243979"): 2,
        master.wowhead_xml_url("id=240983"): 4,
    })
    fetch = AsyncMock()
    with patch("web.main.fetch_wowhead_upgrade", new=fetch):
        response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    enchant = body["enchantments"]["head"][0]
    gem = body["gems"]["standard"][0]
    assert enchant["quality"] == 2  # int from the wowhead_url item, not the spell id
    assert gem["quality"] == 4
    assert gem["stats"] == {"mastery": 81}  # rest of the shape unchanged
    assert fetch.await_count == 0  # warm cache -> zero fetches


def test_quality_warmed_once_per_unique_item_then_cached(monkeypatch, tmp_path):
    _serve_config(monkeypatch, tmp_path,
                  {"enchantments": {"head": [ENCHANT], "neck": [dict(ENCHANT)]},
                   "gems": {"standard": [GEM]}})
    monkeypatch.setattr(master, "wowhead_quality_cache", {})
    calls = []

    async def fake_fetch(item):  # mirrors the real fill: cache quality under the xml url
        calls.append(item)
        master.wowhead_quality_cache[master.wowhead_xml_url(item)] = 3

    with patch("web.main.fetch_wowhead_upgrade", new=fake_fetch):
        first = client.get("/api/config").json()
        assert first["enchantments"]["head"][0]["quality"] == 3
        assert first["enchantments"]["neck"][0]["quality"] == 3
        # bounded: the duplicate url fetched once; the gem resolved its own id
        assert calls == ["id=243979", "id=240983"]
        second = client.get("/api/config").json()
    assert second["enchantments"]["head"][0]["quality"] == 3
    assert calls == ["id=243979", "id=240983"]  # warm -> no re-fetch


def test_upstream_failure_is_none_not_crash(monkeypatch, tmp_path):
    legacy = {"name": "legacy entry without identifiers"}  # unresolvable source
    _serve_config(monkeypatch, tmp_path,
                  {"enchantments": {"head": [ENCHANT, legacy]}, "gems": {}})
    monkeypatch.setattr(master, "wowhead_quality_cache", {})

    async def failing_fetch(item):
        raise httpx.ConnectError("down", request=httpx.Request("GET", "https://www.wowhead.com"))

    with patch("web.main.fetch_wowhead_upgrade", new=failing_fetch):
        response = client.get("/api/config")
    assert response.status_code == 200
    head = response.json()["enchantments"]["head"]
    assert head[0]["quality"] is None  # fail-soft upstream error
    assert head[1]["quality"] is None  # no id/wowhead_url -> None, no fetch issued


def test_quality_none_when_xml_has_no_quality_node(monkeypatch, tmp_path):
    # Fetch succeeds but caches None (no <quality> in the XML): a resolved
    # miss is still a cached answer — never re-fetched, quality stays None.
    _serve_config(monkeypatch, tmp_path,
                  {"enchantments": {"head": [ENCHANT]}, "gems": {}})
    monkeypatch.setattr(master, "wowhead_quality_cache", {})
    calls = []

    async def no_quality(item):
        calls.append(item)
        master.wowhead_quality_cache[master.wowhead_xml_url(item)] = None

    with patch("web.main.fetch_wowhead_upgrade", new=no_quality):
        body = client.get("/api/config").json()
    assert body["enchantments"]["head"][0]["quality"] is None
    assert calls == ["id=243979"]
