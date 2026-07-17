# Bandwidth — a Lewkai product

**Manage every concern from one screen — and act on it — by leveraging your own AI.** Humans have limited bandwidth; Bandwidth is the framework that extends it. Full pitch: [`VISION.md`](VISION.md).

Track projects, manage delivered AI agents, see honest live status, and act (draft / resolve / log) — all wired to Claude. Built for RevvTech/Hungry Lion first; packaged under Lewkai to sell to HL, RevvTech, and other clients.

**Status:** working product (single-tenant, local/VPS). Multi-tenant subscription hosting = roadmap (see `DEPLOY.md`).

---

## What it does

- **Three views** (toggle top-left): **Today** (priorities · bottlenecks · awaiting-replies with one-click chase), **Kanban** (pipeline by stage), **Funnel** (maturity: ideas at top → live agents as the green foundation at the bottom).
- **Honest, live status** — nothing hand-stored; every field is derived from the customer's repo on each refresh (git activity, status lines, blockers, agent health). A neglected item visibly rots and flags itself.
- **Risk model** — Criticality (Critical/High/Med/Low) × health = Risk. 🔥 marks a High/Critical item that's gone red; a risk filter gives a triage list.
- **★ Priority**, **drag-to-reclassify** (writes back to the repo), **editable status**, **per-block chat with Claude**, **context-aware house-style email drafts**, **per-block time logging**, **reconcile check** (nothing goes missing), **light/dark Apple UI**, **search/filter**.

## Configure (this is what makes it a product, not a one-off)

Everything customer-specific lives in **`data.json`** + **`registry.csv`** — no code changes per customer:

- **`data.json`**
  - `repo_root` — the customer's DATA repo the board reads (or set env `BOARD_REPO`). e.g. `~/revvtech`.
  - `client` / `client_dir` — display name + path within that repo.
- **`registry.csv`** — the initiative list (open in Excel): code, name, type, sponsor, contact, repo_path, status_file, dept, etc.

The HL deployment ships with `repo_root: ~/revvtech`, `client_dir: clients/hungry-lion`.

## Run (local)

```sh
./start.sh        # restarts the engine + opens http://127.0.0.1:8787
```
or `BOARD_REPO=/path/to/customer/repo python3 server.py`.

## Derivation model (why status is trustworthy)

| Field | Source | Trust |
|---|---|---|
| Which initiatives exist | `registry.csv` + auto-scan of `<client_dir>/*/project-room/` | unregistered rooms flagged; reconcile flags codes with docs but no registry row |
| Stage | each initiative's `status_file` **`Status:`** line (first stage word) | `no-status-line` / `no-stage-word` flags when missing |
| Blocker | primary-code-matched OPEN line in `<client_dir>/docs/ACTION-ITEMS.md` | shown as "verify", noise-filtered |
| Movement | `git log` per folder | tamper-proof; >14d idle → 🔴 |
| Live agent health | `LOOP_HEALTH.md` | FAIL → 🔴 |

## Actions (each governance-gated, run via `claude -p` with a scoped allowlist)

| Action | Does | Guardrail |
|---|---|---|
| ✉️ Draft email | gathers context (repo + recent Gmail threads), applies house style, tags subject `[code]`, logs to the block | **Gmail draft only — never sent** |
| 🔧 Resolve / restart agent | investigate LOOP_HEALTH + logs, fix, restart | **no git push** |
| ▶️ Do next build step | scoped next task | **PR/draft only** |
| ⏱ Log time | CRM + client file + workspace timelog + Lewkai sheet | CRM-first, safe-retry |

> The CRM / Gmail / Lewkai-sheet integrations are **RevvTech-specific** (keyed off the customer repo's skills + config). For a non-RevvTech customer these are reconfigured or disabled — see `DEPLOY.md`.

## Files
- `server.py` — engine: live derivation + JSON API + scoped Claude actions. Binds 127.0.0.1.
- `board.html` — single-file UI (3 views, detail panel, actions, chat, theme).
- `data.json` — per-deployment config. `registry.csv` — the initiative list.
- `start.sh` — launcher. `DEPLOY.md` — VPS hosting + the path to subscription/multi-tenant.
