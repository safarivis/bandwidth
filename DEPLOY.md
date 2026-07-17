# Deploy & Hosting — Initiative Control Board

## 1. Single-customer on a VPS (works today)

One instance = one customer. Each instance reads that customer's synced repo.

**Prereqs on the VPS:** Python 3, `git`, the customer's data repo synced to a path (e.g. `/srv/board/<customer>/repo`), and — for the Claude-powered actions — the `claude` CLI installed and authenticated **as that customer** (Gmail connector etc.).

**a. Config** — set `repo_root` in `data.json` (or `BOARD_REPO` env) to the synced repo; set `client`/`client_dir`; fill `registry.csv`.

**b. systemd service** (`/etc/systemd/system/board-<customer>.service`):
```ini
[Unit]
Description=Initiative Board — <customer>
After=network.target
[Service]
User=board
Environment=BOARD_REPO=/srv/board/<customer>/repo
WorkingDirectory=/srv/board/<customer>/initiative-board
ExecStart=/usr/bin/python3 server.py
Restart=always
[Install]
WantedBy=multi-user.target
```
`systemctl enable --now board-<customer>`. The server binds `127.0.0.1:8787` — never expose it directly.

**c. Reverse proxy + TLS + auth** (nginx) — the board has **no built-in auth**, so the proxy must gate it:
```nginx
server {
  server_name <customer>.board.lewkai.com;
  location / {
    auth_basic "Board"; auth_basic_user_file /etc/nginx/board.htpasswd;   # or OAuth (oauth2-proxy)
    proxy_pass http://127.0.0.1:8787;
  }
  # + certbot TLS
}
```
Give each customer their own subdomain → their own instance/port.

## 2. The gap to a subscription product (roadmap — not built yet)

Being honest about what "sell under subscription to many users" needs beyond today's single-tenant tool:

| Piece | Status | What's needed |
|---|---|---|
| **Auth / accounts** | ❌ none | App-level login or oauth2-proxy in front; per-user sessions. |
| **Multi-tenant** | ⚠️ one-instance-per-customer works | Either keep instance-per-customer (simple, strong data isolation — recommended first) orchestrated by a systemd template + subdomain router, OR build a real tenant layer (customer switcher, per-tenant repo + auth). Start with instance-per-customer. |
| **Claude actions when hosted** | ✅ solved — BYO Claude | Each customer authenticates their **own Claude subscription** on their instance (one-time `claude` login + connect Gmail etc.). Actions run under their sub — no per-customer auth work on our side, and every hosted customer gets full actions. Their usage is billed to their own Claude account. |
| **Data sync** | per-deploy | Each customer's repo must sync to the VPS (git pull cron / a moeba-style daemon). |
| **Billing** | ❌ | Separate layer (e.g. Stripe) gating access. Out of the tool itself. |
| **Generalise integrations** | ⚠️ RevvTech-specific | CRM / Gmail / Lewkai-sheet actions are keyed to the RevvTech repo. Make them per-customer plugins or feature-flag them off. |

**Recommended first commercial step:** instance-per-customer behind nginx (subdomain + basic auth). Customer does a one-time `claude` login on their instance (their **own** subscription) → full actions work immediately, billed to their Claude account. Add real accounts + billing (for *our* subscription fee) once 1–2 paying customers validate it.

**Onboarding a customer (self-service BYO-Claude):** (1) spin up their instance + subdomain; (2) point `repo_root` at their synced repo, fill `registry.csv`; (3) they run `claude` login once on the instance and connect Gmail; (4) done — views + actions live.

## Live instances

| URL | Box | Path | Service | Port | Notes |
|---|---|---|---|---|---|
| https://bandwidth.lewkai.com | srv1301748 (72.62.235.141) | `/srv/bandwidth/main/` | `bandwidth-main` | 8791 | **Client: Kelly** (first client). nginx + basic-auth + TLS. **Kelly's own Claude** is authed on the box → actions run and bill on her subscription. |

Basic-auth user `kelly`. Runs as root for now — harden to a dedicated `bandwidth` user later.

**⚠️ Per-instance files are customer-specific:** `data.json` and `registry.csv` in `/srv/bandwidth/main/app/` belong to Kelly. When pushing code updates, **exclude them** from rsync (`--exclude data.json --exclude registry.csv`) so you don't overwrite her config/initiatives.

## 3. Local use (RevvTech/HL today)
`./start.sh` — restarts + opens `http://127.0.0.1:8787`. Reads `~/revvtech` per `data.json`.
