#!/usr/bin/env python3
"""
Simcraft Automation Script

This script automates a 3-stage workflow for SimulationCraft:
1. Stage 1: Fast Filtering (100 iterations) - Broadly identifies top performers.
2. Stage 2: Refinement (2000 iterations) - Narrows down the results using higher precision.
3. Stage 3: Final Selection - Produces the final high-precision report.

The script automatically detects the base character profile and ensures it is 
included at the top of the input for every stage.

Usage:
    ./sim_helper simc_path=/path/to/simc input_file=your_input.simc [stage1_percent_best=25%] [stage2_percent_best=25%]

Arguments:
    simc_path:           Path to the SimulationCraft executable.
    input_file:          Path to the base .simc file containing 'copy=' profiles.
    stage1_percent_best: % or number of performers to keep after Stage 1 (default: 25%).
    stage2_percent_best: % or number of performers to keep after Stage 2 (default: 25%).

Outputs:
    - Console: Shows real-time simulation progress.
    - Reports: Saves a timestamped HTML report (e.g., report_20260405_120000.html).
    - Temps:   Stores logs and intermediate .simc files in /tmp/simc_<timestamp>/.
"""
import sys
import os
import re
import subprocess
import datetime
import pty
import select
import math

def get_character_name(input_file):
    """
    Parses the input .simc file to find the primary character's name.
    Looks for the 'name=' line, which defines the base actor.
    """
    try:
        with open(input_file, "r", encoding='utf-8', errors='replace') as f:
            for line in f:
                match = re.match(r"^name=[\"']?([^\"'\s,]+)[\"']?", line)
                if match:
                    return match.group(1).strip()
    except Exception as e:
        print(f"Warning: Could not extract character name from {input_file}: {e}")
    return None

def count_combos(input_file, current_name=None):
    """
    Iterates through the input file to count how many 'copy=' profiles exist.
    The current character profile is excluded from this count as it's the baseline.
    """
    count = 0
    try:
        with open(input_file, "r", encoding='utf-8', errors='replace') as f:
            for line in f:
                match = re.match(r"^copy=[\"']?([^,\"']+)[^\"']*[\"']?", line)
                if match:
                    name = match.group(1).strip()
                    if name != current_name:
                        count += 1
    except Exception as e:
        print(f"Error counting combos: {e}")
    return count

def get_default_filter(stage, count):
    """
    Determines an optimal retention percentage based on the number of combinations.
    Uses stricter filtering for larger datasets to maintain performance.
    """
    if stage == 1:
        if count <= 100: return "25%"
        if count <= 1000: return "15%"
        if count <= 10000: return "10%"
        if count <= 100000: return "5%"
        return "2%"
    else:  # Stage 2
        if count <= 50: return "50%"
        if count <= 200: return "20%"
        if count <= 1000: return "10%"
        return "5%"

def run_simc(simc_path, input_file, extra_args, output_log, html_report=None):
    """
    Executes SimulationCraft via a pseudo-terminal (PTY) to capture real-time 
    interactive progress bars while logging the full output to a file.
    """
    cmd = [simc_path, input_file] + extra_args.split()
    if html_report:
        cmd.append(f"html={html_report}")
    
    print(f"Running: {' '.join(cmd)}")
    
    master_fd, slave_fd = pty.openpty()
    # Use binary mode (default for Popen when text=False) and no pipes
    process = subprocess.Popen(cmd, stdout=slave_fd, stderr=slave_fd, close_fds=True)
    os.close(slave_fd)
    
    with open(output_log, "wb") as f_log:
        buffer = b""
        while True:
            # Wait for data or process exit
            r, _, _ = select.select([master_fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    
                    f_log.write(data)
                    f_log.flush()
                    buffer += data
                    
                    # Process lines for progress updates
                    while b"\r" in buffer or b"\n" in buffer:
                        r_idx = buffer.find(b"\r")
                        n_idx = buffer.find(b"\n")
                        
                        if r_idx != -1 and (n_idx == -1 or r_idx < n_idx):
                            line_bytes = buffer[:r_idx]
                            buffer = buffer[r_idx+1:]
                        else:
                            line_bytes = buffer[:n_idx]
                            buffer = buffer[n_idx+1:]
                            
                        try:
                            line = line_bytes.decode('utf-8', errors='replace').strip()
                            
                            # Extract specific progress pattern if present
                            # Targets: 
                            # - Combo 401 401/961 [===================>] 100/100
                            # - Hamidriel 1/961 [===================>] 100/100
                            # Regex matches: Name (optional index) progress/total [bar] iterations/total
                            progress_match = re.search(r"(\S+\s+(?:\d+\s+)?\d+/\d+\s+\[.*?\]\s+\d+/\d+)", line)
                            
                            if progress_match:
                                print(f"\r{progress_match.group(1)}", end="", flush=True)
                            elif "Progress:" in line:
                                print(f"\r{line}", end="", flush=True)
                        except:
                            pass
                except OSError:
                    # EIO is common when the slave side of a PTY closes
                    break
            
            # If process is done, try one last read then exit
            if process.poll() is not None:
                # Final check for remaining data
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if not r:
                    break
                
        process.wait()
        print() # New line after progress finishes
    
    os.close(master_fd)
    return process.returncode

def filter_best(log_path, filter_arg, current_name=None):
    """
    Parses a SimulationCraft log file to extract the DPS ranking.
    Returns the top-performing 'copy=' profile names based on the filter_arg
    (percentage or absolute number), excluding the 'current' character and 'Raid'.
    """
    if not os.path.exists(log_path):
        print(f"Error: Log file {log_path} not found.")
        return []

    combos_only = []
    ranking_started = False

    # Stream the file line-by-line to handle massive logs
    with open(log_path, "r", encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not ranking_started:
                if line.startswith("DPS Ranking:"):
                    ranking_started = True
                continue
            
            if not line or line.startswith("HPS Ranking:"):
                break
            
            # Match line like: 86173  33.7%  Combo 3
            match = re.match(r"^\d+\s+[\d.]+%?\s+(.+)$", line)
            if match:
                name = match.group(1).strip()
                if name != "Raid" and name != current_name:
                    combos_only.append(name)

    # Determine how many combos to take
    if not combos_only:
        return []

    if filter_arg.endswith("%"):
        percentage = float(filter_arg.replace("%", "")) / 100
        target_n = max(1, math.ceil(len(combos_only) * percentage))
    else:
        target_n = int(filter_arg)

    return combos_only[:target_n]

def prepare_stage(base_simc, combos, output_simc, extra_params, current_name=None):
    """
    Generates a new .simc input file for the next simulation stage.
    Streams the base file to extract only the needed profiles (current + survivors)
    and preserves global configuration settings.
    """
    target_names = set(combos)
    if current_name:
        target_names.add(current_name)
    
    found_profiles = {}
    header = ""
    global_settings = []
    
    class_keywords = {
        "head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet",
        "finger1", "finger2", "trinket1", "trinket2", "main_hand", "off_hand", "talents", "name",
        "race", "level", "role", "spec",
        "paladin", "warrior", "deathknight", "priest", "shaman", "mage", "warlock", 
        "monk", "druid", "rogue", "hunter", "evoker", "demonhunter"
    }

    # Pass 1: Stream and extract only what we need
    with open(base_simc, "r", encoding='utf-8', errors='replace') as f:
        current_profile_name = None
        current_profile_content = []
        in_header = True
        
        for line in f:
            copy_match = re.match(r"^copy=[\"']?([^,\"']+)[^\"']*[\"']?", line)
            if copy_match:
                in_header = False
                # Save previous profile if it was a target
                if current_profile_name and current_profile_name in target_names:
                    found_profiles[current_profile_name] = "".join(current_profile_content)
                
                # Extract first part of comma-separated names
                full_name = copy_match.group(1).strip()
                current_profile_name = full_name.split(',')[0].strip()
                current_profile_content = [line]
            elif in_header:
                # Add active=0 to the base actor definition in the header to avoid name conflicts
                if line.strip().startswith("name=") and current_name and current_name in line:
                    header += line
                    header += "active=0\n"
                else:
                    header += line
                
                # Check for global settings in header
                line_strip = line.strip()
                if "=" in line_strip and not any(k+"=" in line_strip for k in class_keywords):
                    global_settings.append(line_strip)
            elif current_profile_name:
                current_profile_content.append(line)
        
        # Save last profile
        if current_profile_name and current_profile_name in target_names:
            found_profiles[current_profile_name] = "".join(current_profile_content)

    # Pass 2: Write output
    with open(output_simc, "w", encoding='utf-8') as f:
        f.write(header + "\n" + extra_params + "\n\n")
        
        # 1. Current profile first
        if current_name in found_profiles:
            f.write(f"# Current Character Profile\n{found_profiles[current_name]}\n")
        
        # 2. Selected combos in order
        for name in combos:
            if name in found_profiles and name != current_name:
                f.write(found_profiles[name] + "\n")
        
        if global_settings:
            f.write("\n# Global Settings extracted from base file\n" + "\n".join(global_settings) + "\n")

    total_count = (1 if current_name in found_profiles else 0) + len([c for c in combos if c in found_profiles and c != current_name])
    print(f"Created {output_simc} with {total_count} profiles.")

def main():
    """
    Orchestrates the 3-stage workflow.
    Handles argument parsing, dynamic filtering, and stage execution.
    """
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)

    args = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            args[key] = value

    simc_path = args.get("simc_path")
    input_file = args.get("input_file")
    
    if not simc_path or not input_file:
        print("Usage: ./sim_helper simc_path=/path/to/simc input_file=/path/to/input [stage1_percent_best=...] [stage2_percent_best=...]")
        print("Use -h or --help for more information.")
        sys.exit(1)
    
    char_name = get_character_name(input_file)
    print(f"Detected character name: {char_name}")
    
    initial_combo_count = count_combos(input_file, current_name=char_name)
    print(f"Found {initial_combo_count} combinations.")

    s1_filter = args.get("stage1_percent_best")
    if not s1_filter:
        s1_filter = get_default_filter(1, initial_combo_count)
        print(f"Using dynamic default for Stage 1: {s1_filter}")

    s2_filter = args.get("stage2_percent_best")
    # s2_filter will be determined after Stage 1 results are known if not provided
    
    start_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_dir = f"/tmp/simc_{start_time}"
    os.makedirs(tmp_dir, exist_ok=True)
    
    report_name = f"report_{start_time}.html"
    
    # Stage 1: Fast Filtering
    print(f"\n--- STAGE 1: Fast Filtering (iterations=100) using {s1_filter} ---")
    stage1_log = os.path.join(tmp_dir, "stage1.log")
    run_simc(simc_path, input_file, "iterations=100", stage1_log)
    top_combos_s1 = filter_best(stage1_log, s1_filter, current_name=char_name)
    
    if not top_combos_s1:
        print("Error: No combos found to refine after Stage 1. Stopping.")
        sys.exit(1)
    
    if not s2_filter:
        s2_filter = get_default_filter(2, len(top_combos_s1))
        print(f"Using dynamic default for Stage 2: {s2_filter}")

    stage2_simc = os.path.join(tmp_dir, "stage2.simc")
    prepare_stage(input_file, top_combos_s1, stage2_simc, "iterations=2000", current_name=char_name)

    # Stage 2: Refinement
    print(f"\n--- STAGE 2: Refinement (iterations=2000) using {s2_filter} ---")
    stage2_log = os.path.join(tmp_dir, "stage2.log")
    run_simc(simc_path, stage2_simc, "iterations=2000", stage2_log)
    top_combos_s2 = filter_best(stage2_log, s2_filter, current_name=char_name)
    
    if not top_combos_s2:
        print("Error: No combos found to refine after Stage 2. Stopping.")
        sys.exit(1)
    
    stage3_simc = os.path.join(tmp_dir, "stage3.simc")
    prepare_stage(input_file, top_combos_s2, stage3_simc, "", current_name=char_name)

    # Stage 3: Final Selection
    print("\n--- STAGE 3: Final Selection ---")
    stage3_log = os.path.join(tmp_dir, "stage3.log")
    run_simc(simc_path, stage3_simc, "", stage3_log, html_report=report_name)
    
    print(f"\nSimcraft Helper complete! Results in {report_name}")
    print(f"Temporary files are in {tmp_dir}")

if __name__ == "__main__":
    main()
