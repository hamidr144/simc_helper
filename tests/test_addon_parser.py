"""Unit tests for src.core.addon_parser.

Tests the parse_addon_lines function which parses SimulationCraft addon
exports into structured character data, gear, and base profile lines.
"""

import os
import sys

# Ensure the project src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.core.addon_parser import (
    CLASSES,
    SLOTS,
    parse_addon_lines,
)


class TestBasicParsing:
    """Test basic addon export parsing."""

    def test_parse_minimal(self):
        """Minimal addon text with just character info."""
        lines = ["paladin=TestChar"]
        base_profile, equipped, items_by_slot, item_names, char_name, char_class = parse_addon_lines(lines)
        assert char_name == "TestChar"
        assert char_class == "paladin"
        assert "paladin=TestChar" in base_profile
        assert equipped == {}
        assert items_by_slot == {}
        assert item_names == {}

    def test_parse_character_and_gear(self):
        """Parse character info plus equipped gear."""
        lines = [
            "paladin=TestChar",
            "level=90",
            "race=blood_elf",
            "head=id=123",
            "chest=id=456",
        ]
        base_profile, equipped, items_by_slot, item_names, char_name, char_class = parse_addon_lines(lines)
        assert char_name == "TestChar"
        assert char_class == "paladin"
        assert equipped["head"] == "id=123"
        assert equipped["chest"] == "id=456"
        assert "id=123" in items_by_slot["head"]
        assert "id=456" in items_by_slot["chest"]
        assert "paladin=TestChar" in base_profile
        assert "level=90" in base_profile
        assert "race=blood_elf" in base_profile

    def test_parse_all_slots_equipped(self):
        """Parse all 16 equipment slots as equipped gear."""
        lines = ["rogue=TestChar"]
        for slot in SLOTS:
            lines.append(f"{slot}=id={hash(slot) % 10000}")
        _, equipped, items_by_slot, _, _, _ = parse_addon_lines(lines)
        # All 16 slots should be in equipped
        for slot in SLOTS:
            assert slot in equipped, f"Missing equipped slot: {slot}"

    def test_parse_finger_slots_normalized_in_items(self):
        """Finger1 and finger2 should be normalized to 'finger' key in items_by_slot."""
        lines = ["warrior=TestChar", "finger1=id=111", "finger2=id=222"]
        _, equipped, items_by_slot, _, _, _ = parse_addon_lines(lines)
        assert equipped["finger1"] == "id=111"
        assert equipped["finger2"] == "id=222"
        assert "finger" in items_by_slot
        assert "id=111" in items_by_slot["finger"]
        assert "id=222" in items_by_slot["finger"]

    def test_parse_trinket_slots_normalized_in_items(self):
        """Trinket1 and trinket2 should be normalized to 'trinket' key in items_by_slot."""
        lines = ["mage=TestChar", "trinket1=id=111", "trinket2=id=222"]
        _, equipped, items_by_slot, _, _, _ = parse_addon_lines(lines)
        assert equipped["trinket1"] == "id=111"
        assert equipped["trinket2"] == "id=222"
        assert "trinket" in items_by_slot
        assert "id=111" in items_by_slot["trinket"]
        assert "id=222" in items_by_slot["trinket"]


class TestBaseProfile:
    """Test that non-gear lines go into the base profile."""

    def test_non_gear_lines_in_base_profile(self):
        """Lines that don't match a slot should be in base profile."""
        lines = ["deathknight=Test", "level=90", "race=goblin", "spec=blood"]
        base_profile, _, _, _, _, _ = parse_addon_lines(lines)
        assert "deathknight=Test" in base_profile
        assert "level=90" in base_profile
        assert "race=goblin" in base_profile
        assert "spec=blood" in base_profile

    def test_base_profile_preserves_line_breaks(self):
        """Base profile should preserve newlines between lines."""
        lines = ["druid=Test", "level=90", "race=tauren"]
        base_profile, _, _, _, _, _ = parse_addon_lines(lines)
        assert "druid=Test\nlevel=90\nrace=tauren" in base_profile

    def test_gear_lines_excluded_from_base_profile(self):
        """Equipped gear lines should NOT appear in base profile."""
        lines = ["hunter=Test", "head=id=999"]
        base_profile, equipped, _, _, _, _ = parse_addon_lines(lines)
        assert "head=id=999" not in base_profile
        assert equipped["head"] == "id=999"

    def test_empty_lines_skipped(self):
        """Empty lines should be skipped."""
        lines = ["priest=Test", "", "  ", "\t", "level=90"]
        base_profile, _, _, _, _, _ = parse_addon_lines(lines)
        assert "priest=Test" in base_profile
        assert "level=90" in base_profile


class TestBagGear:
    """Test parsing of bag items (### Gear from Bags section)."""

    def test_parse_bag_gear(self):
        """Items in the Bags section should be parsed."""
        lines = [
            "shaman=TestChar",
            "head=id=100",
            "### Gear from Bags",
            "# head=id=200",
            "# chest=id=300",
            "### Additional Character Info",
        ]
        _, equipped, items_by_slot, item_names, char_name, char_class = parse_addon_lines(lines)
        assert char_name == "TestChar"
        assert char_class == "shaman"
        # Equipped gear (before Bags)
        assert equipped["head"] == "id=100"
        # Bag items
        assert "id=200" in items_by_slot["head"]
        assert "id=300" in items_by_slot["chest"]

    def test_bag_gear_finger_trinket_normalized(self):
        """Bag finger/trinket items should be normalized."""
        lines = [
            "warlock=Test",
            "### Gear from Bags",
            "# finger1=id=111",
            "# trinket1=id=222",
            "### Additional Character Info",
        ]
        _, _, items_by_slot, _, _, _ = parse_addon_lines(lines)
        assert "finger" in items_by_slot
        assert "id=111" in items_by_slot["finger"]
        assert "trinket" in items_by_slot
        assert "id=222" in items_by_slot["trinket"]

    def test_bag_gear_valid_slots(self):
        """All SLOTS are valid in bag section."""
        lines = [
            "rogue=Test",
            "### Gear from Bags",
            "# head=id=100",
            "# feet=id=200",
            "# neck=id=300",
            "### Additional Character Info",
        ]
        _, _, items_by_slot, _, _, _ = parse_addon_lines(lines)
        # All three are valid slots
        assert "head" in items_by_slot
        assert "feet" in items_by_slot
        assert "neck" in items_by_slot

    def test_no_bags_section_no_bag_items(self):
        """Without Bags section, only equipped gear is parsed."""
        lines = [
            "rogue=Test",
            "head=id=100",
            "chest=id=200",
        ]
        _, equipped, items_by_slot, _, _, _ = parse_addon_lines(lines)
        assert equipped["head"] == "id=100"
        assert "id=100" in items_by_slot["head"]


class TestNameComments:
    """Test that name comments from bag items are captured."""

    def test_item_names_captured_from_preceding_comment(self):
        """A comment line before a gear item should be captured."""
        lines = [
            "paladin=Test",
            "### Gear from Bags",
            "# This is a comment for the next item",
            "# head=id=100",
            "### Additional Character Info",
        ]
        _, _, _, item_names, _, _ = parse_addon_lines(lines)
        # current_name_comment should be "This is a comment for the next item"
        assert "id=100" in item_names
        assert item_names["id=100"] == "This is a comment for the next item"

    def test_no_preceding_comment_yields_empty_name(self):
        """No preceding comment means empty item name."""
        lines = [
            "mage=Test",
            "### Gear from Bags",
            "# head=id=100",
            "### Additional Character Info",
        ]
        _, _, _, item_names, _, _ = parse_addon_lines(lines)
        assert item_names.get("id=100") == ""


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_lines(self):
        """Empty input should return sensible defaults."""
        lines = []
        _, _, _, _, char_name, char_class = parse_addon_lines(lines)
        assert char_name == "Unknown"
        assert char_class == "Unknown"

    def test_only_whitespace_lines(self):
        """Whitespace-only lines should be handled."""
        lines = ["   ", "\n", "\t"]
        _, _, _, _, char_name, char_class = parse_addon_lines(lines)
        assert char_name == "Unknown"
        assert char_class == "Unknown"

    def test_unknown_class_not_in_classes_dict(self):
        """Unknown class names (not in CLASSES dict) should not match."""
        lines = ["customclass=TestChar"]
        _, _, _, _, char_name, char_class = parse_addon_lines(lines)
        # Only known classes trigger char_class assignment
        assert char_class == "Unknown"
        assert char_name == "Unknown"

    def test_simple_name_with_alphanumeric(self):
        """Simple alphanumeric character name should parse."""
        lines = ["warrior=TestChar123"]
        _, _, _, _, char_name, char_class = parse_addon_lines(lines)
        assert char_class == "warrior"
        assert char_name == "TestChar123"

    def test_duplicate_gear_items_not_duplicated(self):
        """Duplicate gear entries should not be added twice."""
        lines = ["paladin=Test", "head=id=123", "head=id=123"]
        _, _, items_by_slot, _, _, _ = parse_addon_lines(lines)
        assert items_by_slot["head"].count("id=123") == 1

    def test_additional_info_section_stops_parsing(self):
        """### Additional Character Info should stop parsing."""
        lines = [
            "druid=Test",
            "head=id=100",
            "### Additional Character Info",
            "head=id=999",  # This should be ignored
        ]
        _, equipped, _, _, _, _ = parse_addon_lines(lines)
        assert equipped["head"] == "id=100"
        assert "id=999" not in equipped

    def test_last_class_overwrites_earlier(self):
        """If multiple class lines appear, the last one wins."""
        lines = ["paladin=First", "mage=Second", "head=id=100"]
        _, _, _, _, char_name, char_class = parse_addon_lines(lines)
        # The second class (mage) overwrites the first
        assert char_class == "mage"
        assert char_name == "Second"


class TestSlotConstants:
    """Test that slot and class constants are well-defined."""

    def test_all_expected_slots_present(self):
        expected = {
            "head", "neck", "shoulder", "back", "chest", "wrist",
            "hands", "waist", "legs", "feet", "finger1", "finger2",
            "trinket1", "trinket2", "main_hand", "off_hand",
        }
        assert set(SLOTS) == expected

    def test_all_expected_classes_present(self):
        expected = {
            "deathknight", "demonhunter", "druid", "evoker", "hunter",
            "mage", "monk", "paladin", "priest", "rogue", "shaman",
            "warlock", "warrior",
        }
        assert set(CLASSES) == expected

    def test_slots_count(self):
        assert len(SLOTS) == 16

    def test_classes_count(self):
        assert len(CLASSES) == 13
