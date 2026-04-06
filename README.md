# Simcraft Helper Suite

A collection of Python scripts to automate SimulationCraft (SimC) workflows, from generating item combinations to running multi-stage simulations with real-time progress tracking.

## Scripts

### 1. `generate_input.py`
An interactive script to generate a `.simc` input file by combining your character's base profile with selected gear combinations, enchantments, and gems.

#### Features
- **Interactive Gear Selection:** Automatically parses your SimC addon export (`char_simc_addon.txt`) and lets you choose which items from your bags to include for each slot.
- **Automated Enchants/Gems:** Applies multiple enchantment and gem variations to each item based on your `config.json`.
- **Baseline Comparison:** Automatically creates a "Baseline" profile for easy comparison.

#### Usage
1.  Place your SimC addon export in the project folder as `char_simc_addon.txt`.
2.  (Optional) Edit `config.json` to define which `enchant_id` and `gem_id` values to test for each slot.
3.  Run the script:
    ```bash
    python3 generate_input.py
    ```
4.  Follow the interactive prompts in the console to select gear for each slot.
5.  The script will output `generated_sim.simc`.

---

### 2. `sim_helper.py`
A robust wrapper for running SimulationCraft with real-time progress updates and automated report management.

#### Features
- **3-Stage Refinement:** (Optional) Can perform multi-stage simulations to filter out poor combinations early, saving CPU time.
- **Real-time Progress Bar:** Captures SimC's interactive output to show a progress bar in your terminal.
- **Timestamped Reports:** Automatically generates and organizes HTML reports (e.g., `report_20260406_120000.html`).
- **Temporary File Management:** Stores all logs and intermediate files in `/tmp/simc_<timestamp>/` to keep your workspace clean.

#### Usage
Run the script providing the path to your `simc` executable and your input file:
```bash
./sim_helper.py simc_path=/path/to/simc input_file=generated_sim.simc
```

## Configuration (`config.json`)
The `config.json` file allows you to specify lists of IDs to test for each slot. 

Example:
```json
{
    "enchantments": {
        "head": [7991, 8015],
        "chest": [7956, 7957]
    },
    "gems": {
        "neck": [240890, 240892]
    }
}
```

## Requirements
- Python 3.6+
- SimulationCraft (installed locally)
- A SimC addon export from World of Warcraft.
