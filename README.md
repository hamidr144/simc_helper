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
A robust wrapper for running SimulationCraft with real-time progress updates, OOM-safe batching, and automated report management.

#### Features
- **3-Stage Refinement:** Performs multi-stage simulations (100 -> 2000 -> Final iterations) to quickly filter out poor combinations, saving massive CPU time.
- **OOM-Safe Batching:** Automatically splits large combo datasets (>400 profiles) into memory-safe batches to prevent SimulationCraft from crashing your system. Uses global sorting to guarantee the absolute top performers are kept across all batches.
- **Real-time Progress & Timing:** Captures SimC's interactive output to show a progress bar in your terminal and calculates total execution time upon completion.
- **Organized Reports:** Automatically generates and saves HTML reports to a dedicated `/tmp/simc_reports/` directory.
- **Auto-Serve & View:** Start a local HTTP server in the background and instantly open the final HTML report in your browser when the simulation completes.

#### Usage
Run the script providing the path to your `simc` executable and your input file:
```bash
./sim_helper.py simc_path=/path/to/simc input_file=generated_sim.simc [stage1_percent_best=25%] [stage2_percent_best=25%] [start_server=1]
```

**Arguments:**
- `simc_path`: Path to the SimulationCraft executable.
- `input_file`: Path to the `.simc` file containing profiles.
- `stage1_percent_best`: % or number of profiles to keep after Stage 1 (Default: Dynamic).
- `stage2_percent_best`: % or number of profiles to keep after Stage 2 (Default: Dynamic).
- `start_server`: Set to `1` to automatically start a local HTTP server and open the final report.

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
