#!/usr/bin/env python3
"""
Simcraft Automation Script

This script automates a 3-stage workflow for SimulationCraft:
1. Stage 1: Fast Filtering (default 200 iterations at target_error=1%) - Broadly identifies top performers.
2. Stage 2: Refinement (5000 iterations at target_error=0.2%) - Narrows down the results using higher precision.
3. Stage 3: Final Selection (20000 iterations at target_error=0.05%) - Produces the final high-precision report.

Each stage passes explicit 'iterations=<cap> target_error=<err>%' CLI args (early
stop per actor); the plan is overridable via SIMC_HELPER_STAGE_PLAN and the
culling error band via SIMC_HELPER_CULL_K (see get_stage_plan/cull_k).

The script automatically detects the base character profile and ensures it is
included at the top of the input for every stage.

If the input contains no 'copy=' candidate profiles (e.g. the user selected no
gear changes), the script runs a single baseline current-gear simulation and
still produces the HTML report instead of failing.

Usage:
    ./sim_helper simc_path=/path/to/simc input_file=your_input.simc [stage1_percent_best=25%] [stage2_percent_best=25%] [start_server=1]

Arguments:
    simc_path:           Path to the SimulationCraft executable.
    input_file:          Path to the base .simc file containing 'copy=' profiles.
    stage1_percent_best: % or count; overrides the Stage 1 keep-count basis (the cost-cap
                         anchor) — survivors themselves are chosen by error band (see select_survivors).
    stage2_percent_best: same for Stage 2 (default: 25%).
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

# Staged precision parity (design t_0fbfd0bd §5.1, ruling D5): every stage runs
# with an explicit iteration cap and target_error so SimC early-stops per actor
# like Smart Sim — and so stage 3 no longer inherits the export-leaked
# target_error from the global-settings block (real bug, ruling E3).
STAGE_PLAN_DEFAULT = [(200, 1.0), (5000, 0.2), (20000, 0.05)]

def get_stage_plan():
    """Parse SIMC_HELPER_STAGE_PLAN 'iters:err;iters:err;iters:err' (error as
    percent float). Clamps iters to 1..100000 and err to 0.01..5; malformed
    input warns and falls back to STAGE_PLAN_DEFAULT (same defensive posture
    as get_memory_based_batch_size). Permanent worker knob (ruling Q2): the
    container env flows through get_clean_env() into every run_simc call."""
    raw = os.environ.get("SIMC_HELPER_STAGE_PLAN", "").strip()
    if not raw:
        return list(STAGE_PLAN_DEFAULT)
    try:
        plan = []
        for part in raw.split(";"):
            iters_s, err_s = part.split(":")
            plan.append((max(1, min(100000, int(iters_s))),
                         max(0.01, min(5.0, float(err_s)))))
        if len(plan) != len(STAGE_PLAN_DEFAULT):
            raise ValueError(
                f"expected {len(STAGE_PLAN_DEFAULT)} 'iters:err' entries, got {len(plan)}")
        return plan
    except ValueError as exc:
        print(f"Warning: malformed SIMC_HELPER_STAGE_PLAN '{raw}' ({exc}); using default stage plan.")
        return list(STAGE_PLAN_DEFAULT)

def stage_args(plan, stage_idx):
    """Args string for one stage (0-based). The same string is passed to both
    prepare_stage (file options) and run_simc (CLI) — the CLI is authoritative
    over any leaked file/export option (verified, design Appendix A#4)."""
    cap, err = plan[stage_idx]
    return f"iterations={cap} target_error={err:g}% single_actor_batch=1"

def cull_k():
    """Keep-band width multiplier (SIMC_HELPER_CULL_K, default 1.0). Engine
    DPS-Error is the 95% CI half-width of the sample mean (1.96*sigma_mean —
    step-0 verdict on t_590f5317), so 1.0 mirrors the intended ~2-sigma keep
    band (ruling Q4). Presentation band (2*err_top) in results.js is separate."""
    try:
        return float(os.environ.get("SIMC_HELPER_CULL_K", "1.0"))
    except ValueError:
        return 1.0

def _filter_to_count(filter_arg, total):
    """Resolve a '25%'/'20' stage filter argument to a keep-count."""
    arg = str(filter_arg)
    if arg.endswith("%"):
        return max(1, math.ceil(total * float(arg[:-1]) / 100))
    return int(arg)

def select_survivors(summaries, count, override=None):
    """Decide which actors advance a stage (design t_0fbfd0bd §5.3).

    Keep rule is an error band versus the top mean: keep i when
    mean_i + K*err_i_abs >= mean_top - K*err_top_abs (err_abs = mean*err_pct/100).
    The old percentage-of-count rule survives only as a cost cap of
    max(25, 3*count); `count` is the keep-count the old rule would have given
    from the stage defaults and `override` (the stage1/stage2_percent_best
    argument, '25%'/'20') replaces that basis — the args never pick the
    keep-set directly anymore. Actors whose error failed to parse (ok=False)
    stay only inside the old count-rule ordering. `summaries` must already be
    in count-rule (ranking) order; the survivor names come back in that order.
    """
    if not summaries:
        return []
    if override is not None:
        count = _filter_to_count(override, len(summaries))
    k = cull_k()
    banded = [s for s in summaries if s[3]]
    if not banded:
        return [s[0] for s in summaries[:count]]
    top = max(banded, key=lambda s: s[1])
    bound = top[1] - k * top[1] * top[2] / 100.0
    kept = set()
    for idx, (name, mean, err_pct, ok) in enumerate(summaries):
        if ok:
            if mean + k * mean * err_pct / 100.0 >= bound:
                kept.add(name)
        elif idx < count:
            kept.add(name)
    survivors = [s[0] for s in summaries if s[0] in kept]
    cap = max(25, 3 * count)
    if len(survivors) > cap:
        culled = len(survivors) - cap
        mean_of = {s[0]: s[1] for s in summaries}
        top_set = set(sorted(survivors, key=lambda n: mean_of[n], reverse=True)[:cap])
        print(f"Culled {culled} statistically-tied candidates to fit the work budget")
        survivors = [n for n in survivors if n in top_set]
    return survivors

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
                            m = re.search(r"(\d+)/(\d+)\s+\[[^\]]*\]\s+(\d+)/(\d+)", line)
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

def get_actor_summaries(log_path, current_name=None):
    """Parse a SimC console log into [(name, mean, err_pct, ok)] in DPS
    Ranking order.

    Names and means come from the 'DPS Ranking:' block (same regex/format as
    filter_best — engine report_text.cpp); each actor's relative error comes
    from its 'Player:' summary block, where the engine prints
    '  DPS=<mean> DPS-Error=<abs>/<rel>%' on the line right after the
    'Player: <name> ...' header (Player blocks also echo the full APL, hence
    the bounded streaming window). ok=False marks an error-parse miss —
    select_survivors then keeps that actor only within the count rule.
    Quarantine (defect t_6400a2ed #7, design §5.4): entries with dps <= 0 are
    dropped and Raid/current_name are never listed, so dead actors can no
    longer occupy keep-set slots when target_n exceeds the healthy population.
    """
    if not os.path.exists(log_path):
        return []

    ranking = []   # (name, mean) in DPS Ranking order
    stats = []     # (player_rest, mean, err_pct) from Player: summary blocks
    ranking_started = False
    pending_rest = None  # Player: block still waiting for its DPS= line
    pending_left = 0

    with open(log_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if ranking_started:
                if not line or line.startswith("HPS Ranking:"):
                    ranking_started = False
                else:
                    match = re.match(r"^(\d+)\s+[\d.]+%?\s+(.+)$", line)
                    if match:
                        name = match.group(2).strip()
                        if name != "Raid" and name != current_name:
                            ranking.append((name, int(match.group(1))))
                continue

            if line.startswith("DPS Ranking:"):
                ranking_started = True
                continue
            match = re.match(r"^Player: (.+)$", line)
            if match:
                pending_rest = match.group(1).strip()
                pending_left = 6
                continue
            if pending_rest is not None:
                pending_left -= 1
                m = re.match(r"^DPS=([\d.]+)[^ ]* DPS-Error=([\d.]+)/([\d.]+)%", line)
                if m:
                    stats.append((pending_rest, float(m.group(1)), float(m.group(3))))
                    pending_rest = None
                elif pending_left <= 0:
                    pending_rest = None

    summaries = []
    for name, rank_mean in ranking:
        # Copy names may contain spaces; the Player header line continues with
        # race/class/spec/level, so match by '<name> ' prefix.
        hit = next((s for s in stats if s[0] == name or s[0].startswith(name + " ")), None)
        if hit:
            summaries.append((name, hit[1], hit[2], True))
        else:
            summaries.append((name, float(rank_mean), None, False))
    return [s for s in summaries if s[1] > 0]

def get_all_dps(log_path, current_name=None):
    """Legacy (name, dps) view over get_actor_summaries (count-rule callers)."""
    return [(name, int(mean)) for name, mean, _, _ in
            get_actor_summaries(log_path, current_name=current_name)]

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

    # Degenerate selection: every candidate equals equipped gear, so the input
    # has no copy= blocks. The base actor is still a valid current-gear
    # simulation — run it once at full precision and emit the HTML report
    # instead of failing with "no combos to refine" (t_4485565b).
    baseline_only = initial_combo_count == 0

    stage_plan = get_stage_plan()
    s1_args = stage_args(stage_plan, 0)
    s2_args = stage_args(stage_plan, 1)
    s3_args = stage_args(stage_plan, 2)
    user_s1_filter = args.get("stage1_percent_best")
    user_s2_filter = args.get("stage2_percent_best")

    s1_filter = user_s1_filter
    if baseline_only:
        s1_filter = s1_filter or "100%"  # unused in baseline mode
    elif not s1_filter:
        s1_filter = get_default_filter(1, initial_combo_count)
        print(f"Using dynamic default for Stage 1: {s1_filter}")

    s2_filter = user_s2_filter
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

    if baseline_only:
        # No copy= blocks to refine: simulate the base actor once with the
        # final-stage precision plan and emit the HTML report (same report
        # path the staged pipeline uses, so the worker picks it up unchanged).
        print("\n--- BASELINE: no candidate combinations; simulating current gear only ---")
        baseline_log = os.path.join(tmp_dir, "baseline.log")
        exit_code = run_simc(simc_path, input_file, s3_args, baseline_log, html_report=report_name)
        if exit_code != 0:
            print(f"Error: simc failed on the baseline simulation with exit code {exit_code}.")
            sys.exit(1)
    else:
        # Stage 1: Fast Filtering
        if initial_combo_count > BATCH_SIZE:
            print(f"\n--- STAGE 1: Fast Filtering ({s1_args}) using {s1_filter} [BATCHED, size={BATCH_SIZE}] ---")
            chunks = [all_combos[i:i + BATCH_SIZE] for i in range(0, len(all_combos), BATCH_SIZE)]
            all_batch_summaries = []
            for idx, chunk in enumerate(chunks):
                batch_prefix = f"[Batch {idx + 1}/{len(chunks)}] "
                print(f"\n{batch_prefix}Processing {len(chunk)} combinations...")
                chunk_simc = os.path.join(tmp_dir, f"stage1_batch{idx+1}.simc")
                prepare_stage(input_file, chunk, chunk_simc, s1_args, current_name=char_name)

                chunk_log = os.path.join(tmp_dir, f"stage1_batch{idx+1}.log")
                exit_code = run_simc(simc_path, chunk_simc, s1_args, chunk_log, prefix=batch_prefix)
                if exit_code != 0:
                    print(f"Error: simc failed on batch {idx+1} with exit code {exit_code}. It might have run out of memory.")
                    sys.exit(1)

                all_batch_summaries.extend(get_actor_summaries(chunk_log, current_name=char_name))

            # Global band culling across all batches (means/errors collected
            # per actor; batch boundaries cannot shift the keep-set, R4).
            all_batch_summaries.sort(key=lambda x: x[1], reverse=True)
            top_combos_s1 = select_survivors(
                all_batch_summaries,
                _filter_to_count(get_default_filter(1, initial_combo_count), initial_combo_count),
                user_s1_filter)
            print(f"\nAggregated {len(all_batch_summaries)} total profiles across all batches.")
            print(f"Kept {len(top_combos_s1)} profiles within the error band for Stage 2.")
        else:
            print(f"\n--- STAGE 1: Fast Filtering ({s1_args}) using {s1_filter} ---")
            stage1_log = os.path.join(tmp_dir, "stage1.log")
            exit_code = run_simc(simc_path, input_file, s1_args, stage1_log)
            if exit_code != 0:
                print(f"Error: simc failed with exit code {exit_code}. It might have run out of memory.")
                sys.exit(1)
            top_combos_s1 = select_survivors(
                get_actor_summaries(stage1_log, current_name=char_name),
                _filter_to_count(get_default_filter(1, initial_combo_count), initial_combo_count),
                user_s1_filter)

        if not top_combos_s1:
            print("Error: No combos found to refine after Stage 1. Stopping.")
            sys.exit(1)

        if not s2_filter:
            s2_filter = get_default_filter(2, len(top_combos_s1))
            print(f"Using dynamic default for Stage 2: {s2_filter}")
        s2_default_n = _filter_to_count(get_default_filter(2, len(top_combos_s1)), len(top_combos_s1))

        stage2_simc = os.path.join(tmp_dir, "stage2.simc")
        prepare_stage(input_file, top_combos_s1, stage2_simc, s2_args, current_name=char_name)

        # Stage 2: Refinement
        print(f"\n--- STAGE 2: Refinement ({s2_args}) using {s2_filter} ---")
        stage2_log = os.path.join(tmp_dir, "stage2.log")
        exit_code = run_simc(simc_path, stage2_simc, s2_args, stage2_log, prefix="[Stage 2] ")
        if exit_code != 0:
            print(f"Error: simc failed on stage 2 with exit code {exit_code}.")
            sys.exit(1)
        top_combos_s2 = select_survivors(
            get_actor_summaries(stage2_log, current_name=char_name), s2_default_n, user_s2_filter)

        if not top_combos_s2:
            print("Error: No combos found to refine after Stage 2. Stopping.")
            sys.exit(1)

        # Stage 3 must pass explicit precision args: without them it silently
        # inherited the target_error/iterations leaked by the export's global
        # settings block via prepare_stage (live-observed final run at 0.2%;
        # real bug fixed here, design ruling E3).
        stage3_simc = os.path.join(tmp_dir, "stage3.simc")
        prepare_stage(input_file, top_combos_s2, stage3_simc, s3_args, current_name=char_name)

        # Stage 3: Final Selection
        print(f"\n--- STAGE 3: Final Selection ({s3_args}) ---")
        stage3_log = os.path.join(tmp_dir, "stage3.log")
        exit_code = run_simc(simc_path, stage3_simc, s3_args, stage3_log, html_report=report_name, prefix="[Stage 3] ")
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
