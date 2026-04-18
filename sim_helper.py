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
    ./sim_helper simc_path=/path/to/simc input_file=your_input.simc [stage1_percent_best=25%] [stage2_percent_best=25%] [start_server=1]

Arguments:
    simc_path:           Path to the SimulationCraft executable.
    input_file:          Path to the base .simc file containing 'copy=' profiles.
    stage1_percent_best: % or number of performers to keep after Stage 1 (default: 25%).
    stage2_percent_best: % or number of performers to keep after Stage 2 (default: 25%).
    start_server:        Set to 1 to automatically start a local HTTP server and open the report.

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
import time
import webbrowser
import socket

def get_character_name(input_file):
    """
    Parses the input .simc file to find the primary character's name.
    Looks for the 'name=' or 'class=name' line.
    """
    classes = {
        "deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", 
        "monk", "paladin", "priest", "rogue", "shaman", "warlock", "warrior"
    }
    try:
        with open(input_file, "r", encoding='utf-8', errors='replace') as f:
            for line in f:
                # Match name=...
                match = re.match(r"^name=[\"']?([^\"'\s,]+)[\"']?", line)
                if match:
                    return match.group(1).strip()
                # Match paladin=...
                match = re.match(r"^(\w+)=[\"']?([^\"'\s,]+)[\"']?", line)
                if match:
                    key, val = match.groups()
                    if key.lower() in classes:
                        return val.strip()
    except Exception as e:
        print(f"Warning: Could not extract character name from {input_file}: {e}")
    return None

def get_all_combos(input_file, current_name=None):
    """
    Returns a list of all combo names found in the input file.
    """
    combos = []
    try:
        with open(input_file, "r", encoding='utf-8', errors='replace') as f:
            for line in f:
                match = re.match(r"^copy=[\"']?([^,\"']+)[^\"']*[\"']?", line)
                if match:
                    name = match.group(1).strip()
                    if name != current_name:
                        combos.append(name)
    except Exception as e:
        print(f"Error counting combos: {e}")
    return combos

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

def get_all_dps(log_path, current_name=None):
    """
    Parses a SimulationCraft log file to extract all (name, dps) tuples.
    """
    if not os.path.exists(log_path):
        return []

    results = []
    ranking_started = False

    with open(log_path, "r", encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not ranking_started:
                if line.startswith("DPS Ranking:"):
                    ranking_started = True
                continue
            
            if not line or line.startswith("HPS Ranking:"):
                break
            
            match = re.match(r"^(\d+)\s+[\d.]+%?\s+(.+)$", line)
            if match:
                dps = int(match.group(1))
                name = match.group(2).strip()
                if name != "Raid" and name != current_name:
                    results.append((name, dps))
    return results

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
                    # header += "active=0\n"
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
    script_start_time = time.time()
    
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
    
    all_combos = get_all_combos(input_file, current_name=char_name)
    initial_combo_count = len(all_combos)
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
    
    reports_dir = "/tmp/simc_reports"
    os.makedirs(reports_dir, exist_ok=True)
    report_file = f"report_{start_time}.html"
    report_name = os.path.join(reports_dir, report_file)
    
    BATCH_SIZE = 400
    top_combos_s1 = []

    # Stage 1: Fast Filtering
    if initial_combo_count > BATCH_SIZE:
        print(f"\n--- STAGE 1: Fast Filtering (iterations=100) using {s1_filter} [BATCHED] ---")
        chunks = [all_combos[i:i + BATCH_SIZE] for i in range(0, len(all_combos), BATCH_SIZE)]
        all_batch_results = []
        for idx, chunk in enumerate(chunks):
            print(f"\n--- Processing Batch {idx + 1}/{len(chunks)} ({len(chunk)} combos) ---")
            chunk_simc = os.path.join(tmp_dir, f"stage1_batch{idx+1}.simc")
            prepare_stage(input_file, chunk, chunk_simc, "iterations=100", current_name=char_name)
            
            chunk_log = os.path.join(tmp_dir, f"stage1_batch{idx+1}.log")
            exit_code = run_simc(simc_path, chunk_simc, "iterations=100 single_actor_batch=1", chunk_log)
            if exit_code != 0:
                print(f"Error: simc failed on batch {idx+1} with exit code {exit_code}. It might have run out of memory.")
                sys.exit(1)
                
            batch_results = get_all_dps(chunk_log, current_name=char_name)
            all_batch_results.extend(batch_results)
            print(f"Parsed {len(batch_results)} results from batch {idx+1}")
            
        # Global sorting and filtering
        all_batch_results.sort(key=lambda x: x[1], reverse=True)
        
        if s1_filter.endswith("%"):
            percentage = float(s1_filter.replace("%", "")) / 100
            target_n = max(1, math.ceil(initial_combo_count * percentage))
        else:
            target_n = int(s1_filter)
            
        top_combos_s1 = [item[0] for item in all_batch_results[:target_n]]
        print(f"\nAggregated {len(all_batch_results)} total profiles across all batches.")
        print(f"Kept global top {target_n} profiles for Stage 2.")
    else:
        print(f"\n--- STAGE 1: Fast Filtering (iterations=100) using {s1_filter} ---")
        stage1_log = os.path.join(tmp_dir, "stage1.log")
        exit_code = run_simc(simc_path, input_file, "iterations=100 single_actor_batch=1", stage1_log)
        if exit_code != 0:
            print(f"Error: simc failed with exit code {exit_code}. It might have run out of memory.")
            sys.exit(1)
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
    exit_code = run_simc(simc_path, stage2_simc, "iterations=2000 single_actor_batch=1", stage2_log)
    if exit_code != 0:
        print(f"Error: simc failed on stage 2 with exit code {exit_code}.")
        sys.exit(1)
    top_combos_s2 = filter_best(stage2_log, s2_filter, current_name=char_name)
    
    if not top_combos_s2:
        print("Error: No combos found to refine after Stage 2. Stopping.")
        sys.exit(1)
    
    stage3_simc = os.path.join(tmp_dir, "stage3.simc")
    prepare_stage(input_file, top_combos_s2, stage3_simc, "", current_name=char_name)

    # Stage 3: Final Selection
    print("\n--- STAGE 3: Final Selection ---")
    stage3_log = os.path.join(tmp_dir, "stage3.log")
    exit_code = run_simc(simc_path, stage3_simc, "single_actor_batch=1", stage3_log, html_report=report_name)
    if exit_code != 0:
        print(f"Error: simc failed on stage 3 with exit code {exit_code}.")
        sys.exit(1)
    
    print(f"\nSimcraft Helper complete! Results in {report_name}")
    print(f"Temporary files are in {tmp_dir}")
    
    elapsed_time = time.time() - script_start_time
    minutes, seconds = divmod(int(elapsed_time), 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        print(f"Total execution time: {hours}h {minutes}m {seconds}s")
    elif minutes > 0:
        print(f"Total execution time: {minutes}m {seconds}s")
    else:
        print(f"Total execution time: {seconds}s")

    if str(args.get("start_server", "")).lower() in ("1", "true"):
        print(f"\nStarting local HTTP server on port 8000 in {reports_dir} (if not already running)...")
        # Try to start the server in the background
        server_process = subprocess.Popen(
            [sys.executable, "-m", "http.server", "8000", "-d", reports_dir], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        # Give it a tiny bit of time to spin up
        time.sleep(1)
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host_ip = s.getsockname()[0]
            s.close()
        except Exception:
            host_ip = "localhost"
            
        url = f"http://{host_ip}:8000/{report_file}"
        print(f"Opening report: {url}")
        webbrowser.open(url)
        
        try:
            input("\nPress Enter to stop the server and exit...")
        except KeyboardInterrupt:
            pass
        finally:
            print("Stopping the HTTP server...")
            server_process.terminate()
            server_process.wait()

if __name__ == "__main__":
    main()
