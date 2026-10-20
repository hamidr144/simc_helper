#!/usr/bin/env python3
import json
import os
import re
from itertools import product

from src.core.addon_parser import parse_addon_lines


# Midnight enchant-group keys (MGE-1 catalog) -> the gear-slot keys the whole
# pipeline consumes (MGE-2 design contract §8.3). Configs that already use
# gear-slot keys pass through unchanged. profession_tool has no combat-gear
# slot: it stays backend-side seed data only and is filtered out here, so it
# never reaches /api/config.enchantments or combination generation.
ENCHANT_GROUP_TO_SLOT = {
    "helm": "head",
    "shoulders": "shoulder",
    "chest": "chest",
    "legs": "legs",
    "boots": "feet",
    "rings": "finger",
    "weapon": "main_hand",
    "profession_tool": None,
}


def map_enchant_groups(enchantments):
    """Rewrite Midnight enchant-group keys to gear-slot keys, dropping
    group-less entries (None targets). Unknown keys pass through as-is."""
    mapped = {}
    for group, entries in enchantments.items():
        slot = ENCHANT_GROUP_TO_SLOT.get(group, group)
        if slot is not None:
            mapped[slot] = entries
    return mapped


def load_config(config_path="config.json"):
    """Loads enchant and gem options from a JSON config file, mapping
    Midnight enchant-group keys to gear-slot keys at this single load edge
    (callers and /api/config only ever see gear-slot keys)."""
    default_config = {"enchantments": {}, "gems": {}, "max_concurrent_jobs": 4}
    if not os.path.exists(config_path):
        return default_config
    try:
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
        if isinstance(config.get("enchantments"), dict):
            config["enchantments"] = map_enchant_groups(config["enchantments"])
        return config
    except Exception as e:
        print(f"Error loading config: {e}")
        return default_config

def load_globals(globals_path="globals.simc"):
    """Loads global options from a .simc file."""
    if not os.path.exists(globals_path):
        return ""
    with open(globals_path, encoding='utf-8') as f:
        return f.read()

def parse_addon_file(file_path):
    """Parses the addon file to extract base profile and items from bags."""
    with open(file_path, encoding='utf-8') as f:
        return parse_addon_lines(f.readlines())

def apply_mod(gear_str, mod_type, mod_id):
    """Replaces or adds an enchant_id or gem_id to a gear string correctly."""
    if not mod_id: return gear_str
    
    # Ensure the base string has a leading comma if it starts with an ID part
    if gear_str.startswith("id=") or gear_str.startswith("bonus_id="):
        gear_str = "," + gear_str

    # Split the gear string by commas
    parts = gear_str.split(',')
    new_parts = []
    found = False
    
    for part in parts:
        if part.startswith(f"{mod_type}="):
            new_parts.append(f"{mod_type}={mod_id}")
            found = True
        else:
            new_parts.append(part)
            
    if not found:
        # Add it after the 'id=...' part
        for i, part in enumerate(new_parts):
            if part.startswith("id="):
                new_parts.insert(i + 1, f"{mod_type}={mod_id}")
                found = True # Mark as found so we don't try to add it again
                break
    
    if not found:
        # If no id= found, just append it
        new_parts.append(f"{mod_type}={mod_id}")
    
    res = ",".join(new_parts)
    if not res.startswith(',') and (res.startswith("id=") or res.startswith("bonus_id=")):
        res = "," + res
    return res


from src.core.upgrade_data import (
    ascension_for,
    ascension_result,
    get_season,
    is_ascension_eligible_slot,
    track_level as _season_track_level,
)


def is_voidforge_eligible_slot(slot, season=None):
    """Ascension (Voidforged/Venomforged) eligibility for a gear slot."""
    return is_ascension_eligible_slot(season or get_season(), slot)


def parse_item_level(gear_str):
    match = re.search(r"(?:^|,)ilevel=(\d+)(?:,|$)", gear_str or "")
    return int(match.group(1)) if match else None


def midnight_track_level(track, rank, season=None):
    """Return the Midnight item level for a gear track and 1-based rank."""
    if not track or rank in (None, ""):
        return None
    return _season_track_level(season or get_season(), track, rank)


def apply_item_level(gear_str, item_level, slot=None, voidforged=False, season=None):
    """Replaces or adds an ilevel= component to a SimC item string.

    ``voidforged`` on the manual item-level path only applies the legacy
    flat ascension bonus when the season defines one (Season 1 Voidforged
    +9); Season 2's Venomforged is track-dependent and handled by
    :func:`apply_gear_upgrade`.
    """
    season = season or get_season()
    if item_level in (None, ""):
        level = parse_item_level(gear_str) if voidforged else None
    else:
        try:
            level = int(item_level)
        except (TypeError, ValueError):
            return gear_str

    if level is None or level <= 0:
        return gear_str

    if voidforged and is_ascension_eligible_slot(season, slot):
        ascension = ascension_for(season)
        legacy_delta = ascension.get("legacy_bonus_ilvl")
        legacy_finals = set(ascension.get("legacy_final_ilvls") or [])
        if legacy_delta and level not in legacy_finals:
            level += legacy_delta

    return apply_mod(gear_str, "ilevel", level)


def apply_gear_upgrade(gear_str, upgrade, slot=None, voidforged=False, season=None):
    """Applies a Midnight track/rank upgrade by converting it to the matching ilevel.

    Ascension (Ascendant Voidforged/Venomforged) resolves to the season's
    absolute ascended ilvl for the track (hero/myth only, per game rules:
    ascension requires a fully upgraded Hero/Myth or max-quality crafted
    base).
    """
    season = season or get_season()
    if not isinstance(upgrade, dict):
        return apply_item_level(gear_str, None, slot=slot, voidforged=voidforged, season=season)
    # An explicit absolute item_level from the addon export's own
    # upgrade_levels comment (marked source='export') wins over the static
    # season ladder.  Wowhead-hydrated entries also carry item_level (the
    # item's *current* level), so they must keep using track/rank.
    level = None
    if upgrade.get("source") == "export":
        level = _coerce_item_level(upgrade.get("item_level"))
    if level is None:
        level = midnight_track_level(upgrade.get("track"), upgrade.get("rank"), season=season)
    if voidforged and level is not None and is_ascension_eligible_slot(season, slot):
        # Same crafted predicate as the UI (app.js isCraftedItem): a max-quality
        # crafted base ascends to the season's lower crafted_results ilvl.
        crafted = "crafted_stats=" in gear_str or "crafting_quality=" in gear_str
        ascended = ascension_result(season, upgrade.get("track"), crafted=crafted)
        if ascended is not None:
            level = ascended
    return apply_item_level(gear_str, level, slot=slot, voidforged=False, season=season)


def _coerce_item_level(value):
    """Absolute item level from an upgrade payload, or None if unusable."""
    if value in (None, ""):
        return None
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None
    return level if level > 0 else None

def generate_variations(item_list, slot_name, config, extra_sockets=None):
    """Generates all combinations of an item with its possible enchants and valid gems from config."""
    # Ensure each item in item_list has correct SimC formatting
    normalized_items = []
    for it in item_list:
        if it.startswith("id=") or it.startswith("bonus_id="):
            normalized_items.append("," + it)
        else:
            normalized_items.append(it)
    item_list = normalized_items
    # Get list of mod IDs for this slot, handling both simple lists and object lists
    def get_mod_ids(mod_dict, s):
        # Category could be a list (old) or a dict (new)
        # Use main_hand enchants for off_hand if off_hand is missing
        lookup_key = s
        if s == "off_hand" and s not in mod_dict and "main_hand" in mod_dict:
            lookup_key = "main_hand"
            
        mods = mod_dict.get(lookup_key, []) if isinstance(mod_dict, dict) else []
        if not mods: return []
        return [m["id"] if isinstance(m, dict) else m for m in mods]

    enchants = get_mod_ids(config.get("enchantments", {}), slot_name)
    
    # Handle categorized gems if present.
    # Meta gems are not normal socket gems, so never mix them into regular gear
    # variations. Standard gems are only valid for items that already have a
    # socket in the addon export, or for slots explicitly marked as having an
    # extra socket by the UI.
    gem_config = config.get("gems", {})
    gems = []
    extra_sockets = extra_sockets or {}

    categorized_gems = isinstance(gem_config, dict) and ("meta" in gem_config or "standard" in gem_config)
    if categorized_gems:
        gems = get_mod_ids(gem_config, "standard")
    else:
        # Fallback to legacy per-slot gem lists.
        gems = get_mod_ids(gem_config, slot_name)

    def item_accepts_standard_gems(item):
        if not gems:
            return False
        if not categorized_gems:
            return True
        if "gem_id=" in item:
            return True
        # Jewelry always has exactly one socket (t_fa0d755f §4): finger/neck
        # accept standard gems even when the export omits gem_id=.
        return bool(extra_sockets.get(slot_name)) or slot_name in ("finger", "neck")
    
    variations = []
    for item in item_list:
        current_gems = gems if item_accepts_standard_gems(item) else []

        if enchants and current_gems:
            # Must be a combination of both
            for eid in enchants:
                for gid in current_gems:
                    temp = apply_mod(item, "enchant_id", eid)
                    variations.append(apply_mod(temp, "gem_id", gid))
        elif enchants:
            # Only enchants
            for eid in enchants:
                variations.append(apply_mod(item, "enchant_id", eid))
        elif current_gems:
            # Only gems
            for gid in current_gems:
                variations.append(apply_mod(item, "gem_id", gid))
        else:
            # Fallback to as-is if no mods defined for this slot
            variations.append(item)
            
    return list(dict.fromkeys(variations))

def canonical_item(item):
    """Normalize SimC item fields so equivalent profiles compare equally."""
    fields = [field.strip() for field in str(item or "").lstrip(",").split(",") if field.strip()]
    return ",".join(sorted(fields))


def _combination_pools(selected_by_slot, config, equipped_gear, extra_sockets=None):
    """Per-slot variation pools + finger/trinket variation pools.

    Shared by ``build_combination_copies`` and ``count_combination_copies``
    (TG3-I) so the cheap pre-build count sees exactly the product the builder
    iterates.
    """
    group_slots = ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "main_hand", "off_hand"]
    choices = [
        generate_variations(selected_by_slot.get(slot) or [equipped_gear.get(slot, "")],
                            slot, config, extra_sockets=extra_sockets)
        for slot in group_slots
    ]
    finger_vars = generate_variations(selected_by_slot.get("finger") or [], "finger", config, extra_sockets=extra_sockets)
    trinket_vars = generate_variations(selected_by_slot.get("trinket") or [], "trinket", config, extra_sockets=extra_sockets)
    return choices, finger_vars, trinket_vars


def _pair_pool_count(n):
    """len(build's unordered pair list): C(n,2), or the single as-is pair when n < 2."""
    return n * (n - 1) // 2 if n >= 2 else 1


def count_combination_copies(selected_by_slot, config, equipped_gear, extra_sockets=None):
    """Pre-dedup iteration count of ``build_combination_copies`` without
    materializing any copy block (TG3-I, t_acfe75a9).

    The built (deduped) count is always <= this product, so rejecting when
    this exceeds the budget keeps the dispatch budget-safe.  Building first to
    count was what OOM-killed the master on over-cap products.
    """
    choices, finger_vars, trinket_vars = _combination_pools(
        selected_by_slot, config, equipped_gear, extra_sockets=extra_sockets)
    total = 1
    for pool in choices:
        total *= len(pool)
    return total * _pair_pool_count(len(finger_vars)) * _pair_pool_count(len(trinket_vars))


def build_combination_copies(selected_by_slot, config, equipped_gear, char_name,
                             extra_sockets=None, baseline_name=None):
    """Product of per-slot variation pools + unordered finger/trinket pairs.

    Shared Top-Gear algorithm (TG2-B, extracted verbatim from the CLI main):
    returns ``(copy_blocks, count)`` where each block is a SimC clone profile
    ``copy="<char>_Combo_<i>,<clone-target>"`` (sim_helper parses the first
    comma-field).  ``selected_by_slot`` is keyed by the grouped addon slots
    (head..off_hand single, finger, trinket); an empty group slot falls back to
    the equipped item so its enhancements still vary.  Blocks identical to the
    baseline actor or to an earlier block are skipped (honest-zero contract
    t_4485565b: zero real variations -> zero copies -> baseline-only file).
    ``baseline_name`` overrides the clone target (the CLI names its baseline
    ``<char>_Baseline``); the web path clones the plain character profile.
    """
    clone_target = baseline_name or char_name
    group_slots = ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "main_hand", "off_hand"]
    choices, finger_vars, trinket_vars = _combination_pools(
        selected_by_slot, config, equipped_gear, extra_sockets=extra_sockets)

    # shortcut: unordered C(n,2) pairs without self-pairing keep the shipped CLI
    # semantics verbatim (ruling E2); Raidbots' internal pair rule is UNVERIFIED (TGE-1 §2.7).
    finger_pairs = [(finger_vars[i], finger_vars[j]) for i in range(len(finger_vars)) for j in range(i+1, len(finger_vars))] if len(finger_vars)>=2 else [(finger_vars[0], "")] if len(finger_vars)==1 else [("", "")]
    trinket_pairs = [(trinket_vars[i], trinket_vars[j]) for i in range(len(trinket_vars)) for j in range(i+1, len(trinket_vars))] if len(trinket_vars)>=2 else [(trinket_vars[0], "")] if len(trinket_vars)==1 else [("", "")]

    baseline_map = {slot: canonical_item(item) for slot, item in equipped_gear.items() if item}
    seen = {tuple(sorted(baseline_map.items()))}
    copy_blocks = []
    for base_config, fingers, trinkets in product(product(*choices), finger_pairs, trinket_pairs):
        profile_map = dict(baseline_map)
        lines = []
        for slot, details in zip(group_slots, base_config):
            if not details: continue
            profile_map[slot] = canonical_item(details)
            lines.append(f"{slot}={details}\n")
        for slot, details in (("finger1", fingers[0]), ("finger2", fingers[1]), ("trinket1", trinkets[0]), ("trinket2", trinkets[1])):
            if not details: continue
            profile_map[slot] = canonical_item(details)
            lines.append(f"{slot}={details}\n")
        signature = tuple(sorted(profile_map.items()))
        if signature in seen: continue
        seen.add(signature)
        copy_blocks.append(f'copy="{char_name}_Combo_{len(copy_blocks) + 1},{clone_target}"\n' + "".join(lines) + "\n")
    return copy_blocks, len(copy_blocks)


def select_items_interactive(items_by_slot, item_names, equipped_gear):
    """Prompts user to select which items to include for each slot."""
    selected_items = {}
    print("\n--- Gear Selection ---")
    print("For each slot, enter the numbers of the items you want to include (e.g., '1,3').")
    print("The equipped item(s) are marked with [E]. Press Enter to keep default (Equipped).")

    for slot in list(items_by_slot.keys()):
        items = items_by_slot[slot]
        if len(items) <= 1: selected_items[slot] = items; continue

        print(f"\nSlot: {slot.upper()}")
        equipped_in_slot = [equipped_gear.get("finger1"), equipped_gear.get("finger2")] if slot == "finger" else [equipped_gear.get("trinket1"), equipped_gear.get("trinket2")] if slot == "trinket" else [equipped_gear.get(slot)]
        for i, item in enumerate(items, 1):
            prefix = "[E] " if item in equipped_in_slot else "    "
            print(f"  {i}) {prefix}{item_names.get(item, 'Unknown Item')}")

        while True:
            choice = input(f"Select items for {slot} (default: equipped): ").strip()
            if not choice:
                selected_items[slot] = [it for it in items if it in equipped_in_slot] or [items[0]]
                break
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(",") if x.strip()]
                if all(0 <= idx < len(items) for idx in indices):
                    selected_items[slot] = [items[idx] for idx in indices]
                    break
                else: print("Error: Invalid number.")
            except ValueError: print("Error: Please enter numbers separated by commas.")
    return selected_items

def main():
    addon_file, output_file, config_file, globals_file = "char_simc_addon.txt", "generated_sim.simc", "config.json", "globals.simc"

    if not os.path.exists(addon_file): print(f"Error: {addon_file} not found."); return

    config = load_config(config_file)
    globals_data = load_globals(globals_file)
    base_profile, equipped, items_by_slot, item_names, char_name, char_class, _item_upgrades = parse_addon_file(addon_file)
    
    print(f"Loaded character: {char_name} ({char_class})")
    selected_items_by_slot = select_items_interactive(items_by_slot, item_names, equipped)
    
    copy_blocks, count = build_combination_copies(
        selected_items_by_slot, config, equipped, char_name,
        baseline_name=f"{char_name}_Baseline")

    print(f"\nCombinations: {count:,}")
    if count > 100000 and input("WARNING: High combination count. Continue? (y/n): ").lower() != 'y': return

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Generated Top Gear Sim\n")
        f.write(f"{char_class}=\"{char_name}_Baseline\"\n")
        f.write(base_profile + "\n")
        f.write(globals_data + "\n")
        for slot in equipped: f.write(f"{slot}={equipped[slot]}\n")
        f.write("\n")
        f.writelines(copy_blocks)

    print(f"Success! Created {output_file} with {count} combinations.")

if __name__ == "__main__": main()
