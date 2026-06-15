# Example configuration files

These templates are safe to commit. Copy them to the local paths that are ignored by git, then replace placeholders on your machine:

```bash
cp examples/config.example.json config.json
mkdir -p deploy_configs
cp examples/deploy_master.example.json deploy_configs/master.json
cp examples/deploy_worker.example.json deploy_configs/worker1.json
```

Files and directories intentionally ignored by git:

- `config.json`
- `deploy_configs/`

Use a long random `cluster_secret` shared by the master and all workers. Do not commit real deployment hosts, users, passwords, tokens, private key paths that should remain private, or cluster secrets.

Before deploying, validate your local files with:

```bash
python3 utils/deploy.py doctor --config deploy_configs/master.json deploy_configs/worker1.json
```
