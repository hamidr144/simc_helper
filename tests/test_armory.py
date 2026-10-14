"""Tests for the Armory integration (Step 7): src/core/armory.py + POST /api/armory-load.

All upstream data comes from the REAL fixtures in ``tests/fixtures/armory/``
(captured 2026-10-13 from the worldsoul Armory model.json endpoint).  The
test suite NEVER touches the live Blizzard network.
"""

import asyncio
import json
import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.core import armory  # noqa: E402
from src.core.armory import (  # noqa: E402
    ArmoryInputError,
    ArmoryNotFoundError,
    ArmoryRateLimitedError,
    ArmoryUnavailableError,
    armory_item_string,
    build_model_url,
    fetch_armory_model,
    parse_armory_input,
    parse_armory_model,
    parse_armory_url,
    parse_name_realm,
    resolve_realm_slug,
    slugify_realm,
)
from src.web.main import app  # noqa: E402

client = TestClient(app)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "armory")


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as handle:
        return handle.read()


def load_model(name):
    return json.loads(load_fixture(name))


@pytest.fixture(autouse=True)
def clear_armory_cache():
    armory.armory_model_cache.clear()
    yield
    armory.armory_model_cache.clear()


HAMIDRIEL = load_model("armory_model_hamidriel_eu.json")
ONRYO = load_model("armory_model_onryo_us.json")


# ---------------------------------------------------------------------------
# Realm slug rules (guide §3.1/§6, verified live)
# ---------------------------------------------------------------------------

class TestSlugifyRealm:
    @pytest.mark.parametrize("raw,slug", [
        ("Draenor", "draenor"),
        ("Area 52", "area-52"),
        ("area-52", "area-52"),
        ("Kel'Thuzad", "kelthuzad"),          # straight apostrophe REMOVED
        ("Kel\u2019Thuzad", "kelthuzad"),     # curly apostrophe REMOVED
        ("  The Hellfire  ", "the-hellfire"),
        ("Boulder'madgar", "bouldermadgar"),
        ("Spinebreaker!", "spinebreaker"),
        ("Area--52", "area-52"),              # runs collapse to one dash
        ("", ""),
    ])
    def test_slug_rules(self, raw, slug):
        assert slugify_realm(raw) == slug


# ---------------------------------------------------------------------------
# Non-ASCII known-slug preservation (card t_2f9b5e70, decision t_b9e549d1:
# realms.json slugs are source-authoritative).  The 7 EU slugs below are the
# ones NOT idempotent under slugify_realm; picking them in the dropdown must
# not mangle them into a 404-ing slug.
# ---------------------------------------------------------------------------

NON_ASCII_SLUGS = [
    "aggra-português",
    "chants-éternels",
    "confrérie-du-thorium",
    "festung-der-stürme",
    "la-croisade-écarlate",
    "marécage-de-zangar",
    "pozzo-delleternità",
]

REALMS_JSON = os.path.join(
    os.path.dirname(__file__), "..", "src", "web", "static", "realms.json"
)


class TestKnownSlugPassthrough:
    @pytest.mark.parametrize("slug", NON_ASCII_SLUGS)
    def test_dropdown_pick_survives_parse_armory_input(self, slug):
        """The exact path the frontend dropdown exercises (name/realm/region
        fields -> _finish): the slug must come back verbatim."""
        assert parse_armory_input(name="Testchar", realm=slug, region="eu") == (
            "eu",
            slug,
            "Testchar",
        )

    @pytest.mark.parametrize("slug", NON_ASCII_SLUGS)
    def test_resolve_realm_slug_identity_on_card_slugs(self, slug):
        assert resolve_realm_slug(slug) == slug

    def test_resolve_realm_slug_identity_on_every_realms_json_slug(self):
        with open(REALMS_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
        total = 0
        for records in data["realms"].values():
            for rec in records:
                assert resolve_realm_slug(rec["slug"]) == rec["slug"]
                total += 1
        assert total == data["counts"]["eu"] + data["counts"]["us"]

    def test_case_insensitive_match_returns_lowercase_slug(self):
        assert resolve_realm_slug("Pozzo-Delleternità") == "pozzo-delleternità"

    def test_percent_encoded_slug_in_url_survives(self):
        assert parse_armory_url(
            "https://eu.battle.net/wow/en/character/pozzo-delleternit%C3%A0/Testchar"
        ) == ("eu", "pozzo-delleternità", "Testchar")

    def test_model_url_percent_encodes_slug_on_the_wire(self):
        request = httpx.Request("GET", build_model_url("eu", "pozzo-delleternità", "Testchar"))
        assert b"/pozzo-delleternit%C3%A0/" in request.url.raw_path

    def test_fetch_armory_model_keeps_non_ascii_slug(self, monkeypatch):
        fake_get, calls = fake_get_factory([FakeResponse(200, json.dumps(HAMIDRIEL))])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        asyncio.run(fetch_armory_model("eu", "pozzo-delleternità", "Testchar"))
        assert "/pozzo-delleternità/" in calls[0]

    def test_api_armory_load_preserves_non_ascii_realm(self, monkeypatch):
        """Dropdown payload shape {name, region, realm} end-to-end through
        POST /api/armory-load."""
        seen = {}
        async def fake_fetch(region, realm, name):
            seen.update(region=region, realm=realm, name=name)
            return HAMIDRIEL
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={
            "name": "Testchar", "region": "eu", "realm": "pozzo-delleternità",
        })
        assert response.status_code == 200
        assert seen == {"region": "eu", "realm": "pozzo-delleternità", "name": "Testchar"}

    # -- fallback: unknown text keeps the exact old slugify_realm behaviour --

    def test_free_text_falls_back_to_slugify(self):
        assert resolve_realm_slug("Pozzo dell'Eternità") == slugify_realm("Pozzo dell'Eternità")
        assert resolve_realm_slug("Area 52") == "area-52"
        assert resolve_realm_slug("Kel'Thuzad") == "kelthuzad"
        assert resolve_realm_slug("Festung der Stürme") == "festung-der-st-rme"

    def test_missing_realms_json_degrades_to_slugify(self, monkeypatch):
        monkeypatch.setattr(
            armory, "_REALMS_JSON_PATH",
            os.path.join(os.path.dirname(__file__), "no-such-realms.json"),
        )
        monkeypatch.setattr(armory, "_known_realm_slugs_cache", None)
        assert resolve_realm_slug("pozzo-delleternità") == "pozzo-delleternit"


# ---------------------------------------------------------------------------
# URL parsing (worldsoul + legacy battle.net forms)
# ---------------------------------------------------------------------------

class TestUrlParsing:
    def test_worldsoul_url(self):
        assert parse_armory_url(
            "https://worldofwarcraft.blizzard.com/en-gb/worldsoul/eu/armory/"
            "character/draenor/Hamidriel"
        ) == ("eu", "draenor", "Hamidriel")

    def test_worldsoul_url_with_model_json_and_query(self):
        assert parse_armory_url(
            "https://worldofwarcraft.blizzard.com/en-us/worldsoul/us/armory/"
            "character/illidan/Onry%C3%B4/model.json?foo=bar"
        ) == ("us", "illidan", "Onryô")

    def test_worldsoul_url_realm_with_dash_and_apostrophe(self):
        assert parse_armory_url(
            "https://worldofwarcraft.blizzard.com/de-de/worldsoul/eu/armory/"
            "character/area-52/Kel'Thuzad"
        ) == ("eu", "area-52", "Kel'Thuzad")

    def test_legacy_battle_net_url(self):
        assert parse_armory_url(
            "https://eu.battle.net/wow/en/character/draenor/Hamidriel/advanced"
        ) == ("eu", "draenor", "Hamidriel")

    def test_legacy_battle_net_url_without_locale(self):
        assert parse_armory_url(
            "http://us.battle.net/wow/character/area-52/Some Name"
        ) == ("us", "area-52", "Some Name")

    def test_bare_url_without_scheme(self):
        assert parse_armory_url(
            "worldofwarcraft.blizzard.com/ko-kr/worldsoul/kr/armory/"
            "character/realm/Name"
        ) == ("kr", "realm", "Name")

    def test_garbage_url_rejected(self):
        with pytest.raises(ArmoryInputError):
            parse_armory_url("https://example.com/not/armory")


class TestParseNameRealm:
    def test_dash_form(self):
        assert parse_name_realm("Hamidriel-Draenor") == ("Hamidriel", "Draenor")

    def test_comma_form(self):
        assert parse_name_realm("Hamidriel, Draenor") == ("Hamidriel", "Draenor")

    def test_first_dash_wins_realm_keeps_dashes(self):
        # WoW names never contain dashes; realm slugs can (area-52).
        assert parse_name_realm("Name-Area-52") == ("Name", "Area-52")

    def test_unicode(self):
        assert parse_name_realm("Onryô-Illidan") == ("Onryô", "Illidan")
        assert parse_name_realm("Onryô, Illidan") == ("Onryô", "Illidan")

    def test_missing_realm_rejected(self):
        with pytest.raises(ArmoryInputError):
            parse_name_realm("Hamidriel")
        with pytest.raises(ArmoryInputError):
            parse_name_realm("Hamidriel-")
        with pytest.raises(ArmoryInputError):
            parse_name_realm("")


class TestParseArmoryInput:
    def test_url_wins_including_region(self):
        assert parse_armory_input(
            url="https://worldofwarcraft.blizzard.com/en-us/worldsoul/us/armory/"
                "character/illidan/onry%C3%B4",
            region="eu",
        ) == ("us", "illidan", "onryô")

    def test_name_realm_pair_defaults_region_eu(self):
        assert parse_armory_input(name="Hamidriel", realm="Draenor") == ("eu", "draenor", "Hamidriel")

    def test_combined_name_realm_in_name_field(self):
        assert parse_armory_input(name="Hamidriel-Draenor") == ("eu", "draenor", "Hamidriel")
        assert parse_armory_input(name="Onryô, Illidan", region="us") == ("us", "illidan", "Onryô")

    def test_realm_slugified(self):
        assert parse_armory_input(name="X", realm="Kel'Thuzad") == ("eu", "kelthuzad", "X")

    def test_bad_region_rejected(self):
        with pytest.raises(ArmoryInputError):
            parse_armory_input(name="X", realm="Y", region="na")

    def test_missing_input_rejected(self):
        with pytest.raises(ArmoryInputError):
            parse_armory_input()

    def test_non_url_name_falls_through(self):
        # The UI sends whatever the user typed as `url` only for http(s);
        # but even a mislabelled plain name must be handled, not 500.
        assert parse_armory_input(url="Hamidriel-Draenor") == ("eu", "draenor", "Hamidriel")


class TestBuildModelUrl:
    def test_ascii(self):
        assert build_model_url("eu", "draenor", "Hamidriel") == (
            "https://worldofwarcraft.blizzard.com/en-gb/worldsoul/eu/armory/"
            "character/draenor/Hamidriel/model.json"
        )

    def test_unicode_percent_encoded(self):
        assert build_model_url("us", "illidan", "Onryô") == (
            "https://worldofwarcraft.blizzard.com/en-gb/worldsoul/us/armory/"
            "character/illidan/Onry%C3%B4/model.json"
        )


# ---------------------------------------------------------------------------
# Gear parsing against the real fixtures
# ---------------------------------------------------------------------------

class TestGearParsingHamidriel:
    def setup_method(self):
        self.parsed = parse_armory_model(HAMIDRIEL)

    def test_char_identity(self):
        assert self.parsed["char_name"] == "Hamidriel"
        assert self.parsed["char_class"] == "paladin"
        assert self.parsed["char_spec"] == "retribution"
        assert self.parsed["char_ilvl"] == 329

    def test_base_profile(self):
        base = self.parsed["base_profile"]
        assert 'paladin="Hamidriel"' in base
        assert "level=90" in base
        assert "race=blood_elf" in base
        assert "spec=retribution" in base

    def test_all_15_slots_mapped(self):
        assert len(self.parsed["equipped_gear"]) == 15
        assert set(self.parsed["equipped_gear"]) == {
            "head", "neck", "shoulder", "back", "chest", "wrist", "hands",
            "waist", "legs", "feet", "finger1", "finger2", "trinket1",
            "trinket2", "main_hand",
        }

    def test_slot_mapping_spot_checks(self):
        gear = self.parsed["equipped_gear"]
        assert gear["main_hand"].startswith("id=268213")     # weapon
        assert gear["feet"].startswith("id=237828")          # foot
        assert gear["finger1"].startswith("id=268249")       # leftFinger
        assert gear["finger2"].startswith("id=251513")       # rightFinger
        assert gear["trinket1"].startswith("id=273796")      # leftTrinket
        assert gear["trinket2"].startswith("id=270173")      # rightTrinket
        assert gear["hands"].startswith("id=271466")         # hand
        assert gear["legs"].startswith("id=271464")          # leg

    def test_full_item_string_with_bonus_enchant_ilevel(self):
        # chest: Bulwark of the Consecrated Flame, fixture-pinned values
        assert self.parsed["equipped_gear"]["chest"] == (
            "id=271468,bonus_id=13334/6652/13690/13698/12854,"
            "enchant_id=7987,ilevel=334"
        )

    def test_no_enchant_omits_enchant_id(self):
        assert "enchant_id" not in self.parsed["equipped_gear"]["back"]
        assert self.parsed["equipped_gear"]["back"].startswith("id=271460,bonus_id=")

    def test_items_by_slot_normalizes_finger_trinket(self):
        by_slot = self.parsed["items_by_slot"]
        assert "finger" in by_slot and "finger1" not in by_slot
        assert "trinket" in by_slot and "trinket1" not in by_slot
        assert sorted(by_slot["finger"]) == sorted(
            [self.parsed["equipped_gear"]["finger1"], self.parsed["equipped_gear"]["finger2"]]
        )

    def test_item_names_have_ilvl_suffix(self):
        names = self.parsed["item_names"]
        chest = self.parsed["equipped_gear"]["chest"]
        assert names[chest] == "Bulwark of the Consecrated Flame (334)"
        feet = self.parsed["equipped_gear"]["feet"]
        assert names[feet] == "Spellbreaker's March (331)"

    def test_unicode_guild_survives(self):
        # The fixture's guild name is Cyrillic; parsing must not mangle names.
        assert self.parsed["char_name"] == "Hamidriel"
        assert HAMIDRIEL["character"]["guild"]["name"] == "Не хикка а домосед"

    def test_shape_matches_parse_addon_response(self):
        from src.web.main import ParseAddonResponse
        ParseAddonResponse(**{
            key: value for key, value in self.parsed.items()
            if key not in ("char_spec", "char_ilvl")
        })


class TestGearParsingOnryo:
    def setup_method(self):
        self.parsed = parse_armory_model(ONRYO)

    def test_cosmetic_slots_skipped(self):
        gear = self.parsed["equipped_gear"]
        assert len(ONRYO["character"]["gear"]) == 18   # fixture has shirt+tabard+offhand
        assert len(gear) == 16                          # shirt + tabard dropped
        for details in gear.values():
            assert "id=167082" not in details          # Stylish Black Shirt
            assert "id=69209" not in details           # Illustrious Guild Tabard
        assert ",ilevel=1" not in "".join(gear.values())

    def test_offhand_mapped(self):
        assert self.parsed["equipped_gear"]["off_hand"].startswith("id=270850")

    def test_unicode_name(self):
        assert self.parsed["char_name"] == "Onryô"
        assert self.parsed["char_spec"] == "holy"

    def test_first_enchant_wins(self):
        # weapon carries PERMANENT 8011 first, TEMPORARY 7143 second.
        assert "enchant_id=8011" in self.parsed["equipped_gear"]["main_hand"]
        assert "7143" not in self.parsed["equipped_gear"]["main_hand"]

    def test_duplicate_ring_deduped_in_candidates(self):
        # leftFinger and rightFinger are the same item+enchant+ilvl
        assert self.parsed["equipped_gear"]["finger1"] == self.parsed["equipped_gear"]["finger2"]
        assert len(self.parsed["items_by_slot"]["finger"]) == 1


class TestItemStringEdgeCases:
    def test_minimal_item(self):
        assert armory_item_string({"id": 123}) == "id=123"

    def test_empty_bonus_and_enchant_lists_omitted(self):
        assert armory_item_string({"id": 123, "bonus_list": [], "enchantments": []}) == "id=123"

    def test_none_bonus_and_enchant_lists_omitted(self):
        # The live API sends None (not []) for several slots.
        assert armory_item_string({"id": 123, "bonus_list": None, "enchantments": None}) == "id=123"

    def test_enchant_without_id_ignored(self):
        assert armory_item_string({"id": 1, "enchantments": [{"display_string": "x"}]}) == "id=1"

    def test_field_order(self):
        assert armory_item_string({
            "id": 5, "bonus_list": [7, 8], "enchantments": [{"enchantment_id": 9}],
            "level": {"value": 350},
        }) == "id=5,bonus_id=7/8,enchant_id=9,ilevel=350"

    def test_missing_id_yields_empty(self):
        assert armory_item_string({"name": "no id"}) == ""


class TestParseModelEdgeCases:
    def test_is_outdated_surfaces_warning(self):
        payload = json.loads(json.dumps(HAMIDRIEL))
        payload["character"]["isOutdated"] = True
        assert parse_armory_model(payload)["warnings"]

    def test_remix_character_rejected(self):
        payload = json.loads(json.dumps(HAMIDRIEL))
        payload["character"]["isRemix"] = True
        with pytest.raises(ArmoryInputError):
            parse_armory_model(payload)

    def test_garbage_payload_rejected(self):
        from src.core.armory import ArmoryParseError
        with pytest.raises(ArmoryParseError):
            parse_armory_model({"character": {}})
        with pytest.raises(ArmoryParseError):
            parse_armory_model({})

    def test_unknown_slot_keys_skipped(self):
        payload = json.loads(json.dumps(HAMIDRIEL))
        payload["character"]["gear"]["mysterySlot"] = {"id": 999, "name": "Alien"}
        parsed = parse_armory_model(payload)
        assert len(parsed["equipped_gear"]) == 15
        assert all("id=999" not in v for v in parsed["equipped_gear"].values())


# ---------------------------------------------------------------------------
# Fetch layer: 500 discrimination, retry, cache — faked transport only
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def fake_get_factory(responses):
    """Fake _http_get serving queued responses; records URLs, counts calls."""
    calls = []

    async def fake_get(url):
        calls.append(url)
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    return fake_get, calls


ERROR_500_BODY = load_fixture("error_500_unknown_character.txt")


class TestFetchErrorHandling:
    def run(self, coro):
        return asyncio.run(coro)

    def test_unknown_character_500_html_retries_then_not_found(self, monkeypatch):
        # The real unknown-character response: HTTP 500 + HTML error page
        # (which upstream even labels application/json).
        fake_get, calls = fake_get_factory([
            FakeResponse(500, ERROR_500_BODY),
            FakeResponse(500, ERROR_500_BODY),
        ])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        with pytest.raises(ArmoryNotFoundError):
            self.run(fetch_armory_model("eu", "draenor", "NotACharacter12345"))
        assert len(calls) == 2  # exactly one retry

    def test_500_with_json_content_type_but_html_body_is_not_found(self, monkeypatch):
        # Discriminate by JSON parse, never by content type: a 200 whose
        # body is not JSON is also not-found.
        fake_get, _ = fake_get_factory([FakeResponse(200, ERROR_500_BODY)])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        with pytest.raises(ArmoryNotFoundError):
            self.run(fetch_armory_model("eu", "draenor", "Nope"))

    def test_200_json_without_gear_is_not_found(self, monkeypatch):
        fake_get, _ = fake_get_factory([FakeResponse(200, json.dumps({"character": {}}))])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        with pytest.raises(ArmoryNotFoundError):
            self.run(fetch_armory_model("kr", "draenor", "Hamidriel"))  # wrong region -> 500 IRL

    def test_5xx_then_success_recovers(self, monkeypatch):
        fake_get, calls = fake_get_factory([
            FakeResponse(500, ERROR_500_BODY),
            FakeResponse(200, json.dumps(HAMIDRIEL)),
        ])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        payload = self.run(fetch_armory_model("eu", "draenor", "Hamidriel"))
        assert payload["character"]["name"] == "Hamidriel"
        assert len(calls) == 2

    def test_timeout_retries_then_unavailable(self, monkeypatch):
        fake_get, calls = fake_get_factory([
            httpx.ConnectTimeout("boom"),
            httpx.ConnectTimeout("boom"),
        ])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        with pytest.raises(ArmoryUnavailableError):
            self.run(fetch_armory_model("eu", "draenor", "Hamidriel"))
        assert len(calls) == 2

    def test_rate_limited_429(self, monkeypatch):
        fake_get, _ = fake_get_factory([FakeResponse(429, "slow down")])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        with pytest.raises(ArmoryRateLimitedError):
            self.run(fetch_armory_model("eu", "draenor", "Hamidriel"))

    def test_success_cached_and_url_built(self, monkeypatch):
        fake_get, calls = fake_get_factory([FakeResponse(200, json.dumps(HAMIDRIEL))])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        first = self.run(fetch_armory_model("eu", "Draenor", "hamidriel"))
        second = self.run(fetch_armory_model("eu", "draenor", "Hamidriel"))
        assert first is second
        assert len(calls) == 1  # cache hit, keyed case-insensitively
        assert calls[0] == (
            "https://worldofwarcraft.blizzard.com/en-gb/worldsoul/eu/armory/"
            "character/draenor/hamidriel/model.json"
        )

    def test_unicode_name_percent_encoded_in_request(self, monkeypatch):
        fake_get, calls = fake_get_factory([FakeResponse(200, json.dumps(ONRYO))])
        monkeypatch.setattr(armory, "_http_get", fake_get)
        self.run(fetch_armory_model("us", "illidan", "Onryô"))
        assert calls[0].endswith("/illidan/Onry%C3%B4/model.json")


# ---------------------------------------------------------------------------
# POST /api/armory-load — endpoint shape with mocked fetch (no network)
# ---------------------------------------------------------------------------

class TestArmoryLoadEndpoint:
    def test_url_form_returns_parse_addon_shape(self, monkeypatch):
        async def fake_fetch(region, realm, name):
            assert (region, realm, name.lower()) == ("eu", "draenor", "hamidriel")
            return HAMIDRIEL
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={
            "url": "https://worldofwarcraft.blizzard.com/en-gb/worldsoul/eu/armory/"
                   "character/draenor/Hamidriel",
        })
        assert response.status_code == 200
        data = response.json()
        for key in ("base_profile", "equipped_gear", "items_by_slot", "item_names",
                    "char_name", "char_class", "item_upgrades", "warnings"):
            assert key in data
        assert data["char_name"] == "Hamidriel"
        assert data["char_class"] == "paladin"
        assert data["char_spec"] == "retribution"
        assert data["char_ilvl"] == 329
        assert data["equipped_gear"]["feet"] == (
            "id=237828,bonus_id=12214/13667/12497/13751/14001/8793/13836,"
            "enchant_id=7963,ilevel=331"
        )

    def test_name_realm_region_form(self, monkeypatch):
        seen = {}
        async def fake_fetch(region, realm, name):
            seen.update(region=region, realm=realm, name=name)
            return ONRYO
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={
            "name": "Onryô", "realm": "Illidan", "region": "us",
        })
        assert response.status_code == 200
        assert seen == {"region": "us", "realm": "illidan", "name": "Onryô"}
        assert response.json()["char_name"] == "Onryô"

    def test_combined_name_realm_single_field(self, monkeypatch):
        seen = {}
        async def fake_fetch(region, realm, name):
            seen.update(region=region, realm=realm, name=name)
            return HAMIDRIEL
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={"name": "Hamidriel-Draenor"})
        assert response.status_code == 200
        assert seen == {"region": "eu", "realm": "draenor", "name": "Hamidriel"}

    def test_unknown_character_maps_to_clean_404(self, monkeypatch):
        async def fake_fetch(region, realm, name):
            raise ArmoryNotFoundError(
                f"No character '{name}' found on realm {realm} ({region.upper()}). "
                "Check the name, realm and region."
            )
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={"name": "NotACharacter12345", "realm": "Draenor"})
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "NotACharacter12345" in detail
        assert "<html" not in detail.lower()  # no upstream error page leakage

    def test_unreachable_maps_to_502(self, monkeypatch):
        async def fake_fetch(region, realm, name):
            raise ArmoryUnavailableError("The Armory could not be reached (timeout or connection error). Try again.")
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={"name": "X-Y"})
        assert response.status_code == 502
        assert "could not be reached" in response.json()["detail"]

    def test_rate_limited_maps_to_429(self, monkeypatch):
        async def fake_fetch(region, realm, name):
            raise ArmoryRateLimitedError("The Armory is rate limiting us. Wait a minute and try again.")
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        response = client.post("/api/armory-load", json={"name": "X-Y"})
        assert response.status_code == 429

    def test_bad_input_maps_to_400(self):
        response = client.post("/api/armory-load", json={"name": "NoRealmHere"})
        assert response.status_code == 400
        response = client.post("/api/armory-load", json={"name": "X", "realm": "Y", "region": "moon"})
        assert response.status_code == 400
        response = client.post("/api/armory-load", json={})
        assert response.status_code == 400

    def test_generated_profile_contains_armory_items(self, monkeypatch):
        """End-to-end shape check: the armory-load result feeds /api/generate-simc."""
        async def fake_fetch(region, realm, name):
            return HAMIDRIEL
        monkeypatch.setattr("src.web.main.armory_source.fetch_armory_model", fake_fetch)
        loaded = client.post("/api/armory-load", json={"name": "Hamidriel-Draenor"})
        assert loaded.status_code == 200
        data = loaded.json()
        response = client.post("/api/generate-simc", json={
            "char_class": data["char_class"],
            "char_name": data["char_name"],
            "base_profile": data["base_profile"],
            "equipped_gear": data["equipped_gear"],
            "selected_items": data["items_by_slot"],
            "selected_enchants": {},
            "selected_gems": [],
            "selected_meta_gems": [],
            "item_levels": {},
            "gear_upgrades": {},
            "voidforged_items": {},
            "extra_sockets": {},
        })
        assert response.status_code == 200
        with open(response.json()["file_path"], "r", encoding="utf-8") as handle:
            profile = handle.read()
        assert 'paladin="Hamidriel"' in profile
        assert "id=271468,bonus_id=13334/6652/13690/13698/12854,enchant_id=7987,ilevel=334" in profile
        assert "id=237828" in profile  # Spellbreaker's March feet


# ---------------------------------------------------------------------------
# UI wiring (static files)
# ---------------------------------------------------------------------------

class TestArmoryUiWiring:
    def test_app_html_has_armory_controls(self):
        html = client.get("/").text
        assert 'id="armory-input"' in html
        assert 'id="armory-region"' in html
        assert 'id="btn-armory-load"' in html
        assert "Or load from Armory" in html
        # addon paste path stays present and primary
        assert 'id="addon-input"' in html
        assert 'id="btn-parse-addon"' in html

    def test_app_js_calls_armory_endpoint(self):
        with open("src/web/static/app.js", "r", encoding="utf-8") as handle:
            script = handle.read()
        assert "/api/armory-load" in script
        assert "applyParsedCharacter" in script

    def test_style_has_armory_classes(self):
        with open("src/web/static/style.css", "r", encoding="utf-8") as handle:
            css = handle.read()
        for css_class in (".armory-import", ".armory-input", ".armory-region-select", ".armory-hint"):
            assert css_class in css
