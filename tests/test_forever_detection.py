"""WoW: Forever export detection tests.

Fixtures are built from the official addon's Forever output path:
simc-addon core.lua (master, fetched 2026-10-13) GetSimcProfile +
forever/stats.lua.  Forever-only sections (``# skills=``, ``# buffs=``,
``# character_stats*=``, the bare stat keys and ``# pet_*=``) are gated
behind EXPORTS.character_stats/skills/buffs, which are only set when the
Forever client is detected (IS_FOREVER).  Retail exports never contain them.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.core.addon_parser import (
    FOREVER_EXPORT_MESSAGE,
    forever_export_warnings,
    is_forever_export,
    parse_addon_lines,
)
from web.main import app

client = TestClient(app)

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


# A full Forever export as the addon (with experimental Forever support,
# release #124) emits it: no spec in the header, bare spec=unknown, no
# "# loot_spec=" comment, Forever TOC, and the Forever-only stats/skills/
# buffs comment blocks at the end.
FOREVER_EXPORT = """# Mankrik - 2026-10-13 12:34 - EU/Ravenholdt
# SimC Addon 12.1.5-01
# WoW 1.60.1.99999, TOC 16001
# Requires SimulationCraft 1000-01 or newer

warrior="Mankrik"
level=60
race=orc
region=EU
server=Ravenholdt
role=attack

spec=unknown

talents=1234-5678-90

# Wristguards of the Skyborne
head=id=120001,ilvl=60,gems=,bonus_stats=1013_540
# Skyborne Greatsword
main_hand=id=120002,ilvl=60,speed=3.60

### Gear from Bags
#
# Haste-Bracers
# wrist=id=120003,ilvl=60

#
# character_stats=health:5400/power_type:0/mana:10000/strength:245/agility:120/stamina:340/intellect:60/spirit:55
# character_stats_base=strength:200/agility:100/stamina:300/intellect:50/spirit:50
# character_stats_bonus=strength:45/agility:20/stamina:40
# character_stats_gear=armor:1250/agility:40/strength:30
# attack_power=melee:780:120:0
# spell_power=holy:0/fire:0/nature:0/frost:0/shadow:0/arcane:0
# spell_stats=healing:0/penetration:0
# regen=health:12:4/mana:5:2
# crit=melee:5.2/ranged:5.2/spell:5.0
# hit=melee_rating_bonus:0/melee_modifier:0/ranged_rating_bonus:0/ranged_modifier:0/spell_rating_bonus:0/spell_modifier:0
# haste=melee:100.0/ranged:100.0/ranged_ammo:0.0/spell:100.0
# combat_modifiers=expertise:0/expertise_offhand:0/expertise_ranged:0/armor_penetration:0/mastery:0
# combat_ratings=defense:0:0/dodge:0:0/parry:0:0
# defense=armor_base:500/armor_effective:1250/armor:1250/armor_bonus:0/defense_skill:300/defense_modifier:0/dodge:5.0/parry:5.0/block:0.0/block_value:0
# resistances=holy:10/fire:10/nature:10/frost:10/shadow:10/arcane:10
# weapon_damage=mainhand:120:180:2.6/pos_buff:0/neg_buff:0/percent:100
# pet_info=npc_id:416/level:60/name:skyborne_wolf/family:wolf/type:beast/loyalty:good
# pet_stats=health:3200/power_type:0/strength:150/agility:220/stamina:200
# pet_attack_power=melee:310:40:0
# pet_modifiers=spell_power:0/haste_melee:100.0/hit_melee_modifier:0
# pet_defense=armor_base:400/armor_effective:900/armor:900/armor_bonus:0/defense_skill:300/dodge:5.0/parry:5.0
# pet_resistances=holy:10/fire:10/nature:10/frost:10/shadow:10/arcane:10
# pet_weapon_damage=mainhand:60:90:1.5/pos_buff:0/neg_buff:0/percent:100

# skills=750:300:0:300/754:300:0:300/762:300:0:300

# buffs=19210:1/20153:1

# Checksum: 1a2b3c4d
"""

# A realistic Midnight (retail) export: spec in header + loot_spec comment,
# retail TOC, upgrade_levels debug comment, bonus-roll comments, checksum —
# none of the Forever-only sections.
RETAIL_EXPORT = """# Thrall - Enhancement - 2026-10-13 12:30 - EU/Durotan
# SimC Addon 12.1.5-01
# WoW 12.0.5.64872, TOC 120105
# Requires SimulationCraft 1000-01 or newer

shaman="Thrall"
level=90
race=orc
region=EU
server=Durotan
role=attack
professions=alchemy=1/inscription=1
spec=enhancement
# loot_spec=enhancement

talents=11231-00001-00000000000000000000000000000000000000000000000000000

omnium_talents=1a1b2c3d4e

# Voidscale Greaves (327)
head=id=274766,ilvl=327,gems=4,bonus_stats=1462_6459
# Voidscale Pauldrons (327)
# upgrade_levels=2:4:c#3047#40#0:/3:8:c#3047#80#0:
chest=id=274767,ilvl=327

### Gear from Bags
#
# Crude Brambleblade
# main_hand=id=99112,ilvl=300
#
# loot_spec=enhancement trinket
# trinket1=id=99113,ilvl=300

# bonus_roll_items=i#99114#1#0

# Checksum: deadbeef
"""


class TestForeverDetectionUnit:
    def test_forever_fixture_detected(self):
        assert is_forever_export(FOREVER_EXPORT.splitlines()) is True

    @pytest.mark.parametrize("marker", [
        "# skills=750:300:0:300/754:300:0:300",
        "# buffs=19210:1/20153:1",
        "# character_stats=health:5400/power_type:0",
        "# character_stats_base=strength:200",
        "# character_stats_bonus=strength:45",
        "# character_stats_gear=armor:1250",
        "# pet_info=npc_id:416/level:60",
        "# pet_stats=health:3200",
        "# attack_power=melee:780:120:0",
        "# spell_power=holy:0/fire:0",
        "# spell_stats=healing:0/penetration:0",
        "# regen=health:12:4/mana:5:2",
        "# crit=melee:5.2/ranged:5.2",
        "# hit=melee_rating_bonus:0/melee_modifier:0",
        "# haste=melee:100.0",
        "# combat_modifiers=expertise:0",
        "# combat_ratings=defense:0:0",
        "# defense=armor_base:500",
        "# resistances=holy:10",
        "# weapon_damage=mainhand:120:180:2.6",
    ])
    def test_each_marker_alone_detected(self, marker):
        assert is_forever_export(marker.splitlines()) is True

    def test_retail_fixture_not_detected(self):
        assert is_forever_export(RETAIL_EXPORT.splitlines()) is False

    def test_repo_sample_export_not_detected(self):
        with open(os.path.join(REPO_ROOT, "char_simc_addon.txt")) as f:
            assert is_forever_export(f.read().splitlines()) is False

    def test_generic_keys_need_value_shape_no_false_positives(self):
        # Free-text or differently-shaped comments must never trip the
        # generically-named keys.
        benign = [
            "# crit is a great stat",
            "# crit=5.2",                # no name: prefix
            "# hit me up later",
            "# haste=whatever",          # no name:value shape
            "# skills=abc",              # not the addon's 4-field grammar
            "# skills=750:300",          # too few fields
            "# buffs=19210",             # no :stacks
            "# defense against evil",
            "# regen=12",
            "# weapon_damage",
        ]
        assert is_forever_export(benign) is False

    def test_item_name_comments_never_trip(self):
        names = [
            "# Haste-Bracers",
            "# Crit Ring",
            "# Attack Power Amulet",
            "# head=id=123,ilvl=300",   # bag item comment (slot key)
            "# loot_spec=enhancement trinket",
            "# upgrade_levels=2:4:c#3047#40#0:",
            "# bonus_roll_items=i#99114#1#0",
            "# Checksum: deadbeef",
        ]
        assert is_forever_export(names) is False

    def test_forever_export_still_parses_if_called_directly(self):
        # Detection is a gate in front of parsing; the parser itself is
        # unchanged and never raises on Forever input.
        base_profile, equipped, *_ = parse_addon_lines(FOREVER_EXPORT.splitlines())
        assert "warrior=" in base_profile
        assert equipped["head"].startswith("id=120001")


class TestSoftWarnings:
    def test_forever_like_without_markers_warns_but_parses(self):
        lines = [
            "# Mankrik - 2026-10-13 12:34 - EU/Ravenholdt",
            "# WoW 1.60.1.99999, TOC 16001",
            'warrior="Mankrik"',
            "spec=unknown",
            "head=id=123",
        ]
        assert is_forever_export(lines) is False
        warnings = forever_export_warnings(lines)
        assert len(warnings) == 2
        assert any("TOC 16001" in w for w in warnings)
        assert any("loot_spec" in w for w in warnings)

    def test_retail_export_has_no_warnings(self):
        assert forever_export_warnings(RETAIL_EXPORT.splitlines()) == []

    def test_retail_no_spec_character_warns_only_about_spec(self):
        # A retail character without a spec yet: spec=unknown but the
        # retail-only "# loot_spec=" comment is present, so no warning.
        lines = ["shaman=Test", "spec=unknown", "# loot_spec=unknown", "head=id=1"]
        assert forever_export_warnings(lines) == []

    def test_repo_sample_export_has_no_warnings(self):
        with open(os.path.join(REPO_ROOT, "char_simc_addon.txt")) as f:
            assert forever_export_warnings(f.read().splitlines()) == []


class TestParseAddonEndpoint:
    def test_forever_export_rejected_with_clear_message(self):
        response = client.post("/api/parse-addon", json={"addon_text": FOREVER_EXPORT})
        assert response.status_code == 400
        assert response.json()["detail"] == FOREVER_EXPORT_MESSAGE
        assert "WoW: Forever" in response.json()["detail"]
        assert "Midnight (retail)" in response.json()["detail"]

    def test_retail_export_accepted(self):
        response = client.post("/api/parse-addon", json={"addon_text": RETAIL_EXPORT})
        assert response.status_code == 200
        data = response.json()
        assert data["char_name"] == "Thrall"
        assert data["char_class"] == "shaman"
        assert data["warnings"] == []
        assert data["equipped_gear"]["head"].startswith("id=274766")
        assert "id=274767,ilvl=327" in data["item_upgrades"]

    def test_repo_sample_export_accepted(self):
        with open(os.path.join(REPO_ROOT, "char_simc_addon.txt")) as f:
            response = client.post("/api/parse-addon", json={"addon_text": f.read()})
        assert response.status_code == 200
        # The volatile char_simc_addon.txt is also the legacy write path of
        # generate-simc, so earlier tests may leave copy= blocks in it; the
        # TG3-D2 warning for those is legitimate. What must stay absent is
        # any FOREVER-export warning.
        assert all("embedded copy" in w for w in response.json()["warnings"])

    def test_minimal_export_has_empty_warnings_field(self):
        response = client.post("/api/parse-addon", json={"addon_text": "paladin=Test\nhead=id=123"})
        assert response.status_code == 200
        assert response.json()["warnings"] == []

    def test_forever_like_without_markers_accepted_with_warnings(self):
        addon_text = (
            "# Mankrik - 2026-10-13 12:34 - EU/Ravenholdt\n"
            "# WoW 1.60.1.99999, TOC 16001\n"
            'warrior="Mankrik"\n'
            "spec=unknown\n"
            "head=id=123\n"
        )
        response = client.post("/api/parse-addon", json={"addon_text": addon_text})
        assert response.status_code == 200
        assert len(response.json()["warnings"]) == 2


class TestUiSurfaces:
    def test_warning_panel_exists_and_is_wired(self):
        html = open(os.path.join(REPO_ROOT, "src/web/static/app.html")).read()
        assert 'id="parse-warning"' in html
        js = open(os.path.join(REPO_ROOT, "src/web/static/app.js")).read()
        assert "showParseWarning" in js
        assert "clearParseWarning" in js
        assert "parsedData.warnings" in js
        css = open(os.path.join(REPO_ROOT, "src/web/static/style.css")).read()
        assert ".warning-panel" in css

    def test_error_message_renders_via_show_parse_error(self):
        # The 400 path surfaces detail.detail through showParseError; make
        # sure that wiring is still in place.
        js = open(os.path.join(REPO_ROOT, "src/web/static/app.js")).read()
        assert "detail.detail" in js
        assert "showParseError(`Could not parse the export: ${error.message}`)" in js
