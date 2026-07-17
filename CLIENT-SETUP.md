# Bandwidth — client setup (the framework)

Bandwidth is the **structure**; you bring **your own repo + content**. Each client is fully self-contained — your own folder/files, your own initiatives. Nothing about another client's setup touches yours.

## The only thing you must do: fill `registry.csv`
List *your* initiatives — one row each. Columns:

| Column | Meaning | Required |
|---|---|---|
| `code` | your ID for it (e.g. `PRJ-01`) | optional |
| `name` | what it is | ✅ |
| `type` | project / agent / initiative | optional |
| `sponsor` / `contact` | who owns it / who to chase | optional |
| `repo_path` | folder for this item in *your* repo (used for git activity) | optional |
| `status_file` | the file the board reads/writes status to (any path you choose) | optional (defaults under repo_path) |
| `dept` | grouping for the filter | optional |

Point `repo_root` (in `data.json` or env `BOARD_REPO`) at your repo, set `client`/`client_dir`, and you're live.

## You don't need any pre-existing structure
The board **creates and manages** the status files itself. As you use it:
- **drag** a block to a stage, or **edit its status text** → the board writes a `**Status:**` line into that item's `status_file` (creating it if needed).
- **★ Priority**, **Criticality**, and activity notes are written as small markers in the same file.

So a brand-new client can start with just a `registry.csv` of names and build everything from the board.

## Optional enrichments (light conventions that "light up" extra signals)
Adopt any of these in *your* repo and Bandwidth uses them automatically; skip them and nothing breaks:

| Convention | What it adds |
|---|---|
| A `**Status:** <stage> — <note>` line in each `status_file` | stage colour + status text (the board writes these for you anyway) |
| Your repo is a **git** repo | "days since last movement" + stale flags (tamper-proof) |
| A `docs/ACTION-ITEMS.md` with dated rows mentioning an item's `code` + a "waiting/blocked" word | auto-detected blockers in "Why it's red" + the Today page |
| A `LOOP_HEALTH.md` naming your live agents PASS/FAIL | live-agent health → red on FAIL |

## Integrations (per-client, off by default)
The CRM time-log, Gmail drafts, and the Lewkai sheet are **RevvTech-specific** and keyed to that repo. For your instance they're either reconfigured to your tools or left off — the core board (views, status, priority, risk, chat) is fully generic.

## Your AI (BYO Claude)
The action buttons (draft / resolve / next-step / chat) run on **your own Claude subscription** — you log in `claude` once on your instance. Your usage, your account.
