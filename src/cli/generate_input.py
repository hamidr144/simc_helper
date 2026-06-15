#!/usr/bin/env python3
import json
import os
import re
from itertools import product

from src.core.addon_parser import parse_addon_lines


def load_config(config_path="config.json"):
    """Loads enchant and gem options from a JSON config file."""
    default_config = {"enchantments": {}, "gems": {}, "max_concurrent_jobs": 4}
    if not os.path.exists(config_path):
        return default_config
    try:
        with open(config_path, encoding='utf-8') as f:
            return json.load(f)
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


VOIDFORGE_BONUS_ILVL = 9
VOIDFORGE_FINAL_ILVLS = {285, 298}
VOIDFORGE_ELIGIBLE_SLOTS = {"main_hand", "off_hand", "trinket", "trinket1", "trinket2"}

MIDNIGHT_UPGRADE_TRACKS = {
    "adventurer": [220, 224, 227, 230, 233, 237],
    "veteran": [233, 237, 240, 243, 246, 250],
    "champion": [246, 250, 253, 256, 259, 263],
    "hero": [259, 263, 266, 269, 272, 276],
    "myth": [272, 276, 279, 282, 285, 289],
}


def is_voidforge_eligible_slot(slot):
    return slot in VOIDFORGE_ELIGIBLE_SLOTS


def parse_item_level(gear_str):
    match = re.search(r"(?:^|,)ilevel=(\d+)(?:,|$)", gear_str or "")
    return int(match.group(1)) if match else None


def midnight_track_level(track, rank):
    """Return the Midnight item level for a gear track and 1-based rank."""
    if not track or rank in (None, ""):
        return None
    levels = MIDNIGHT_UPGRADE_TRACKS.get(str(track).lower())
    if not levels:
        return None
    try:
        rank_int = int(rank)
    except (TypeError, ValueError):
        return None
    if rank_int < 1 or rank_int > len(levels):
        return None
    return levels[rank_int - 1]


def apply_item_level(gear_str, item_level, slot=None, voidforged=False):
    """Replaces or adds an ilevel= component to a SimC item string."""
    if item_level in (None, ""):
        level = parse_item_level(gear_str) if voidforged else None
    else:
        try:
            level = int(item_level)
        except (TypeError, ValueError):
            return gear_str

    if level is None or level <= 0:
        return gear_str

    if voidforged and is_voidforge_eligible_slot(slot) and level not in VOIDFORGE_FINAL_ILVLS:
        level += VOIDFORGE_BONUS_ILVL

    return apply_mod(gear_str, "ilevel", level)


def apply_gear_upgrade(gear_str, upgrade, slot=None, voidforged=False):
    """Applies a Midnight track/rank upgrade by converting it to the matching ilevel."""
    if not isinstance(upgrade, dict):
        return apply_item_level(gear_str, None, slot=slot, voidforged=voidforged)
    level = midnight_track_level(upgrade.get("track"), upgrade.get("rank"))
    return apply_item_level(gear_str, level, slot=slot, voidforged=voidforged)

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
        return bool(extra_sockets.get(slot_name))
    
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
    base_profile, equipped, items_by_slot, item_names, char_name, char_class = parse_addon_file(addon_file)
    
    print(f"Loaded character: {char_name} ({char_class})")
    selected_items_by_slot = select_items_interactive(items_by_slot, item_names, equipped)
    
    choices = []
    group_slots = ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "main_hand", "off_hand"]
    for slot in group_slots:
        items = selected_items_by_slot.get(slot, [equipped.get(slot, "")])
        choices.append(generate_variations(items, slot, config))

    finger_vars = generate_variations(selected_items_by_slot.get("finger", []), "finger", config)
    trinket_vars = generate_variations(selected_items_by_slot.get("trinket", []), "trinket", config)

    # Combinations calculation
    f_count = max(1, (len(finger_vars)*(len(finger_vars)-1))//2 if len(finger_vars)>=2 else len(finger_vars))
    t_count = max(1, (len(trinket_vars)*(len(trinket_vars)-1))//2 if len(trinket_vars)>=2 else len(trinket_vars))
    total_est = 1
    for c in choices: total_est *= len(c)
    total_est *= f_count * t_count
    
    print(f"\nEstimated combinations: {total_est:,}")
    if total_est > 100000 and input("WARNING: High combination count. Continue? (y/n): ").lower() != 'y': return

    finger_pairs = [(finger_vars[i], finger_vars[j]) for i in range(len(finger_vars)) for j in range(i+1, len(finger_vars))] if len(finger_vars)>=2 else [(finger_vars[0], "")] if len(finger_vars)==1 else [("", "")]
    trinket_pairs = [(trinket_vars[i], trinket_vars[j]) for i in range(len(trinket_vars)) for j in range(i+1, len(trinket_vars))] if len(trinket_vars)>=2 else [(trinket_vars[0], "")] if len(trinket_vars)==1 else [("", "")]

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Generated Top Gear Sim\n")
        f.write(f"{char_class}=\"{char_name}_Baseline\"\n")
        f.write(base_profile + "\n")
        f.write(globals_data + "\n")
        for slot in equipped: f.write(f"{slot}={equipped[slot]}\n")
        f.write("\n")

        for i, (base_config, fingers, trinkets) in enumerate(product(product(*choices), finger_pairs, trinket_pairs), 1):
            f.write(f"copy=\"Combo_{i},{char_name}_Baseline\"\n")
            for slot, details in zip(group_slots, base_config):
                if details: f.write(f"{slot}={details}\n")
            if fingers[0]: f.write(f"finger1={fingers[0]}\n")
            if fingers[1]: f.write(f"finger2={fingers[1]}\n")
            if trinkets[0]: f.write(f"trinket1={trinkets[0]}\n")
            if trinkets[1]: f.write(f"trinket2={trinkets[1]}\n\n")

    print(f"Success! Created {output_file} with {total_est} combinations.")

if __name__ == "__main__": main()
