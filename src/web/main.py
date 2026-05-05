from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import subprocess
import os
import pty
import select
import sys
import json
import re
from typing import List, Dict, Any
from pydantic import BaseModel

# Add project root to path so we can import local modules if needed
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = FastAPI()

# Ensure temp directories exist
os.makedirs("/tmp/simc_reports", exist_ok=True)
os.makedirs("/tmp/simc_tmp", exist_ok=True)

# Mount static files and reports
app.mount("/static", StaticFiles(directory="src/web/static"), name="static")
app.mount("/reports", StaticFiles(directory="/tmp/simc_reports"), name="reports")

@app.get("/")
def read_root():
    with open("src/web/static/index.html", "r") as f:
        return HTMLResponse(content=f.read(), status_code=200)

async def stream_subprocess(cmd, cwd=None):
    """Generator to stream subprocess output via SSE."""
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        cmd, 
        stdout=slave_fd, 
        stderr=slave_fd, 
        close_fds=True,
        cwd=cwd
    )
    os.close(slave_fd)
    
    try:
        while True:
            r, _, _ = select.select([master_fd], [], [], 0.1)
            if r:
                try:
                    data = os.read(master_fd, 4096)
                    if not data:
                        break
                    # Clean ANSI escape codes for cleaner web output if desired, or keep them
                    text = data.decode('utf-8', errors='replace')
                    # PTY converts \n to \r\n, causing every line to have \r.
                    # We strip \r\n to \n to fix the frontend overwriting logic.
                    text = text.replace('\r\n', '\n')
                    # Yield as SSE data
                    for line in text.split('\n'):
                        if line:
                            yield f"data: {json.dumps({'type': 'log', 'text': line})}\n\n"
                except OSError:
                    break
            
            if process.poll() is not None:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if not r:
                    break
                    
        process.wait()
        yield f"data: {json.dumps({'type': 'exit', 'code': process.returncode})}\n\n"
    finally:
        os.close(master_fd)

@app.get("/api/update-simc")
def update_simc():
    script_path = os.path.abspath("scripts/manage_simc.sh")
    cwd = os.path.dirname(os.path.dirname(script_path))
    return StreamingResponse(
        stream_subprocess([script_path], cwd=cwd), 
        media_type="text/event-stream"
    )

class AddonPayload(BaseModel):
    addon_text: str

@app.post("/api/parse-addon")
def parse_addon(payload: AddonPayload):
    lines = payload.addon_text.split('\n')
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
        if not line_strip: continue
        
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

    return {
        "char_name": char_name,
        "char_class": char_class,
        "base_profile": "\n".join(base_profile),
        "equipped_gear": equipped_gear,
        "items_by_slot": items_by_slot,
        "item_names": item_names
    }

class SimPayload(BaseModel):
    base_profile: str
    char_class: str
    char_name: str
    equipped_gear: Dict[str, str]
    selected_items: Dict[str, List[str]]

@app.post("/api/generate-simc")
def generate_simc(payload: SimPayload):
    # This will create a file in /tmp/simc_tmp that can be passed to sim_helper
    try:
        from cli.generate_input import generate_variations
    except ImportError:
        def generate_variations(item_list, slot_name, config):
            return item_list # Fallback

    output_file = "/tmp/simc_tmp/generated_sim.simc"
    
    # We will just write a simple version, simulating what generate_input.py does.
    # In a fully robust version, we'd reuse its exact code.
    from itertools import product
    
    choices = []
    group_slots = ["head", "neck", "shoulder", "back", "chest", "wrist", "hands", "waist", "legs", "feet", "main_hand", "off_hand"]
    for slot in group_slots:
        items = payload.selected_items.get(slot, [payload.equipped_gear.get(slot, "")])
        # Add basic enchants if you wanted, skipping config for now or loading it
        choices.append(items)

    finger_vars = payload.selected_items.get("finger", [payload.equipped_gear.get("finger1", "")])
    trinket_vars = payload.selected_items.get("trinket", [payload.equipped_gear.get("trinket1", "")])
    
    finger_pairs = [(finger_vars[i], finger_vars[j]) for i in range(len(finger_vars)) for j in range(i+1, len(finger_vars))] if len(finger_vars)>=2 else [(finger_vars[0], "")] if len(finger_vars)==1 else [("", "")]
    trinket_pairs = [(trinket_vars[i], trinket_vars[j]) for i in range(len(trinket_vars)) for j in range(i+1, len(trinket_vars))] if len(trinket_vars)>=2 else [(trinket_vars[0], "")] if len(trinket_vars)==1 else [("", "")]

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Generated Top Gear Sim\n")
        f.write(f'{payload.char_class}="{payload.char_name}_Baseline"\n')
        # Ensure base_profile replaces literal \n with actual newlines
        f.write(payload.base_profile.replace("\\n", "\n") + "\n")
        for slot in payload.equipped_gear: f.write(f"{slot}={payload.equipped_gear[slot]}\n")
        f.write("\n")

        i = 1
        for base_config, fingers, trinkets in product(product(*choices), finger_pairs, trinket_pairs):
            f.write(f'copy="Combo_{i},{payload.char_name}_Baseline"\n')
            for slot, details in zip(group_slots, base_config):
                if details: f.write(f"{slot}={details}\n")
            if fingers[0]: f.write(f"finger1={fingers[0]}\n")
            if fingers[1]: f.write(f"finger2={fingers[1]}\n")
            if trinkets[0]: f.write(f"trinket1={trinkets[0]}\n")
            if trinkets[1]: f.write(f"trinket2={trinkets[1]}\n\n")
            i += 1
            
    return {"status": "success", "file_path": output_file, "combinations": i-1}

@app.get("/api/run-simulation")
def run_simulation(input_file: str = "/tmp/simc_tmp/generated_sim.simc"):
    sim_helper_path = os.path.abspath("src/cli/sim_helper.py")
    simc_engine = os.path.expanduser("~/.simc/engine/simc")
    
    if not os.path.exists(simc_engine):
        raise HTTPException(status_code=400, detail="SimulationCraft engine not found. Please update/build it first.")
        
    cmd = [
        sys.executable,
        "-u",
        sim_helper_path,
        f"simc_path={simc_engine}",
        f"input_file={input_file}",
        "start_server=0" # Prevent it from spawning its own server/browser
    ]
    
    cwd = os.getcwd()
    return StreamingResponse(
        stream_subprocess(cmd, cwd=cwd), 
        media_type="text/event-stream"
    )

@app.get("/api/get-results")
def get_results(tmp_dir: str):
    log_path = os.path.join(tmp_dir, "stage3.log")
    simc_path = os.path.join(tmp_dir, "stage3.simc")
    
    if not os.path.exists(log_path) or not os.path.exists(simc_path):
        raise HTTPException(status_code=404, detail="Results not found.")
        
    results_map = {}
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
                if name != "Raid":
                    results_map[name] = {"name": name, "dps": dps, "gear": {}}

    current_combo = None
    classes = {"deathknight", "demonhunter", "druid", "evoker", "hunter", "mage", "monk", "paladin", "priest", "rogue", "shaman", "warlock", "warrior"}
    
    with open(simc_path, "r", encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            match_class = re.match(r'^(\w+)=["\']?([^"\']+)["\']?$', line)
            if match_class and match_class.group(1).lower() in classes:
                current_combo = match_class.group(2)
            elif line.startswith("copy="):
                match = re.match(r'^copy=["\']?([^,"\']+)["\']?', line)
                if match:
                    current_combo = match.group(1)
            elif current_combo and current_combo in results_map:
                match_gear = re.match(r'^(head|neck|shoulder|back|chest|wrist|hands|waist|legs|feet|finger1|finger2|trinket1|trinket2|main_hand|off_hand)=(.*)$', line)
                if match_gear:
                    slot, details = match_gear.groups()
                    results_map[current_combo]["gear"][slot] = details

    sorted_results = sorted(results_map.values(), key=lambda x: x["dps"], reverse=True)
    return {"results": sorted_results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.web.main:app", host="0.0.0.0", port=8000, reload=True)
