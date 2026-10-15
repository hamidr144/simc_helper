# TLS fronting — external host infrastructure

Status: **not part of this project** (since 2026-10-16, task `t_6da4607e`) · Owner: devops

The stack serves **plain HTTP on `127.0.0.1:8000`** (knobs: `MASTER_BIND`,
`PORT`). TLS termination and domain routing are **host infrastructure, not
part of this project**: `docker compose up -d` must work with zero config and
no TLS/domain dependency. The in-compose Caddy service and `deploy/caddy/`
were removed in `t_6da4607e`. On the operator's host the front lives at
`~/Hermes-work/infra/caddy/` (own compose project + cert volumes, host-owned).

History: `t_d034f7e9` (2026-10-14, audit HIGH-2 — cleartext WAN HTTP) shipped
a Caddy TLS front inside compose. Coupling a run-with-one-command project to a
TLS/domain front was the wrong trade; the front moved to host infra.

## If you want HTTPS

Run any reverse proxy outside this stack. Caddy example (Let's Encrypt):

```caddy
simc.example.com {
    encode zstd gzip
    log
    reverse_proxy 127.0.0.1:8000
}
```

## App-side notes when behind a TLS front

- Set `SIMC_COOKIE_SECURE=1` once all clients reach the app via HTTPS — adds
  the `Secure` attribute to `session_id`/`user_id` cookies (`HttpOnly` and
  `SameSite=Lax` are always set).
- `client_ip()` deliberately ignores proxy headers, so rate limiting sees the
  proxy's IP for every client. Fine for a single operator; if multi-user, add
  uvicorn `--proxy-headers`/`--forwarded-allow-ips` *and* restrict the master
  to the proxy network first.
- No HSTS until a real (non-self-signed) certificate is in place.
