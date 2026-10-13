import re
from typing import Any, Dict, List, Optional, Tuple

SLOTS = [
    "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist",
    "legs", "feet", "finger1", "finger2", "trinket1", "trinket2",
    "main_hand", "off_hand",
]
CLASSES = {
    "deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", "monk",
    "paladin", "priest", "rogue", "shaman", "warlock", "warrior",
}

# Addon ``# upgrade_levels=`` comment grammar, verified against the real
# simc-addon source (github.com/simulationcraft/simc-addon, core.lua master,
# getUpgradeComment/formatCosts, fetched 2026-10-13).  The addon emits the
# comment right after the item-name comment and before the item line, only
# in ``/simc debug`` output while an upgrade vendor is open:
#
#   upgrade_levels=<levelStr>[/<levelStr>...]
#   <levelStr> = upgradeLevel:itemLevelIncrement:currencyCosts:itemCosts
#   <currencyCosts> = "" | "c#<currencyId>#<count>#<discounted01>"[,...]
#   <itemCosts>     = "" | "i#<itemId>#<count>#<discounted01>"[,...]
#
# Increments are relative to the item's *current* ilvl, and the addon
# excludes the item's own current upgrade level from the list.
_UPGRADE_COMMENT_RE = re.compile(r"^#\s*upgrade_levels=(.*)$")
_UPGRADE_COST_RE = re.compile(r"^([ci])#(\d+)#(\d+)#([01])$")


def parse_upgrade_levels(value: str) -> Optional[Dict[str, Any]]:
    """Parse the value of an addon ``upgrade_levels=`` comment.

    Returns ``{"levels": [...]}`` with one entry per upgrade level
    (``upgrade_level``, ``ilvl_increment``, ``currency_costs``,
    ``item_costs``), or ``None`` when nothing valid can be salvaged.
    Malformed individual levels are skipped; parsing never raises.
    """
    levels: List[Dict[str, Any]] = []
    for segment in str(value or "").split("/"):
        if not segment:
            continue
        parts = segment.split(":")
        if len(parts) != 4:
            continue
        try:
            upgrade_level = int(parts[0])
            ilvl_increment = int(parts[1])
        except ValueError:
            continue
        currency_costs: List[Dict[str, Any]] = []
        item_costs: List[Dict[str, Any]] = []
        malformed = False
        for kind, raw, bucket in (
            ("c", parts[2], currency_costs),
            ("i", parts[3], item_costs),
        ):
            for cost_str in filter(None, raw.split(",")):
                match = _UPGRADE_COST_RE.match(cost_str)
                if not match or match.group(1) != kind:
                    malformed = True
                    break
                bucket.append({
                    "id": int(match.group(2)),
                    "count": int(match.group(3)),
                    "discounted": match.group(4) == "1",
                })
            if malformed:
                break
        if malformed:
            continue
        levels.append({
            "upgrade_level": upgrade_level,
            "ilvl_increment": ilvl_increment,
            "currency_costs": currency_costs,
            "item_costs": item_costs,
        })
    return {"levels": levels} if levels else None


def parse_addon_lines(lines: List[str]) -> Tuple[str, Dict[str, str], Dict[str, List[str]], Dict[str, str], str, str, Dict[str, Dict[str, Any]]]:
    base_profile = []
    items_by_slot: Dict[str, List[str]] = {}
    item_names: Dict[str, str] = {}
    equipped_gear: Dict[str, str] = {}
    item_upgrades: Dict[str, Dict[str, Any]] = {}
    char_name = "Unknown"
    char_class = "Unknown"
    current_name_comment = ""
    current_upgrade: Optional[Dict[str, Any]] = None
    in_bags = False
    valid_slots = set(SLOTS) | {"finger", "trinket"}

    def preserve_line(raw_line: str) -> str:
        return raw_line if raw_line.endswith("\n") else raw_line + "\n"

    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        upgrade_match = _UPGRADE_COMMENT_RE.match(line_strip)
        if upgrade_match:
            # Attach to the item line that follows; never a name comment,
            # never part of the base profile.
            current_upgrade = parse_upgrade_levels(upgrade_match.group(1))
            continue
        if line_strip.startswith("# ") and not re.match(r"^#\s+\w+=", line_strip):
            current_name_comment = line_strip[2:]
            current_upgrade = None

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
                    if current_upgrade:
                        item_upgrades.setdefault(details, current_upgrade)
                current_upgrade = None
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
                    if current_upgrade:
                        item_upgrades.setdefault(details, current_upgrade)
                current_upgrade = None

    return "".join(base_profile), equipped_gear, items_by_slot, item_names, char_name, char_class, item_upgrades
