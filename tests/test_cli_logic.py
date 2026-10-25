import json
import os
import sys
from unittest.mock import MagicMock, patch

# Add src to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from cli.generate_input import (
    apply_gear_upgrade,
    apply_item_level,
    apply_mod,
    generate_variations,
    load_config,
    midnight_track_level,
    parse_addon_file,
    select_items_interactive,
)
from core.upgrade_data import detect_season, get_season, load_upgrade_seasons


def test_load_config(tmp_path):
    config_data = {
        "enchantments": {"chest": [123]},
        "gems": {"neck": [456]}
    }
    config_file = tmp_path / "config.json"
    with open(config_file, "w") as f:
        json.dump(config_data, f)
        
    loaded = load_config(str(config_file))
    assert loaded["enchantments"]["chest"] == [123]
    assert loaded["gems"]["neck"] == [456]
    
    # Test loading non-existent file returns defaults
    assert "enchantments" in load_config("invalid.json")

def test_apply_mod():
    gear_str = "id=123,bonus_id=456"
    
    # Test adding enchant
    res = apply_mod(gear_str, "enchant_id", 789)
    assert "enchant_id=789" in res
    assert "id=123" in res
    
    # Test replacing enchant
    gear_str_with_enchant = "id=123,enchant_id=111,bonus_id=456"
    res = apply_mod(gear_str_with_enchant, "enchant_id", 222)
    assert "enchant_id=222" in res
    assert "enchant_id=111" not in res
    
    # Test adding gem
    res = apply_mod(gear_str, "gem_id", 999)
    assert "gem_id=999" in res

def test_apply_item_level_adds_and_replaces_ilevel():
    assert apply_item_level("id=123,bonus_id=456", 626) == ",id=123,ilevel=626,bonus_id=456"
    assert apply_item_level("id=123,ilevel=610,bonus_id=456", "640") == ",id=123,ilevel=640,bonus_id=456"
    assert apply_item_level("id=123,bonus_id=456", "") == "id=123,bonus_id=456"
    assert apply_item_level("id=123,bonus_id=456", "abc") == "id=123,bonus_id=456"


def test_apply_item_level_can_add_voidforge_bonus_for_weapons_and_trinkets():
    s1 = get_season("midnight-s1")
    assert apply_item_level("id=123,ilevel=276", "276", slot="trinket", voidforged=True, season=s1) == ",id=123,ilevel=285"
    assert apply_item_level("id=123,ilevel=289", "289", slot="main_hand", voidforged=True, season=s1) == ",id=123,ilevel=298"
    # Season 2 Venomforged is track-dependent: no flat bonus on the manual path.
    s2 = get_season("midnight-s2")
    assert apply_item_level("id=123,ilevel=334", "334", slot="trinket", voidforged=True, season=s2) == ",id=123,ilevel=334"


def test_midnight_track_level_maps_track_and_rank_to_item_level():
    s1 = get_season("midnight-s1")
    assert midnight_track_level("hero", 1, season=s1) == 259
    assert midnight_track_level("hero", 6, season=s1) == 276
    assert midnight_track_level("myth", 6, season=s1) == 289
    assert midnight_track_level("unknown", 1) is None
    assert midnight_track_level("myth", 7) is None
    # Default season is the live one (Season 2 ladders).
    assert midnight_track_level("hero", 1) == 305
    assert midnight_track_level("hero", 6) == 321
    assert midnight_track_level("myth", 6) == 334
    assert midnight_track_level("myth", 7) is None


def test_apply_gear_upgrade_uses_midnight_track_rank_instead_of_manual_item_level():
    s1 = get_season("midnight-s1")
    assert apply_gear_upgrade("id=123,bonus_id=456", {"track": "myth", "rank": 6}, season=s1) == ",id=123,ilevel=289,bonus_id=456"
    assert apply_gear_upgrade("id=123,ilevel=263", {"track": "hero", "rank": 6}, season=s1) == ",id=123,ilevel=276"
    assert apply_gear_upgrade("id=123,ilevel=276", {"track": "myth", "rank": 6}, slot="trinket", voidforged=True, season=s1) == ",id=123,ilevel=298"
    # Season 2: Venomforged resolves to absolute ascended ilvls (hero 328 / myth 341).
    assert apply_gear_upgrade("id=123,bonus_id=456", {"track": "myth", "rank": 6}) == ",id=123,ilevel=334,bonus_id=456"
    assert apply_gear_upgrade("id=123,ilevel=334", {"track": "myth", "rank": 6}, slot="trinket", voidforged=True) == ",id=123,ilevel=341"
    assert apply_gear_upgrade("id=123,ilevel=321", {"track": "hero", "rank": 6}, slot="main_hand", voidforged=True) == ",id=123,ilevel=328"
    # Non-eligible slots never ascend.
    assert apply_gear_upgrade("id=123,ilevel=334", {"track": "myth", "rank": 6}, slot="head", voidforged=True) == ",id=123,ilevel=334"


def test_apply_gear_upgrade_prefers_export_provided_item_level():
    """Absolute ilvls from the export's upgrade_levels comment beat static ladders."""
    # 331 is not on any static myth ladder; the export data still drives generation.
    assert apply_gear_upgrade("id=123,ilevel=327", {"source": "export", "rank": 1, "item_level": 331}) == ",id=123,ilevel=331"
    # Rank 0 = "Current": applies the current absolute ilvl (no-op override).
    assert apply_gear_upgrade("id=123,ilevel=327", {"source": "export", "rank": 0, "item_level": 327}) == ",id=123,ilevel=327"
    # A garbage item_level falls back to the track/rank ladder.
    assert apply_gear_upgrade("id=123,ilevel=327", {"source": "export", "track": "myth", "rank": 6, "item_level": "nope"}) == ",id=123,ilevel=334"
    # Ascension (Venomforged) still overrides export ranks when a track is known.
    assert apply_gear_upgrade("id=123,ilevel=327", {"source": "export", "track": "myth", "rank": 1, "item_level": 331}, slot="trinket", voidforged=True) == ",id=123,ilevel=341"
    # Non-export entries (e.g. Wowhead hydration) keep using track/rank even
    # though they carry item_level (which there is the item's *current* level).
    assert apply_gear_upgrade("id=123,ilevel=327", {"track": "myth", "rank": 6, "item_level": 327}) == ",id=123,ilevel=334"


def test_apply_gear_upgrade_crafted_base_uses_crafted_ascension_ilvl():
    """C1: a max-quality crafted base ascends to the season's crafted_results
    ilvl (lower than the track results value); non-crafted lines are unchanged."""
    s1 = get_season("midnight-s1")
    # S2 crafted Venomforged: myth 337 / hero 324 (not the track 341 / 328).
    assert apply_gear_upgrade("id=1,ilevel=331,crafted_stats=1/2", {"track": "myth", "rank": 6}, slot="trinket", voidforged=True) == ",id=1,ilevel=337,crafted_stats=1/2"
    assert apply_gear_upgrade("id=1,ilevel=331,crafted_stats=1/2", {"track": "hero", "rank": 6}, slot="main_hand", voidforged=True) == ",id=1,ilevel=324,crafted_stats=1/2"
    # Same line WITHOUT a crafted marker keeps the track ascended ilvl.
    assert apply_gear_upgrade("id=1,ilevel=331", {"track": "myth", "rank": 6}, slot="trinket", voidforged=True) == ",id=1,ilevel=341"
    # crafting_quality= is the other crafted marker (app.js isCraftedItem parity).
    assert apply_gear_upgrade("id=1,ilevel=331,crafting_quality=4", {"track": "myth", "rank": 6}, slot="trinket", voidforged=True) == ",id=1,ilevel=337,crafting_quality=4"
    # S1 crafted myth Voidforged: 295 (not the track 298).
    assert apply_gear_upgrade("id=1,ilevel=283,crafted_stats=1/2", {"track": "myth", "rank": 6}, slot="trinket", voidforged=True, season=s1) == ",id=1,ilevel=295,crafted_stats=1/2"
    # Ineligible slot never ascends, crafted or not (stays at the track level).
    assert apply_gear_upgrade("id=1,ilevel=331,crafted_stats=1/2", {"track": "myth", "rank": 6}, slot="head", voidforged=True) == ",id=1,ilevel=334,crafted_stats=1/2"


def test_apply_item_level_does_not_voidforge_non_eligible_slots_or_double_apply():
    assert apply_item_level("id=123,ilevel=276", "276", slot="head", voidforged=True) == ",id=123,ilevel=276"
    assert apply_item_level("id=123,ilevel=298", "298", slot="trinket", voidforged=True) == ",id=123,ilevel=298"


def test_detect_season_prefers_active_for_live_ilvls_and_falls_back_for_old_exports():
    assert detect_season([318, 334, 295])["id"] == "midnight-s2"
    # Overlapping ilvl (276 is in both ladders): live-first, active season wins.
    assert detect_season([276])["id"] == "midnight-s2"
    # Below the active band: archived Season 1 export still resolves.
    assert detect_season([220, 250, 263])["id"] == "midnight-s1"
    # No usable ilvls: active season default.
    assert detect_season([])["id"] == "midnight-s2"
    assert detect_season([None, "abc"])["id"] == "midnight-s2"


def test_upgrade_seasons_data_matches_live_midnight_values():
    """T1 data-validation (audit risk #9): the live values spec t_080134d5 cites
    (engine-probed / Wowhead-cited), plus structural invariants a future season
    edit must not break."""
    s1 = get_season("midnight-s1")
    s2 = get_season("midnight-s2")

    # Live values.
    assert s2["elevated_ilvls"] == [344]
    assert s2["ascension"]["bonus_ids"] == ["12856"]
    assert s1["ascension"]["cost"] == 1
    assert s1["ascension"]["crafted_results"] == {"hero": 282, "myth": 295}
    assert s1["ascension"]["bonus_ids"] == ["13653", "13654"]

    # Structure: 5 tracks x 6 ranks, each ladder strictly increasing, band covers it.
    for season in (s1, s2):
        lo, hi = season["ilvl_band"]
        assert len(season["tracks"]) == 5
        for levels in season["tracks"].values():
            assert len(levels) == 6
            assert all(b > a for a, b in zip(levels, levels[1:]))
            assert lo <= levels[0] and levels[-1] <= hi

    # Ascended ilvls (track + crafted) stay within the known live tiers.
    s2_asc = set(s2["ascension"]["results"].values()) | set(s2["ascension"]["crafted_results"].values())
    s1_asc = set(s1["ascension"]["results"].values()) | set(s1["ascension"]["crafted_results"].values())
    assert s2_asc <= {324, 328, 337, 341}
    assert s1_asc <= {282, 285, 295, 298}


def test_generate_variations():
    item_list = ["id=100", "id=200"]
    config = {
        "enchantments": {"head": [1, 2]},
        "gems": {"head": [10]}
    }
    
    # Test head slot with both enchants and gems
    vars = generate_variations(item_list, "head", config)
    # 2 items * 2 enchants * 1 gem = 4 variations
    assert len(vars) == 4
    # Check that both IDs are present in the first variation
    res_str = vars[0]
    assert "enchant_id=1" in res_str
    assert "gem_id=10" in res_str
    assert "id=100" in res_str
    
    # Test slot with no config
    vars = generate_variations(item_list, "back", config)
    assert len(vars) == 2
    assert vars == ["," + i for i in item_list]

def test_generate_variations_excludes_meta_gems_from_item_variations():
    item_list = ["id=100,gem_id=240888"]
    config = {
        "enchantments": {},
        "gems": {
            "meta": [240967],
            "standard": [240888],
        },
    }

    vars = generate_variations(item_list, "head", config)
    assert vars == [",id=100,gem_id=240888"]
    assert all("240967" not in var for var in vars)


def test_generate_variations_does_not_add_standard_gems_to_unsocketed_items():
    config = {
        "enchantments": {},
        "gems": {
            "meta": [240967],
            "standard": [240908],
        },
    }

    for slot in ("chest", "legs", "trinket"):
        vars = generate_variations(["id=100"], slot, config)
        assert vars == [",id=100"]
        assert all("gem_id=" not in var for var in vars)


def test_generate_variations_always_gems_jewelry_without_exported_socket():
    # C2: finger/neck always have exactly one socket, so they get standard gem
    # variations even when the export omits gem_id= (t_fa0d755f §4).
    config = {
        "enchantments": {},
        "gems": {
            "meta": [240967],
            "standard": [240908],
        },
    }
    for slot in ("finger", "neck"):
        vars = generate_variations(["id=100"], slot, config)
        assert vars == [",id=100,gem_id=240908"]


def test_generate_variations_applies_standard_gems_to_existing_or_extra_sockets():
    config = {
        "enchantments": {},
        "gems": {
            "meta": [240967],
            "standard": [240908],
        },
    }

    existing_socket = generate_variations(["id=100,gem_id=240888"], "finger", config)
    extra_socket = generate_variations(["id=200"], "head", config, extra_sockets={"head": True})

    assert existing_socket == [",id=100,gem_id=240908"]
    assert extra_socket == [",id=200,gem_id=240908"]


def test_parse_addon_data(tmp_path):
    addon_content = """
paladin="Hamidriel"
head=id=12345
# Helm of Might
finger1=id=111
# Ring 1
### Gear from Bags
# Girdle of Giant Strength (100)
# waist=id=67890
# Another Ring
# finger=id=333
### Additional Character Info
"""
    addon_file = tmp_path / "addon.txt"
    addon_file.write_text(addon_content)
    
    base_profile, equipped, items_by_slot, item_names, char_name, char_class, _item_upgrades = parse_addon_file(str(addon_file))
    
    assert char_name == "Hamidriel"
    assert char_class == "paladin"
    assert equipped["head"] == "id=12345"
    assert "waist" in items_by_slot
    assert items_by_slot["waist"][0] == "id=67890"
    assert item_names["id=67890"] == "Girdle of Giant Strength (100)"
    assert "finger" in items_by_slot
    assert "id=111" in items_by_slot["finger"]
    assert "id=333" in items_by_slot["finger"]

def test_select_items_interactive():
    items_by_slot = {"waist": ["id=1", "id=2"]}
    item_names = {"id=1": "Belt A", "id=2": "Belt B"}
    equipped_gear = {"waist": "id=1"}
    
    # 1. Test default selection (Enter)
    with patch("builtins.input", return_value=""):
        res = select_items_interactive(items_by_slot, item_names, equipped_gear)
        assert res["waist"] == ["id=1"]
        
    # 2. Test explicit selection
    with patch("builtins.input", return_value="2"):
        res = select_items_interactive(items_by_slot, item_names, equipped_gear)
        assert res["waist"] == ["id=2"]

    # 3. Test multiple selection
    with patch("builtins.input", return_value="1,2"):
        res = select_items_interactive(items_by_slot, item_names, equipped_gear)
        assert len(res["waist"]) == 2
        assert "id=1" in res["waist"]
        assert "id=2" in res["waist"]

def test_main_addon_not_found(tmp_path):
    from cli.generate_input import main
    with patch("cli.generate_input.os.path.exists", return_value=False), \
         patch("builtins.print") as mock_print:
        main()
        mock_print.assert_any_call("Error: char_simc_addon.txt not found.")

def test_main_success_flow(tmp_path):
    from cli.generate_input import main
    
    # Mock files
    with patch("cli.generate_input.os.path.exists", return_value=True), \
         patch("cli.generate_input.load_config", return_value={}), \
         patch("cli.generate_input.load_globals", return_value=""), \
         patch("cli.generate_input.parse_addon_file", return_value=("", {}, {"head":["id=1"]}, {"id=1":"H"}, "Char", "paladin", {})), \
         patch("cli.generate_input.select_items_interactive", return_value={"head":["id=1"]}), \
         patch("builtins.open", MagicMock()):
        
        main() # Should run through without error
