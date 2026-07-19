# Example configuration files

These templates are safe to commit. Choose one installation topology, copy it to the ignored deployment directory, then replace placeholders on your machine:

```bash
cp examples/config.example.json config.json
mkdir -p deploy_configs
cp examples/deploy_local.example.json deploy_configs/installation.json
# OR
cp examples/deploy_remote.example.json deploy_configs/installation.json
```

Files and directories intentionally ignored by git:

- `config.json`
- `deploy_configs/`

Use a long random `cluster_secret` shared by the master and all workers. Do not commit real deployment hosts, users, passwords, tokens, private key paths that should remain private, or cluster secrets.

Before deploying, validate your local files with:

```bash
python3 utils/deploy.py doctor --config deploy_configs/installation.json
```
