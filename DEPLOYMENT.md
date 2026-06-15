# Deployment Workflow

This document outlines the steps to deploy the SimCraft Helper Suite on a target machine.

## 1. Prerequisites
- Python 3.11+ (or use the provided Docker image).
- `ssh` access to the worker host(s) with a public key set up.
- Systemd (user services) available on the target (Linux/macOS).
- `git` and `make`/`cmake` installed if you plan to build the SimC binaries locally.

## 2. SSH Key Setup
```bash
# On your local machine (the master)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
# Copy the public key to each worker
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@worker-host
```
Verify:
```bash
ssh -i ~/.ssh/id_ed25519 user@worker-host echo ok
# should output "ok"
```

## 3. Install the Service Files
```bash
# Clone the repo on the master host
git clone https://github.com/yourorg/simc_helper.git
cd simc_helper
# Install Python dependencies (venv optional)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Copy the systemd unit to `~/.config/systemd/user/` (or `/etc/systemd/user/` for system-wide):
```bash
mkdir -p ~/.config/systemd/user
cp utils/simc-worker.service ~/.config/systemd/user/
# Enable and start the service
systemctl --user daemon-reload
systemctl --user enable simc-worker.service
systemctl --user start simc-worker.service
# Check status
systemctl --user status simc-worker.service
```
Do the same on each worker host (adjust the `ExecStart` path if you installed binaries elsewhere).

## 4. Configure Secrets
Edit `deploy_configs/worker1.json` (and any other worker configs) to include:
```json
{
  "WORKER_ID": "worker1",
  "MASTER_URL": "http://master-host:8000",
  "CLUSTER_SECRET": "<your‑shared‑secret>"
}
```
**Never commit the real secret** – keep the file out of version control.

## 5. Deploy the Binaries
You can either build locally (see the Dockerfile) or copy pre‑built binaries:
```bash
# Example: copy from the master to a worker
scp -i ~/.ssh/id_ed25519 build/simc-worker user@worker-host:~/workspace/simc_helper/bin/
```
Make sure the binary is executable:
```bash
ssh -i ~/.ssh/id_ed25519 user@worker-host "chmod +x ~/workspace/simc_helper/bin/simc-worker"
```

## 6. Verify Deployment
- Visit `http://master-host:8000/health` – should return JSON with status and worker counts.
- Check the Prometheus metrics at `http://master-host:8000/metrics`.
- Ensure the worker logs (`~/workspace/simc_helper/logs/worker.out`) show a successful connection.

## 7. Updating
When a new SimC version is released, run the deployment script on each host:
```bash
python3 utils/deploy.py deploy --config deploy_configs/worker1.json
```
The script will copy the new binary, restart the systemd service, and verify the health endpoint.

---
*All paths are relative to the repository root unless otherwise noted.*