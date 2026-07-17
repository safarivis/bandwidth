# Bandwidth — single-customer VPS deploy (step 1)

One instance per customer: isolated by port + subdomain, gated by nginx (auth + TLS). Full rationale + roadmap in `../DEPLOY.md`.

## One-time on the VPS
- `sudo useradd -r -m bandwidth` (service user)
- install `nginx` + `certbot` (`python3-certbot-nginx`)
- `sudo mkdir -p /srv/bandwidth /etc/nginx/bandwidth`

## Per customer `<name>`
1. **App:** copy this product → `/srv/bandwidth/<name>/app`.
2. **Data repo:** sync the customer's repo → `/srv/bandwidth/<name>/repo` (git-pull cron or a sync daemon).
3. **Config:** `cp deploy/env.example /srv/bandwidth/<name>/env` → set `BOARD_REPO` + a **unique** `BOARD_PORT`. Edit `app/data.json` (`client`, `client_dir`) and `app/registry.csv`.
4. **Service:** `sudo cp deploy/bandwidth@.service /etc/systemd/system/` → `sudo systemctl enable --now bandwidth@<name>`.
5. **Proxy + TLS:** fill `nginx-bandwidth.conf.tmpl` (`{{CUSTOMER}}`, `{{PORT}}`) → `/etc/nginx/sites-enabled/bandwidth-<name>`; `sudo htpasswd -c /etc/nginx/bandwidth/<name>.htpasswd <user>`; `sudo nginx -t && sudo systemctl reload nginx`; `sudo certbot --nginx -d <name>.bandwidth.lewkai.com`.
6. **BYO Claude:** on the instance, the customer runs `claude` login once + connects Gmail → actions go live under their own subscription.

**Verify:** `systemctl status bandwidth@<name>` and open `https://<name>.bandwidth.lewkai.com`.
