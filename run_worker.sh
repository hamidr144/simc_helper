#!/usr/bin/env bash
export CLUSTER_SECRET=j3J-eJvNpQvjHyVMuOGNMhtRb56yzJ86eUmV-XQVY3A=
export MASTER_URL=http://localhost:8000
exec ./bin/simc-worker >> logs/worker_local.out 2>&1
