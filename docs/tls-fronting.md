# TLS Fronting for Internet-Exposed simc_helper (audit HIGH-2)

Status: **implemented** (2026-10-14, task `t_d034f7e9`) · Owner: devops

## Problem

The stack was reachable as **WAN :80 → 192.168.0.4:8000 over plain HTTP**.
Login credentials and `session_id` cookies crossed the internet in cleartext.
FastAPI/uvicorn does not terminate TLS.

## Decision

**Option A — Caddy reverse proxy in compose, TLS on 443, master rebound to
loopback.** HTTP :80 is kept only as a redirect to HTTPS.

| Option | Verdict | Why |
|---|---|---|
| A. Caddy + Let's Encrypt | ✅ **Chosen** (internal CA variant) | Fully implementable and verifiable today; zero external accounts; Caddy auto-redirects HTTP→HTTPS and auto-renews internal certs. No domain exists (checked `.env` — none), so Let's Encrypt is not possible yet; Caddy's `tls internal` issues a cert with the correct IP SAN instead. |
| B. Tailscale / Cloudflare Tunnel, WAN port closed | 📌 **Recommended end state** | Strictly better if you are the only remote client (kills the public attack surface entirely), but requires a Tailscale/Cloudflare account, an auth key, and a client on every device — cannot be implemented or verified without those user-side steps. Checklist below. |
| A′. nginx + LE | ❌ Rejected | Same as Caddy but manual cert plumbing, manual redirect config, no auto-HTTPS. |

When a domain is acquired, upgrade = 3 lines (see `deploy/caddy/Caddyfile`
header) — the architecture does not change.

## What changed

1. **`deploy/caddy/Caddyfile`** (new) — site `{$SIMC_SITE_ADDRESS:192.168.0.4}`,
   `tls internal`, `default_sni` (bare-IP clients send no SNI — without this
   Caddy aborts the handshake with `tlsv1 alert internal error`), access log,
   `reverse_proxy simc-master:8000`.
2. **`docker-compose.yml`** — added `caddy` service (ports 80/443, volumes
   `caddy-data`/`caddy-config` for the CA + certs) and rebound the master's
   published port to `${MASTER_BIND:-127.0.0.1}` so **cleartext :8000 is no
   longer reachable from the network** — only loopback (host-local fallback)
   and the compose network (workers use `http://simc-master:8000` internally).
3. **`src/web/main.py`** — `session_id` and `user_id` cookies now honour
   `SIMC_COOKIE_SECURE=1` (adds the `Secure` attribute). `HttpOnly` and
   `SameSite=Lax` were already set. Default stays `0` so loopback HTTP keeps
   working; set `SIMC_COOKIE_SECURE=1` in `.env` once all clients use HTTPS.
4. **`.env` (local, untracked)** — `CORS_ALLOWED_ORIGINS` gains the https
   origins; `SIMC_SITE_ADDRESS=192.168.0.4`.

## Access after the change

| URL | Result |
|---|---|
| `https://192.168.0.4` | ✅ dashboard (Caddy internal-CA cert — trust it once or accept the warning) |
| `http://192.168.0.4` | ↪ 308 redirect to HTTPS |
| `http://127.0.0.1:8000` | ✅ still works **on the host only** (escape hatch / health) |
| `http://192.168.0.4:8000` from LAN | ❌ refused (loopback bind) — use HTTPS |

Trust the Caddy root CA on client devices to remove cert warnings:
`docker compose exec caddy sh -c "cat /data/caddy/pki/authorities/local/root.crt"`
(macOS: `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain <file>`;
iOS: AirDrop the .crt → Install → Settings ▸ Certificate Trust Settings ▸ enable full trust).

## USER-ACTION checklist (router side — user's job, not automatable)

- [ ] **Close the WAN port-80 forward** on the Comhem router (192.168.0.1 →
      port forward / NAT: delete external 80 → 192.168.0.4:8000). The forward
      is already dead since :8000 is loopback-bound, but removing it deletes
      the stale config and any router-side logging noise.
- [ ] **If remote access is still needed now:** add forward WAN 443 →
      192.168.0.4:443 (traffic is TLS; acceptable but keeps a public surface).
- [ ] **Preferred end state (Tailscale):** install Tailscale on this Mac and
      every client device, join them all to one tailnet, then **remove every
      WAN forward** and reach the dashboard at `https://<mac-tailscale-ip>`
      (or an HTTPS-enabled MagicDNS name). No cert warnings, no public ports.
- [ ] After everyone uses HTTPS only: set `SIMC_COOKIE_SECURE=1` in `.env`
      and `docker compose up -d simc-master`.

## Known trade-offs

- **Self-signed warning / CA trust**: unavoidable without a domain. Cheap
  upgrade path documented in the Caddyfile header.
- **No HSTS** on purpose (HSTS + internal CA = browser lockout risk).
- **Rate limiting sees one IP**: `client_ip()` deliberately ignores proxy
  headers, so behind Caddy all browser traffic appears as the Caddy
  container. Fine for a single-operator app; if multi-user, add uvicorn
  `--forwarded-allow-ips`/`--proxy-headers` *and* restrict master to the
  compose network first.
- **Caddy runs as root in-container** (needs :443 bind). Acceptable; switch
  to `caddy:2-alpine-caddyuser` + sysctl if hardened later.

## Rollback

```bash
cd ~/Projects/simc_helper
git revert <this commit>          # removes caddy service + loopback bind
docker compose up -d              # master republishes 0.0.0.0:8000
docker compose rm -sf caddy && docker volume rm simc_helper_caddy-data simc_helper_caddy-config
```
Or without reverting: `MASTER_BIND=0.0.0.0 docker compose up -d simc-master`
restores the old cleartext exposure instantly (not recommended).
