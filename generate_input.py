#!/usr/bin/env python3
import sys
import os
import re
import json
from itertools import product

def load_config(config_path="config.json"):
    """Loads enchant and gem options from a JSON config file."""
    default_config = {"enchantments": {}, "gems": {}}
    if not os.path.exists(config_path):
        return default_config
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return default_config

def load_globals(globals_path="globals.simc"):
    """Loads global options from a .simc file."""
    if not os.path.exists(globals_path):
        return ""
    with open(globals_path, 'r', encoding='utf-8') as f:
        return f.read()

def parse_addon_file(file_path):
    """Parses the addon file to extract base profile and items from bags."""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    base_profile = []
    items_by_slot = {}
    item_names = {}
    slots = ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "finger1", "finger2", "trinket1", "trinket2", "main_hand", "off_hand"]
    
    in_bags = False
    equipped_gear = {}
    char_name = "Unknown"
    char_class = "Unknown"
    current_name_comment = ""
    classes = {"deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", "monk", "paladin", "priest", "rogue", "shaman", "warlock", "warrior"}

    for line in lines:
        line_strip = line.strip()
        if line_strip.startswith("# ") and not re.match(r"^#\s+\w+=", line_strip):
            current_name_comment = line_strip[2:]
        
        name_match = re.match(r"^(\w+)=[\"']?([^\"'\s,]+)[\"']?$", line_strip)
        if name_match:
            key, val = name_match.groups()
            if key.lower() in classes:
                char_class, char_name = key, val
                continue
        
        if line_strip == "### Gear from Bags": in_bags = True; continue
        if line_strip == "### Additional Character Info": break

        if not in_bags:
            match = re.match(r"^(\w+)=(.+)$", line_strip)
            if match:
                slot, details = match.groups()
                if slot in slots:
                    equipped_gear[slot] = details
                    norm_slot = "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot
                    if norm_slot not in items_by_slot: items_by_slot[norm_slot] = []
                    if details not in items_by_slot[norm_slot]:
                        items_by_slot[norm_slot].append(details)
                        item_names[details] = current_name_comment
            if not any(line_strip.startswith(s+"=") for s in slots):
                base_profile.append(line)
        else:
            match = re.match(r"^#\s+(\w+)=(.+)$", line_strip)
            if match:
                slot, details = match.groups()
                norm_slot = "finger" if slot.startswith("finger") else "trinket" if slot.startswith("trinket") else slot
                if norm_slot in items_by_slot or norm_slot in slots:
                    if norm_slot not in items_by_slot: items_by_slot[norm_slot] = []
                    if details not in items_by_slot[norm_slot]:
                        items_by_slot[norm_slot].append(details)
                        item_names[details] = current_name_comment

    return "".join(base_profile), equipped_gear, items_by_slot, item_names, char_name, char_class

def apply_mod(gear_str, mod_type, mod_id):
    """Replaces or adds an enchant_id or gem_id to a gear string correctly."""
    if not mod_id: return gear_str
    
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
                break
    
    return ",".join(new_parts)

def generate_variations(item_list, slot_name, config):
    """Generates all combinations of an item with its possible enchants and gems from config.
    Always ensures both are applied if both are defined."""
    enchants = config.get("enchantments", {}).get(slot_name, [])
    gems = config.get("gems", {}).get(slot_name, [])
    
    variations = []
    for item in item_list:
        if enchants and gems:
            # Must be a combination of both
            for eid in enchants:
                for gid in gems:
                    temp = apply_mod(item, "enchant_id", eid)
                    variations.append(apply_mod(temp, "gem_id", gid))
        elif enchants:
            # Only enchants
            for eid in enchants:
                variations.append(apply_mod(item, "enchant_id", eid))
        elif gems:
            # Only gems
            for gid in gems:
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
