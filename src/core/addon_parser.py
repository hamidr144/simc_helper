import re
from typing import Dict, List, Tuple

SLOTS = [
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist",
    "legs", "feet", "finger1", "finger2", "trinket1", "trinket2",
    "main_hand", "off_hand",
]
CLASSES = {
    "deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", "monk",
    "paladin", "priest", "rogue", "shaman", "warlock", "warrior",
}


def parse_addon_lines(lines: List[str]) -> Tuple[str, Dict[str, str], Dict[str, List[str]], Dict[str, str], str, str]:
    base_profile = []
    items_by_slot: Dict[str, List[str]] = {}
    item_names: Dict[str, str] = {}
    equipped_gear: Dict[str, str] = {}
    char_name = "Unknown"
    char_class = "Unknown"
    current_name_comment = ""
    in_bags = False
    valid_slots = set(SLOTS) | {"finger", "trinket"}

    def preserve_line(raw_line: str) -> str:
        return raw_line if raw_line.endswith("\n") else raw_line + "\n"

    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        if line_strip.startswith("# ") and not re.match(r"^#\s+\w+=", line_strip):
            current_name_comment = line_strip[2:]

        name_match = re.match(r"^(\w+)=[\"']?([^\"'\s,]+)[\"']?$", line_strip)
        if name_match:
            key, val = name_match.groups()
            if key.lower() in CLASSES:
                char_class, char_name = key, val
                base_profile.append(preserve_line(line))
                continue

        if line_strip == "### Gear from Bags":
            in_bags = True
            continue
        if line_strip == "### Additional Character Info":
            break

        if not in_bags:
            match = re.match(r"^(\w+)=(.+)$", line_strip)
            if match:
                slot, details = match.groups()
                if slot in SLOTS:
                    equipped_gear[slot] = details
                    norm_slot = "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot
                    items_by_slot.setdefault(norm_slot, [])
                    if details not in items_by_slot[norm_slot]:
                        items_by_slot[norm_slot].append(details)
                        item_names[details] = current_name_comment
            if not any(line_strip.startswith(s + "=") for s in SLOTS):
                base_profile.append(preserve_line(line))
        else:
            match = re.match(r"^#\s+(\w+)=(.+)$", line_strip)
            if match:
                slot, details = match.groups()
                norm_slot = "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot
                if norm_slot in valid_slots:
                    items_by_slot.setdefault(norm_slot, [])
                    if details not in items_by_slot[norm_slot]:
                        items_by_slot[norm_slot].append(details)
                        item_names[details] = current_name_comment

    return "".join(base_profile), equipped_gear, items_by_slot, item_names, char_name, char_class
