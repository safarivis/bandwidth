# Next session — make onboarding a new client genuinely self-serve

Paste the block below into a fresh session to continue.

---

Continue building **Bandwidth** (a Lewkai product). This session's goal: **make onboarding a NEW client genuinely self-serve** — from "sign up" to "using their board with their own AI" with minimal/no manual ops.

**What it is:** a local-hosted visual control board — one screen to track projects/agents, derive honest status live from a repo, and act via the user's own Claude (draft / resolve / log / chat; human approves).

**Where:** product code lives at `~/ldp/projects/lewkai/bandwidth/` — its own git repo (`github.com/safarivis/bandwidth`; ship with `./ship.sh "msg" [instance]`). **Read first:** `README.md`, `VISION.md`, `DESIGN.md` (Apple/monochrome theme — stay on it), `DEPLOY.md`, `CLIENT-SETUP.md`, `ONBOARDING.md`, `docs/PLAN.md`, then skim `server.py` + `board.html`.

**Architecture:** `server.py` (Python stdlib HTTP, binds 127.0.0.1, derives status from the repo, runs scoped `claude -p` actions) + `board.html` (single file: Today/Kanban/Funnel/Delays views, welcome onboarding, ＋Add). Config per deployment via `data.json` + env (`BOARD_REPO`, `BOARD_CLIENT`, `BOARD_CLIENT_DIR`, `BOARD_PORT`); the initiative list is `registry.csv` in the client's repo_root.

**Hosting model (DEPLOY.md):** one sandboxed instance per client on VPS `72.62.235.141` — dedicated `bw-<client>` user, framework read-only, systemd `ProtectSystem=strict` (only their data writable), nginx subdomain + basic-auth + TLS. First client **Kelly** is live at https://bandwidth.lewkai.com. Deploy key: `~/.ssh/lewkai_deploy`; DNS wildcard `*.bandwidth.lewkai.com`.

**BYO-Claude:** each client authenticates their own Claude via `claude setup-token`; the token is stored at `~/.bandwidth-claude-token` and injected into every `claude` call by `_claude_env()`. There's an in-UI "Connect Claude" flow (`/api/claude/start` + `/api/claude/finish`) — **start is proven (captures the auth URL); finish is NOT yet live-tested end-to-end.**

**The work:**
1. **Finish + live-test the in-UI Connect-Claude flow** (paste code → store token). Tune the token-capture parse against real output.
2. **Automate provisioning** — turn the manual DEPLOY.md runbook into a `provision.sh <client>`: create the user, `/srv/bandwidth/<client>/{app,data}`, env, systemd service, nginx site + TLS, seed an empty `registry.csv`.
3. **Polish first-run** — empty welcome → Connect Claude → ＋Add → organise → Today; obvious and Apple-clean.

**Constraints:** KISS; never weaken the sandbox/isolation; human-in-the-loop (email = drafts only, no auto-send/push); test live, no "done" without evidence; per-client `data.json`/`registry.csv` must not be clobbered on deploy (ship.sh excludes them). **Propose the provisioning approach before building.**

---

## State at handoff (2026-07-17)
- Product live for client **Kelly** at https://bandwidth.lewkai.com (basic-auth `kelly`), her own Claude connected (token stored + injected).
- Own repo pushed: `github.com/safarivis/bandwidth` (proprietary licence, `ship.sh` one-command deploy, infra in gitignored `.deploy.env`).
- Board reads each initiative's **own room ACTION-ITEMS** now (folder work reflects); **live agents stay green** (stale build blockers suppressed).
- HL still runs as a local instance: `BOARD_REPO=~/revvtech BOARD_CLIENT_DIR=clients/hungry-lion BOARD_CLIENT="Hungry Lion" BOARD_PORT=8789 python3 server.py`.

## Open loops
- Rotate Kelly's Claude token (it was pasted in a chat once).
- Send Kelly her password via a separate channel.
- Repo → `adh.revvtech.com` dashboard sync is still manual (option A "Dashboard sync" view was proposed, not built).
