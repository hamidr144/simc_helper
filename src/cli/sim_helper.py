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
import datetime
import math
import os
import pty
import re
import select
import socket
import subprocess  # nosec B404
import sys
import time
import webbrowser


def get_clean_env():
    env = os.environ.copy()
    # PyInstaller sets these, which can break system binaries (symbol lookup errors)
    for var in ["LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"]:
        orig = var + "_ORIG"
        if orig in env:
            env[var] = env[orig]
        elif var in env:
            del env[var]

    # Also ensure the bundled bin path isn't first in PATH
    if "PATH" in env and sys.prefix in env["PATH"]:
        # Remove any entries containing the PyInstaller temporary directory
        paths = env["PATH"].split(os.pathsep)
        clean_paths = [p for p in paths if sys.prefix not in p]
        env["PATH"] = os.pathsep.join(clean_paths)

    return env

try:
    import psutil
except ImportError:
    psutil = None

def get_memory_based_batch_size(buffer_gb=4.0, mb_per_profile=90.0):
    """
    Calculates batch size based on available system RAM.
    Defaults to 200 if RAM cannot be detected.
    Strictly caps at 200 to prevent OOM on large core systems.
    """
    max_batch_size = 200

    if not psutil:
        # Fallback: try to parse /proc/meminfo on Linux
        try:
            with open('/proc/meminfo') as f:
                for line in f:
                    if line.startswith('MemAvailable:'):
                        kb = int(line.split()[1])
                        available_mb = kb / 1024
                        usable_mb = available_mb - (buffer_gb * 1024)
                        calculated = max(50, int(usable_mb / mb_per_profile))
                        return min(calculated, max_batch_size)
        except (OSError, ValueError, IndexError):
            return max_batch_size  # Conservative fallback

    try:
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
        usable_mb = available_mb - (buffer_gb * 1024)
        calculated = max(50, int(usable_mb / mb_per_profile))
        return min(calculated, max_batch_size)
    except (AttributeError, OSError, ValueError):
        return max_batch_size

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
        with open(input_file, encoding='utf-8', errors='replace') as f:
            for line in f:
                # Match name=...
                match = re.search(r"^name=[\"']?([^\"'\s,]+)[\"']?", line)
                if match:
                    return match.group(1).strip()
                # Match paladin=...
                match = re.search(r"^(\w+)=[\"']?([^\"'\s,]+)[\"']?", line)
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
        with open(input_file, encoding='utf-8', errors='replace') as f:
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

def run_simc(simc_path, input_file, extra_args, output_log, html_report=None, prefix=""):
    """
    Executes SimulationCraft via a pseudo-terminal (PTY) to capture real-time
    interactive progress bars while logging the full output to a file.
    """
    if not os.path.isfile(simc_path) or not os.access(simc_path, os.X_OK):
        print(
            f"{prefix}SimulationCraft engine is unavailable: {simc_path}. "
            "Install it with `python3 utils/deploy.py simc --config deploy_configs/installation.json` "
            "(or deploy with `--install-simc`)."
        )
        return 127

    cmd = [simc_path, input_file] + extra_args.split()
    if html_report:
        cmd.append(f"html={html_report}")

    # print(f"Running: {' '.join(cmd)}") # Quieter

    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(cmd, stdout=slave_fd, stderr=slave_fd, close_fds=True, env=get_clean_env())  # nosec B603
    os.close(slave_fd)

    with open(output_log, "wb") as f_log:
        buffer = b""
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(master_fd, 4096)
                    if not data: break
                    f_log.write(data)
                    f_log.flush()
                    buffer += data

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
                            # Match: Combo_400 401/401 [===================>] 100/100
                            # Groups: 1:curr_actor, 2:total_actors, 3:curr_iter, 4:total_iters
                            m = re.search(r"(\d+)/(\d+)\s+\[.*?\]\s+(\d+)/(\d+)", line)
                            if m:
                                curr_a, tot_a, curr_i, tot_i = m.groups()
                                curr_a_int = int(curr_a)
                                if curr_a_int % 5 == 0 or curr_a == tot_a or curr_i == tot_i:
                                    percent = int((curr_a_int / int(tot_a)) * 100)
                                    print(f"\r{prefix}Progress: {percent}% ({curr_a}/{tot_a} profiles)", end="", flush=True)
                            elif "Progress:" in line and "combos" not in line:
                                print(f"\r{prefix}{line}", end="", flush=True)
                        except ValueError as exc:
                            print(f"\n{prefix}Ignored malformed progress line: {exc}", file=sys.stderr)
                except OSError: break
            if process.poll() is not None:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if not r: break
        process.wait()
        print()

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
    with open(log_path, encoding='utf-8', errors='replace') as f:
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

    with open(log_path, encoding='utf-8', errors='replace') as f:
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
    with open(base_simc, encoding='utf-8', errors='replace') as f:
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
                line_strip = line.strip()
                if not line_strip:
                    header += "\n"
                    continue

                # Check if it's a global setting (not related to character gear/stats)
                if "=" in line_strip and not any(line_strip.startswith(k) for k in class_keywords):
                    header += "# " + line
                    global_settings.append(line_strip)
                else:
                    # It's part of the base actor definition
                    header += line
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
    tmp_dir = f"/tmp/simc_{start_time}"  # nosec B108
    os.makedirs(tmp_dir, exist_ok=True)

    reports_dir = "/tmp/simc_reports"  # nosec B108
    os.makedirs(reports_dir, exist_ok=True)
    report_file = f"report_{start_time}.html"
    report_name = os.path.join(reports_dir, report_file)

    # Dynamic Batching: Determine size based on available RAM
    BATCH_SIZE = get_memory_based_batch_size()
    print(f"Dynamic batch size determined: {BATCH_SIZE} combinations (based on available RAM)")

    top_combos_s1 = []

    # Stage 1: Fast Filtering
    if initial_combo_count > BATCH_SIZE:
        print(f"\n--- STAGE 1: Fast Filtering (iterations=100) using {s1_filter} [BATCHED, size={BATCH_SIZE}] ---")
        chunks = [all_combos[i:i + BATCH_SIZE] for i in range(0, len(all_combos), BATCH_SIZE)]
        all_batch_results = []
        for idx, chunk in enumerate(chunks):
            batch_prefix = f"[Batch {idx + 1}/{len(chunks)}] "
            print(f"\n{batch_prefix}Processing {len(chunk)} combinations...")
            chunk_simc = os.path.join(tmp_dir, f"stage1_batch{idx+1}.simc")
            prepare_stage(input_file, chunk, chunk_simc, "iterations=100", current_name=char_name)

            chunk_log = os.path.join(tmp_dir, f"stage1_batch{idx+1}.log")
            exit_code = run_simc(simc_path, chunk_simc, "iterations=100 single_actor_batch=1", chunk_log, prefix=batch_prefix)
            if exit_code != 0:
                print(f"Error: simc failed on batch {idx+1} with exit code {exit_code}. It might have run out of memory.")
                sys.exit(1)

            batch_results = get_all_dps(chunk_log, current_name=char_name)
            all_batch_results.extend(batch_results)
            # print(f"Parsed {len(batch_results)} results from batch {idx+1}") # Quieter

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
    exit_code = run_simc(simc_path, stage2_simc, "iterations=2000 single_actor_batch=1", stage2_log, prefix="[Stage 2] ")
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
    exit_code = run_simc(simc_path, stage3_simc, "single_actor_batch=1", stage3_log, html_report=report_name, prefix="[Stage 3] ")
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
        server_process = subprocess.Popen(  # nosec B603
            [sys.executable, "-m", "http.server", "8000", "-d", reports_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=get_clean_env()
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
