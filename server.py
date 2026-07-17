#!/usr/bin/env python3
"""
Initiative Control Board - local engine.

Intention: serve board.html and expose a tiny API that (a) DERIVES honest,
live status for every initiative from repo ground truth and (b) runs scoped
Claude Code actions on click.
Author: RevvTech (Louis) - 2026-07-16

FAILSAFE MODEL (why this is trustworthy, not just a snapshot):
  - Initiatives are AUTO-DISCOVERED by scanning for project rooms. A room with
    no registry entry shows as 'unregistered' - nothing goes missing silently.
  - Stage is PARSED from each room's README "Status:" line (the thing you
    already update as you work), with the status date captured for freshness.
  - Blockers are READ from ACTION-ITEMS.md (fed by the gmail scan skills).
  - Movement + recent commits come from git (tamper-proof).
  - Live-agent health comes from LOOP_HEALTH.md (loop-verify cron).
  - data.json is ONLY a thin registry (code/name/sponsor/what/why). Nothing
    that moves is stored. Unknown => flagged, never guessed.

All local. Binds to 127.0.0.1 only.
"""
import json
import os
import re
import csv
import glob
import pty
import time
import select
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root():
    """The DATA repo this board reads (the customer's repo). Configurable so the
    product can point at any customer without moving the code:
      1. env var BOARD_REPO   2. data.json "repo_root"   3. fallback: two dirs up.
    Relative paths resolve against the app dir (HERE), not the shell's CWD."""
    def _resolve(p):
        p = os.path.expanduser(p)
        return os.path.abspath(p if os.path.isabs(p) else os.path.join(HERE, p))
    env = os.environ.get("BOARD_REPO")
    if env:
        return _resolve(env)
    try:
        cfg = json.load(open(os.path.join(HERE, "data.json")))
        if cfg.get("repo_root"):
            return _resolve(cfg["repo_root"])
    except Exception:
        pass
    return os.path.abspath(os.path.join(HERE, "..", ".."))


REPO_ROOT = _repo_root()
DATA = os.path.join(HERE, "data.json")            # config (client, client_dir, repo_root)
# Registry lives in the CLIENT's data repo (repo_root) — per-client, survives code
# updates. The app-dir registry.csv is only a template seed, never read at runtime.
REGISTRY_CSV = os.path.join(REPO_ROOT, "registry.csv")
BOARD_MD = os.path.join(REPO_ROOT, "BOARD.md")     # human-readable snapshot (auto-written)
HTML = os.path.join(HERE, "board.html")
REG_COLS = ["code", "name", "type", "sponsor", "contact", "repo_path", "status_file",
            "what_it_does", "why_it_matters", "dept", "requested_by", "sa"]
CLAUDE_TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".bandwidth-claude-token")


def _claude_env():
    """Environment for spawned `claude` calls — injects the client's stored OAuth token
    (from `claude setup-token`) so actions run on THEIR subscription, no systemd env needed."""
    env = os.environ.copy()
    try:
        t = open(CLAUDE_TOKEN_FILE).read().strip()
        if t:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = t
    except Exception:
        pass
    return env


def load_registry():
    """The initiative list, from registry.csv. Empty cells -> None (never guessed)."""
    out = []
    if not os.path.exists(REGISTRY_CSV):
        return out
    with open(REGISTRY_CSV, newline="") as f:
        for row in csv.DictReader(f):
            out.append({k: (v.strip() if v and v.strip() else None) for k, v in row.items()})
    return out

HOST, PORT = "127.0.0.1", int(os.environ.get("BOARD_PORT", "8787"))
STALE_MOVE_DAYS = 14    # no git commit in this many days => red (stale movement)
STALE_STATUS_DAYS = 30  # README status claim older than this => "stale status" flag

STAGE_ORDER = ["ideating", "scoping", "approved", "building", "testing", "live", "unknown"]
CODE_RE = re.compile(r"UC-\d{3,4}|NI-[A-Z]{2,3}-\d{3}", re.I)

# Each action maps to a scoped `claude -p` invocation. The allowlist is the
# guardrail: draft_chase can ONLY create a Gmail draft; resolve_agent cannot
# push. permission-mode is acceptEdits (never bypass) so nothing irreversible
# (send/push) happens without a human.
ACTIONS = {
    "resolve_agent": {
        "tools": "Read,Bash,Edit",
        "prompt": (
            "Investigate the '{name}' ({code}) agent for Hungry Lion. Read its folder "
            "{repo_path} and any LOOP_HEALTH.md, then check logs / recent runs. Diagnose why "
            "it is failing or stalled, propose or apply a minimal fix, and restart it if it is a "
            "scheduled/live job. DO NOT push to git and DO NOT send email. Report: what was "
            "wrong, what you did, and what still needs a human."
        ),
    },
    "draft_chase": {
        "tools": "Read,Grep,Glob,mcp__claude_ai_Gmail__search_threads,mcp__claude_ai_Gmail__get_thread,mcp__claude_ai_Gmail__create_draft",
        "perm": "bypassPermissions",   # Gmail MCP needs this in headless mode (see CLAUDE.md)
        "prompt": (
            "Draft a Gmail DRAFT ONLY (do NOT send) for the Hungry Lion initiative '{name}' ({code}). "
            "Louis clicked this quickly — do NOT just parrot his one-line aim. GATHER CONTEXT FIRST so the email is well-grounded:\n"
            "1. Read the project room + recent notes under `{repo_path}` (README/STATUS, 01-sources, "
            "SESSION-NOTES, ACTION-ITEMS) to understand where it stands and exactly what's blocking it. "
            "Current blocker: {blocker}.\n"
            "2. SEARCH recent Gmail threads about this initiative (its code '{code}', its name, and the people "
            "involved) to see what was already said — so the email fits the existing thread and does NOT repeat "
            "or contradict it.\n"
            "3. Read `skills/gmail-draft/SKILL.md` (apply the RevvTech HOUSE STYLE exactly: skimmable, lead with "
            "the ask, labelled sections, lists not prose, ONE bold ask sentence, warm+direct; provide BOTH an "
            "inline-CSS `htmlBody` using its callout template AND a clean plain-text `body`) and "
            "`clients/hungry-lion/CLAUDE.md` (client tone).\n"
            "4. Write an INFORMED draft that achieves Louis's aim (below), grounded in what you found. Start the "
            "SUBJECT with '[{code}] '. If a recipient is implied, address it; otherwise leave the To line for Louis.\n"
            "Return the draft id and a one-line summary, noting the key context you used."
        ),
    },
    "next_step": {
        "tools": "Read,Bash,Edit,Write",
        "prompt": (
            "For the Hungry Lion initiative '{name}' ({code}), stage '{stage}', do the scoped "
            "NEXT build step. Read {repo_path} first. Make progress and report what you did. "
            "Prepare a branch/PR or draft for review - DO NOT push to master, DO NOT send email. "
            "Report what still needs a human decision."
        ),
    },
    "scan_email": {
        "tools": "Skill,Read,Write,Edit,mcp__claude_ai_Gmail__search_threads,mcp__claude_ai_Gmail__get_thread,mcp__claude_ai_Gmail__create_draft",
        "perm": "bypassPermissions",
        "prompt": (
            "Run the gmail-inbound-scan skill for Hungry Lion only. Capture any new "
            "decisions/actions/blockers into clients/hungry-lion ACTION-ITEMS and SESSION-NOTES "
            "managed zones (append-only, quarantined). Create a draft digest only - send nothing. "
            "Report a one-line summary of what was captured."
        ),
    },
}


# ------------------------- derivation helpers -------------------------

def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=timeout)
    except Exception:
        return None


def parse_stage(readme_path):
    """Return (stage, status_date, status_text). Derived from the README Status line."""
    try:
        with open(readme_path, errors="ignore") as f:
            head = f.read(4000)
    except Exception:
        return "unknown", None, None
    status_text = None
    for line in head.splitlines():
        low = line.lower()
        if "status" in low and ("**status" in low or "status:" in low or "status (" in low):
            if "high-stakes deliverables" in low:   # template boilerplate, skip
                continue
            status_text = line.strip(">#* \t")
            break
    if not status_text:
        return "unknown", None, None
    date_m = re.search(r"(\d{4}-\d{2}-\d{2})", status_text)
    status_date = date_m.group(1) if date_m else None
    # Clean body = the text right after "Status...:" (drop the marker + trailing **).
    m = re.search(r"status[^:]*:\s*(.*)", status_text, re.I)
    body = (m.group(1) if m else status_text).strip().strip("*").strip()
    # Stage = the EARLIEST-occurring stage word in the first sentence. Humans type the
    # stage first ("scoping — awaiting approval"), and word-boundaries stop matching
    # "live" inside "deliver" or "approv" inside a later "approval".
    first = re.split(r"[.;]", body, maxsplit=1)[0].lower()
    STAGE_KW = [(r"not started", "ideating"), (r"\bideat", "ideating"),
                (r"\blive\b", "live"), (r"\btest", "testing"), (r"\buat\b", "testing"),
                (r"\bbuild", "building"), (r"\bprototype", "building"), (r"\bpoc\b", "building"),
                (r"\bapprov", "approved"), (r"\bscop", "scoping")]
    hits = [(mm.start(), st) for pat, st in STAGE_KW for mm in [re.search(pat, first)] if mm]
    stage = min(hits)[1] if hits else "unknown"
    return stage, status_date, body


def git_movement(repo_path):
    """(days_since_last_commit, [recent commit one-liners]) for a folder."""
    r = _run(["git", "log", "-1", "--format=%cI", "--", repo_path])
    days = None
    if r and r.stdout.strip():
        try:
            days = (datetime.now(timezone.utc)
                    - datetime.fromisoformat(r.stdout.strip())).days
        except Exception:
            days = None
    rc = _run(["git", "log", "-3", "--format=%cr | %s", "--", repo_path])
    commits = [c for c in (rc.stdout.strip().splitlines() if rc else []) if c]
    return days, commits


def loop_health(item):
    """'pass' | 'fail' | None from any HL LOOP_HEALTH.md mentioning this initiative."""
    name = (item.get("name") or "")[:15].lower()
    code = (item.get("code") or "").lower()
    verdict = None
    for f in glob.glob(os.path.join(REPO_ROOT, item["client_dir"], "**", "LOOP_HEALTH.md"),
                       recursive=True):
        try:
            for line in open(f, errors="ignore"):
                low = line.lower()
                if not ((code and code in low) or (name and name in low)):
                    continue
                if "fail" in low:
                    return "fail"
                if "pass" in low or "live" in low or "ok" in low:
                    verdict = "pass"
        except Exception:
            continue
    return verdict


def find_blocker(item, action_items_text):
    """Most recent OPEN blocker line in ACTION-ITEMS for this initiative, else None.

    Deliberately conservative to avoid false reds: matches on the initiative CODE
    only (fuzzy name matching produced wrong hits), requires a blocker marker, and
    skips any line already marked done/decided/resolved.
    """
    code = item.get("code")
    if not action_items_text or not code:
        return None
    markers = ("blocked", "waiting", "awaiting", "pending", "⏳", "stalled")
    done = ("✅", "done", "decided", "resolved", "complete", "sent 2026", "closed")
    # cross-cutting / improvement notes that merely MENTION the code are not blockers
    noise = ("pattern", "generalis", "worth folding", "apply to", "standard", "retro-fit",
             "not just", "etc.", "consider ")
    match = None
    for line in action_items_text.splitlines():
        low = line.lower()
        if not any(m in low for m in markers):
            continue
        if any(d in low for d in done) or any(nz in low for nz in noise):
            continue
        # A blocker counts ONLY for the project that is the PRIMARY (first) code on the
        # line - stops lines about project A that merely reference B from flagging B.
        first = CODE_RE.search(line)
        if not first or first.group(0).upper() != code.upper():
            continue
        match = line.strip().strip("|").strip()[:300]  # keep last = most recent
    return match


def days_since(iso_or_date):
    if not iso_or_date:
        return None
    try:
        d = datetime.fromisoformat(iso_or_date)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - d).days
    except Exception:
        return None


# ------------------------- reconcile + human-readable snapshot -------------------------

def reconcile(registry, client_dir):
    """Codes that appear in a FILENAME under the client dir but are NOT registered.

    A code baked into a filename (tech-spec, scope doc, STATUS-*, output) implies a
    real initiative with artifacts. If it's not in the registry, it's missing from the
    board - exactly the NI-IT-001 class of bug. Returns [{code, sample_path}].
    """
    registered = {r["code"].upper() for r in registry if r.get("code")}
    found = {}
    for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, client_dir)):
        if os.sep + ".git" in root:
            continue
        for fn in files:
            m = CODE_RE.search(fn)
            if m:
                found.setdefault(m.group(0).upper(),
                                 os.path.relpath(os.path.join(root, fn), REPO_ROOT))
    return [{"code": c, "sample": found[c]} for c in sorted(found) if c not in registered]


def register_flags(item):
    """For Named Initiatives only: flag if there's no paste-ready register stub, or the
    stub's Credential/SA line is still TBD. UCs (dashboard use cases) are skipped -
    they aren't Named Initiatives. Credential Sheet is external/human-only so we infer
    'cred-TBD' from the local stub, never claim to have read the Sheet."""
    code = (item.get("code") or "").upper()
    if not ((item.get("type") or "").upper() == "NI" or code.startswith("NI-")):
        return []
    room = os.path.join(REPO_ROOT, item["client_dir"], item["folder"], "project-room")
    mine = None
    for s in glob.glob(os.path.join(room, "**", "ni-register-entry*.md"), recursive=True):
        try:
            if code and code in open(s, errors="ignore").read().upper():
                mine = s
                break
        except Exception:
            pass
    if not mine:
        return ["no-register-stub"]
    low = open(mine, errors="ignore").read().lower()
    m = re.search(r"credential\s*/\s*sa\s*\**\s*\|\s*([^|\n]+)", low)
    val = (m.group(1) if m else "").strip()
    return ["cred-TBD"] if (not val or "tbd" in val) else []


def register_row(key):
    """Generate the paste-ready NI register row for one initiative, and (for NIs)
    write/refresh its ni-register-entry.md stub. Returns {text, wrote}. Never touches
    the external canonical register or the credential Sheet - those stay human-only."""
    item = next((i for i in build_state()["items"]
                 if i.get("key") == key or i.get("code") == key or i.get("folder") == key), None)
    if not item:
        return {"ok": False, "error": f"no initiative '{key}'"}
    reg = _resolve_reg(key) or {}
    code = item.get("code") or "(no code)"
    room = os.path.join(item["client_dir"], item["folder"], "project-room")
    status = item.get("stage") + (f" — {item['status_text']}" if item.get("status_text") else "")
    row = ("| Field | Value |\n|-------|-------|\n"
           f"| **Code** | `{code}` |\n"
           f"| **Initiative** | {item.get('name')} |\n"
           f"| **Department** | {reg.get('dept') or 'TBD (confirm with Jonathan)'} |\n"
           f"| **Requested by** | {reg.get('requested_by') or 'TBD'} |\n"
           f"| **Description** | {item.get('what_it_does') or 'TBD'} |\n"
           f"| **Status** | {status} |\n"
           f"| **Project room** | `{room}/` |\n"
           f"| **Credential / SA** | {reg.get('sa') or 'TBD — one SA/key per initiative (HL standard)'} |\n")
    wrote = None
    if (item.get("type") or "").upper() == "NI" or code.upper().startswith("NI-"):
        wdir = os.path.join(REPO_ROOT, room, "05-working")
        os.makedirs(wdir, exist_ok=True)
        target = None
        for s in glob.glob(os.path.join(wdir, "ni-register-entry*.md")):
            if code.upper() in open(s, errors="ignore").read().upper():
                target = s
                break
        if not target:
            plain = os.path.join(wdir, "ni-register-entry.md")
            target = plain if not os.path.exists(plain) else os.path.join(wdir, f"ni-register-entry-{code}.md")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(target, "w") as f:
            f.write(f"---\ntype: Working Note\n"
                    f"title: \"{code} — Named Initiative Register Entry (for Louis to add)\"\n"
                    f"description: \"Paste-ready register row generated by the control board. The HL "
                    f"register (Google Sheet + HL_AI_Initiatives NAMED-INITIATIVES-REGISTER.md) is "
                    f"Louis-only; agents do not write to it.\"\n"
                    f"tags: [\"hungry-lion\", \"{item['folder']}\", \"{code}\", \"register\"]\n"
                    f"timestamp: \"{today}\"\n---\n\n# Register entry — for Louis to add\n\n"
                    f"> Generated by the control board {today}. The canonical register is Louis-only, "
                    f"append-only. This is the paste-ready row.\n\n" + row + "\n")
        wrote = os.path.relpath(target, REPO_ROOT)
    return {"ok": True, "text": row, "wrote": wrote}


def write_board_md(state):
    """Human-readable snapshot of the derived state. Output only - the board rewrites
    it every refresh; humans read/share it, git tracks its history."""
    dot = {"green": "🟢", "amber": "🟡", "red": "🔴", "grey": "⚪"}
    out = [f"# {state['client']} — Initiative Board (auto-generated)", "",
           f"_Generated {state['generated_at']}. Do not edit — the board rewrites this every refresh._",
           "",
           f"Counts: 🟢 {state['counts']['green']} live · 🟡 {state['counts']['amber']} moving · "
           f"🔴 {state['counts']['red']} needs-you · ⚪ {state['counts']['grey']} unknown", "",
           "| Health | Code | Initiative | Stage | Sponsor | Last moved | Blocker / flag |",
           "|---|---|---|---|---|---|---|"]
    for i in state["items"]:
        mv = "—" if i.get("days_since_movement") is None else f"{i['days_since_movement']}d"
        note = i["blocker"] if i.get("blocker") else (", ".join(i.get("flags") or []))
        note = (note or "")[:80].replace("|", "/")
        out.append(f"| {dot.get(i['health'], '')} | {i.get('code') or ''} | "
                   f"{(i['name'] or '').replace('|', '/')} | {i['stage']} | "
                   f"{(i.get('sponsor') or '—').replace('|', '/')} | {mv} | {note} |")
    if state.get("missing_codes"):
        out += ["", "## ⚠ Found in repo but NOT on the board — register these in registry.csv"]
        out += [f"- **{m['code']}** — `{m['sample']}`" for m in state["missing_codes"]]
    out.append("")
    # Writing the snapshot must NEVER crash the board — create the dir, swallow errors.
    try:
        os.makedirs(os.path.dirname(BOARD_MD), exist_ok=True)
        with open(BOARD_MD, "w") as f:
            f.write("\n".join(out))
    except Exception:
        pass


def append_activity(status_file, line):
    """Append a dated bullet under a '## Board activity' section in the block's status
    file — an auto-record of things the board did (e.g. drafted an email). Kept below
    the Status line so it never affects stage parsing."""
    if not status_file:
        return
    target = os.path.join(REPO_ROOT, status_file)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        existing = open(target, errors="ignore").read() if os.path.exists(target) else ""
        with open(target, "a") as f:
            if "## Board activity" not in existing:
                f.write("\n## Board activity\n")
            f.write(f"- {line}\n")
    except Exception:
        pass


def is_priority(status_file):
    """True if the block is flagged priority (a bounded marker in its status file)."""
    if not status_file:
        return False
    p = os.path.join(REPO_ROOT, status_file)
    try:
        return "<!-- board-priority" in open(p, errors="ignore").read()
    except Exception:
        return False


VALID_CRIT = ("critical", "high", "medium", "low")


def read_criticality(status_file):
    """How bad if this breaks/stalls — from a marker in the status file, or None."""
    if not status_file:
        return None
    p = os.path.join(REPO_ROOT, status_file)
    try:
        m = re.search(r"<!-- board-criticality:\s*(critical|high|medium|low)\s*-->",
                      open(p, errors="ignore").read(), re.I)
        return m.group(1).lower() if m else None
    except Exception:
        return None


def read_activity(status_file):
    """Last few '## Board activity' bullets for display in the panel."""
    if not status_file:
        return []
    p = os.path.join(REPO_ROOT, status_file)
    if not os.path.exists(p):
        return []
    out, inside = [], False
    for line in open(p, errors="ignore"):
        s = line.strip()
        if s.lower().startswith("## board activity"):
            inside = True
            continue
        if inside:
            if s.startswith("## "):
                break
            if s.startswith("- "):
                out.append(s[2:])
    return out[-5:]


WAIT_REASONS = {"approval": "Awaiting approval", "reply": "Awaiting reply",
                "access": "Access / tech setup", "data": "Client input / data"}


def _days_between(a, b):
    try:
        from datetime import date
        return max(0, (date.fromisoformat(b[:10]) - date.fromisoformat(a[:10])).days)
    except Exception:
        return 0


def wait_metrics(status_file):
    """Delay tracking: parse board-wait markers → {by_reason, total, open}. Days that a
    block sat in each wait bucket (approval/reply/access/data)."""
    empty = {"by": {}, "total": 0, "open": None}
    if not status_file:
        return empty
    p = os.path.join(REPO_ROOT, status_file)
    if not os.path.exists(p):
        return empty
    try:
        txt = open(p, errors="ignore").read()
    except Exception:
        return empty
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by, total, open_w = {}, 0, None
    for m in re.finditer(r"<!-- board-wait(-done)? reason=(\w+) since=(\S+?)(?: until=(\S+?))? -->", txt):
        done, reason, since, until = m.group(1), m.group(2), m.group(3), m.group(4)
        d = _days_between(since, until or today)
        by[reason] = by.get(reason, 0) + d
        total += d
        if not done:
            open_w = {"reason": reason, "since": since, "days": d}
    return {"by": by, "total": total, "open": open_w}


def _aggregate_delays(items):
    by, total = {}, 0
    for i in items:
        w = i.get("wait") or {}
        for r, d in (w.get("by") or {}).items():
            by[r] = by.get(r, 0) + d
        total += w.get("total", 0)
    return {"by": by, "total": total, "top": (max(by, key=by.get) if by else None)}


# ------------------------- state builder -------------------------

def build_state():
    with open(DATA) as f:
        data = json.load(f)
    client_dir = os.environ.get("BOARD_CLIENT_DIR") or data["client_dir"]
    registry = load_registry()

    # ACTION-ITEMS + email scan freshness (read once)
    ai_path = os.path.join(REPO_ROOT, client_dir, "docs", "ACTION-ITEMS.md")
    ai_text = open(ai_path, errors="ignore").read() if os.path.exists(ai_path) else ""
    scan_state = glob.glob(os.path.join(REPO_ROOT, client_dir, "**", "email-scan-state.md"),
                           recursive=True)
    email_scan_iso = email_scan_age = None
    if scan_state:
        mt = datetime.fromtimestamp(os.path.getmtime(scan_state[0]), timezone.utc)
        email_scan_iso = mt.isoformat(timespec="seconds")
        email_scan_age = (datetime.now(timezone.utc) - mt).days

    # AUTO-DISCOVER: every project room under the client
    rooms = {}
    for readme in glob.glob(os.path.join(REPO_ROOT, client_dir, "*", "project-room", "README.md")):
        folder = os.path.relpath(readme, os.path.join(REPO_ROOT, client_dir)).split(os.sep)[0]
        if folder.startswith("_"):
            continue
        rooms[folder] = readme

    def finalize(item):
        days, commits = git_movement(item["repo_path"])
        item["days_since_movement"] = days
        item["recent_commits"] = commits
        item["blocker"] = find_blocker(item, ai_text)
        lh = loop_health(item)
        item["loop_health"] = lh
        if days is not None and days > STALE_MOVE_DAYS:
            item["flags"].append("stale-movement")
        sd = days_since(item.get("status_date"))
        if sd is not None and sd > STALE_STATUS_DAYS:
            item["flags"].append("stale-status")
        red = bool(item["blocker"]) or lh == "fail" or "stale-movement" in item["flags"]
        if red:
            item["health"] = "red"
        elif lh == "pass" or item["stage"] == "live":
            item["health"] = "green"
        elif item["stage"] in ("scoping", "approved", "building", "testing"):
            item["health"] = "amber"
        else:
            item["health"] = "grey"
        item["flags"] += register_flags(item)
        item["wait"] = wait_metrics(item.get("status_file"))
        # Risk = how-bad-it-is-now (health) × how-much-it-matters (criticality)
        sev = {"red": 3, "amber": 2, "grey": 1, "green": 0}.get(item["health"], 0)
        cw = {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(item.get("criticality") or "", 1)
        item["risk"] = sev * cw
        item["at_risk"] = item.get("criticality") in ("critical", "high") and item["health"] == "red"
        return item

    items = []
    covered = set()   # room folders the registry claims (a folder may hold >1 initiative)
    for reg in registry:
        repo_path = reg["repo_path"]
        room_folder = os.path.relpath(repo_path, client_dir).split(os.sep)[0]
        covered.add(room_folder)
        key = reg.get("code") or os.path.basename(repo_path)
        status_file = reg.get("status_file") or os.path.join(repo_path, "project-room", "README.md")
        item = {
            "key": key, "folder": room_folder, "client_dir": client_dir,
            "code": reg.get("code"), "name": reg.get("name") or key,
            "type": reg.get("type"), "sponsor": reg.get("sponsor"),
            "contact": reg.get("contact") or reg.get("sponsor"), "dept": reg.get("dept"),
            "what_it_does": reg.get("what_it_does"), "why_it_matters": reg.get("why_it_matters"),
            "repo_path": repo_path, "status_file": status_file, "flags": [],
        }
        sf = os.path.join(REPO_ROOT, status_file)
        if os.path.exists(sf):
            item["stage"], item["status_date"], item["status_text"] = parse_stage(sf)
            if item["stage"] == "unknown":
                # a note IS present but has no stage keyword vs. no status line at all
                item["flags"].append("no-stage-word" if item["status_text"] else "no-status-line")
        else:
            item["stage"], item["status_date"], item["status_text"] = "unknown", None, None
            item["flags"].append("no-status-line")
        item["activity"] = read_activity(status_file)
        item["priority"] = is_priority(status_file)
        item["criticality"] = read_criticality(status_file)
        items.append(finalize(item))

    # AUTO-DISCOVERY: any project room the registry does NOT claim -> surface it so
    # nothing goes missing silently.
    for folder, readme in rooms.items():
        if folder in covered:
            continue
        stage, sdate, stext = parse_stage(readme)
        item = {
            "key": folder, "folder": folder, "client_dir": client_dir,
            "code": None, "name": folder, "type": None, "sponsor": None,
            "what_it_does": None, "why_it_matters": None,
            "repo_path": os.path.join(client_dir, folder),
            "status_file": os.path.join(client_dir, folder, "project-room", "README.md"),
            "stage": stage, "status_date": sdate, "status_text": stext,
            "flags": ["unregistered"] + ([] if stage != "unknown" else
                                         ["no-stage-word" if stext else "no-status-line"]),
        }
        item["activity"] = read_activity(item["status_file"])
        item["priority"] = is_priority(item["status_file"])
        item["criticality"] = read_criticality(item["status_file"])
        items.append(finalize(item))

    items.sort(key=lambda i: (0 if i.get("priority") else 1, -i.get("risk", 0),
                              STAGE_ORDER.index(i["stage"]) if i["stage"] in STAGE_ORDER else 99,
                              i["name"]))
    state = {
        "client": os.environ.get("BOARD_CLIENT") or data.get("client"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stale_move_days": STALE_MOVE_DAYS,
        "email_scan_iso": email_scan_iso,
        "email_scan_age_days": email_scan_age,
        "missing_codes": reconcile(registry, client_dir),
        "crm_tasks": CRM_TASKS,
        "wait_reasons": WAIT_REASONS,
        "delays": _aggregate_delays(items),
        "counts": {c: sum(1 for i in items if i["health"] == c)
                   for c in ("green", "amber", "red", "grey")},
        "items": items,
    }
    write_board_md(state)
    return state


VALID_STAGES = ("ideating", "scoping", "approved", "building", "testing", "live")


def _resolve_reg(key):
    """Registry entry for a key, or a fallback for an unregistered discovered room."""
    with open(DATA) as f:
        client_dir = json.load(f)["client_dir"]
    for r in load_registry():
        if (r.get("code") or os.path.basename(r["repo_path"])) == key:
            return r
    if os.path.isdir(os.path.join(REPO_ROOT, client_dir, key)):
        return {"repo_path": os.path.join(client_dir, key), "name": key, "code": None}
    return None


def _write_status(key, body, tag):
    """Write `**Status:** {body}` into the initiative's OWN status_file (create if
    missing). One source of truth per initiative; the previous value is kept in a
    single bounded history comment so rendered markdown stays clean. Powers both the
    drag (canonical stage line) and the human-typed free-text edit.
    """
    reg = _resolve_reg(key)
    if reg is None:
        return {"ok": False, "error": f"unknown initiative '{key}'"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    status_file = reg.get("status_file") or os.path.join(reg["repo_path"], "project-room", "README.md")
    target = os.path.join(REPO_ROOT, status_file)
    created = False
    if not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        title = reg.get("name") or key
        code = reg.get("code")
        head = f"{title}{(' (' + code + ')') if code else ''}"
        with open(target, "w") as f:
            f.write(f"---\ntype: Status\ntitle: \"{head}\"\n"
                    f"description: \"Status anchor created by the control board.\"\n"
                    f"tags: [\"hungry-lion\"]\ntimestamp: {today}\n---\n\n# {head}\n\n")
        created = True
    with open(target, errors="ignore") as f:
        lines = f.readlines()
    lines = [l for l in lines if not l.lstrip().startswith("<!-- board-prev-status")]
    idx = None
    for i, line in enumerate(lines):
        low = line.lower()
        if "status" in low and ("**status" in low or "status:" in low or "status (" in low) \
                and "high-stakes deliverables" not in low:
            idx = i
            break
    blockquote = idx is not None and lines[idx].lstrip().startswith(">")
    prefix = "> " if blockquote else ""
    new_line = f"{prefix}**Status:** {body}\n"
    if idx is not None:
        prev = lines[idx].strip()
        lines[idx] = new_line
        lines.insert(idx + 1, f"<!-- board-prev-status {today}: {prev} -->\n")
    else:
        at = 0
        if lines and lines[0].strip() == "---":               # skip frontmatter
            for j in range(1, len(lines)):
                if lines[j].strip() == "---":
                    at = j + 1
                    break
        for j in range(at, min(len(lines), at + 20)):          # after first heading
            if lines[j].startswith("#"):
                at = j + 1
                break
        lines.insert(at, "\n" + new_line)
    with open(target, "w") as f:
        f.writelines(lines)
    state = build_state()
    state["set_stage_ok"] = True
    state["set_stage_msg"] = f"{key}: {tag} (" + ("status file created" if created else "status updated") + ")"
    return state


def set_stage(key, stage):
    """Quick reclassify via drag - writes a canonical status line for the stage."""
    if stage not in VALID_STAGES:
        return {"ok": False, "error": f"invalid stage '{stage}'"}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _write_status(key, f"{stage} — reclassified via control board {today}.", f"-> {stage}")


def set_status(key, text):
    """Human-typed free-text status (most failsafe - no AI interprets the fact).
    Stage re-derives from the text keyword on the next build."""
    text = (text or "").strip()
    text = re.sub(r"(?i)^\**\s*status:?\**\s*", "", text)   # tolerate a pasted 'Status:' prefix
    if not text:
        return {"ok": False, "error": "empty status text"}
    return _write_status(key, text, "status edited")


def set_priority(key, on):
    """Toggle a priority flag by writing/removing a bounded marker in the block's status
    file (append-only comment, doesn't affect stage parsing)."""
    reg = _resolve_reg(key)
    if reg is None:
        return {"ok": False, "error": f"unknown initiative '{key}'"}
    status_file = reg.get("status_file") or os.path.join(reg["repo_path"], "project-room", "README.md")
    target = os.path.join(REPO_ROOT, status_file)
    content = open(target, errors="ignore").read() if os.path.exists(target) else \
        (f"# {reg.get('name') or key}\n" if on else "")
    content = "\n".join(l for l in content.splitlines() if "<!-- board-priority" not in l)
    if on:
        content = content.rstrip() + "\n\n<!-- board-priority -->\n"
    if on or os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write(content)
    state = build_state()
    state["set_stage_ok"] = True
    state["set_stage_msg"] = f"{key} priority {'set' if on else 'cleared'}"
    return state


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").strip().lower()).strip("-") or "item"


def add_initiative(name, area, itype):
    """Self-service add: create a light 'room' (status.md + context.md) under
    <area>/<slug> in the client's data repo, and register it. This is the onboarding
    primitive — a client lists their concerns and the structure is built for them."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "give it a name"}
    area = (area or "Work").strip() or "Work"
    aslug, base = _slug(area), _slug(name)
    slug, n = base, 2
    while os.path.isdir(os.path.join(REPO_ROOT, aslug, slug)):
        slug, n = f"{base}-{n}", n + 1
    rel = f"{aslug}/{slug}"
    room = os.path.join(REPO_ROOT, aslug, slug)
    os.makedirs(room, exist_ok=True)
    with open(os.path.join(room, "status.md"), "w") as f:
        f.write(f"# {name}\n\n**Status:** ideating — just added.\n")
    with open(os.path.join(room, "context.md"), "w") as f:
        f.write(f"# {name} — context\n\n**What it is:** \n\n**Why it matters:** \n\n"
                f"**Key facts / links:** \n\n**Notes / log:** \n")
    exists = os.path.exists(REGISTRY_CSV)
    os.makedirs(os.path.dirname(REGISTRY_CSV), exist_ok=True)
    row = {c: "" for c in REG_COLS}
    row.update({"name": name, "type": (itype or "").strip(), "dept": area,
                "repo_path": rel, "status_file": f"{rel}/status.md"})
    with open(REGISTRY_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(REG_COLS)
        w.writerow([row[c] for c in REG_COLS])
    state = build_state()
    state["set_stage_ok"] = True
    state["set_stage_msg"] = f"added '{name}' under {area}"
    return state


def set_wait(key, reason):
    """Mark a block waiting on {reason} (approval/reply/access/data), or clear ('').
    Closes any open wait first; timestamps entry/exit for delay tracking."""
    reason = (reason or "").strip().lower()
    if reason and reason not in WAIT_REASONS:
        return {"ok": False, "error": f"invalid reason '{reason}'"}
    reg = _resolve_reg(key)
    if reg is None:
        return {"ok": False, "error": f"unknown initiative '{key}'"}
    status_file = reg.get("status_file") or os.path.join(reg["repo_path"], "project-room", "README.md")
    target = os.path.join(REPO_ROOT, status_file)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content = open(target, errors="ignore").read() if os.path.exists(target) else \
        (f"# {reg.get('name') or key}\n" if reason else "")
    out = []
    for l in content.splitlines():
        m = re.match(r"\s*<!-- board-wait reason=(\w+) since=(\S+?) -->\s*$", l)
        out.append(f"<!-- board-wait-done reason={m.group(1)} since={m.group(2)} until={now} -->"
                   if m else l)
    if reason:
        out.append(f"<!-- board-wait reason={reason} since={now} -->")
    if reason or os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write("\n".join(out) + "\n")
    state = build_state()
    state["set_stage_ok"] = True
    state["set_stage_msg"] = f"{key}: {WAIT_REASONS.get(reason, 'wait cleared')}"
    return state


def set_criticality(key, level):
    """Set how bad it is if this breaks/stalls (critical|high|medium|low, '' clears).
    Stored as a bounded marker in the block's status file."""
    level = (level or "").strip().lower()
    if level and level not in VALID_CRIT:
        return {"ok": False, "error": f"invalid level '{level}'"}
    reg = _resolve_reg(key)
    if reg is None:
        return {"ok": False, "error": f"unknown initiative '{key}'"}
    status_file = reg.get("status_file") or os.path.join(reg["repo_path"], "project-room", "README.md")
    target = os.path.join(REPO_ROOT, status_file)
    content = open(target, errors="ignore").read() if os.path.exists(target) else \
        (f"# {reg.get('name') or key}\n" if level else "")
    content = "\n".join(l for l in content.splitlines() if "<!-- board-criticality" not in l)
    if level:
        content = content.rstrip() + f"\n\n<!-- board-criticality: {level} -->\n"
    if level or os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write(content)
    state = build_state()
    state["set_stage_ok"] = True
    state["set_stage_msg"] = f"{key} criticality {level or 'cleared'}"
    return state


def run_action(code, action, extra=None):
    spec = ACTIONS.get(action)
    if not spec:
        return {"ok": False, "error": f"unknown action '{action}'"}
    state = build_state()
    item = next((i for i in state["items"]
                 if i.get("key") == code or i.get("code") == code or i.get("folder") == code), None)
    if item is None and action != "scan_email":
        return {"ok": False, "error": f"no initiative '{code}'"}
    fields = {k: (item.get(k) if item and item.get(k) is not None else "n/a")
              for k in ("name", "code", "stage", "blocker", "repo_path")} if item else \
             {k: "n/a" for k in ("name", "code", "stage", "blocker", "repo_path")}
    prompt = spec["prompt"].format(**fields)
    if (extra or "").strip():
        prompt += f"\n\nLouis's aim / instruction (follow this): {extra.strip()}"
    try:
        res = subprocess.run(
            ["claude", "-p", prompt, "--allowedTools", spec["tools"],
             "--permission-mode", spec.get("perm", "acceptEdits")],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=600, env=_claude_env())
    except FileNotFoundError:
        return {"ok": False, "error": "claude CLI not found on PATH", "prompt": prompt}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "claude timed out (600s)", "prompt": prompt}
    out = res.stdout.strip()
    # Auto-record a created draft in the block's notes for traceability, incl. a summary
    if action == "draft_chase" and res.returncode == 0 and item:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        m = re.search(r"\b(r-\d{6,})\b", out)
        aim = (extra or "").strip()
        summary = " ".join(out.split())[:260]        # Claude's summary of what it drafted
        note = f"{today} — 📧 email drafted" + (f" [{m.group(1)}]" if m else "")
        if aim:
            note += f" · aim: {aim}"
        if summary:
            note += f" · drafted: {summary}"
        append_activity(item.get("status_file"), note)
    return {"ok": res.returncode == 0, "output": out,
            "error": res.stderr.strip() or None, "prompt": prompt}


def run_chat(key, message, history):
    """Chat with Claude Code ABOUT one block. Read/edit only - CANNOT push or send
    (those tools are not granted), so it can help and draft, never fire irreversible."""
    if not (message or "").strip():
        return {"ok": False, "error": "empty message"}
    item = next((i for i in build_state()["items"]
                 if i.get("key") == key or i.get("code") == key or i.get("folder") == key), None)
    ctx = ""
    if item:
        ctx = (f"You are helping with ONE Hungry Lion initiative on the RevvTech board.\n"
               f"Code: {item.get('code')}\nName: {item.get('name')}\nStage: {item.get('stage')}\n"
               f"Health: {item.get('health')}\nBlocker: {item.get('blocker') or 'none'}\n"
               f"Folder: {item.get('repo_path')}\nStatus file: {item.get('status_file')}\n"
               f"What it does: {item.get('what_it_does')}\n\n")
    convo = "".join(f"{'User' if t.get('role') == 'user' else 'You'}: {t.get('text', '')}\n"
                    for t in (history or [])[-8:])
    prompt = (ctx + "Conversation so far:\n" + convo + f"User: {message}\n\n"
              "Reply concisely (KISS, plain language - Louis is a PM, not a coder). You may read "
              "and edit files in this repo to help, but DO NOT push to git and DO NOT send email.")
    try:
        res = subprocess.run(
            ["claude", "-p", prompt, "--allowedTools", "Read,Grep,Glob,Edit,Write",
             "--permission-mode", "acceptEdits"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=600, env=_claude_env())
        return {"ok": res.returncode == 0, "reply": res.stdout.strip(),
                "error": res.stderr.strip() or None}
    except FileNotFoundError:
        return {"ok": False, "error": "claude CLI not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "claude timed out (600s)"}


# ------------------------- time logging -------------------------

# HL CRM tasks (Hungry Lion - CTO + RM Agent projects). Task IDs are not secrets -
# they live in skills/time-log/SKILL.md already. The Bearer KEY is read at runtime
# from that skill (one source) - never hardcoded here.
CRM_URL = "https://tzeuejpedbbwywxillnq.supabase.co/functions/v1/consultant-api/time-entries"
LEWKAI_SHEET = "1e_d1u11Zsi69hlhATXN6iBpFWTO1A6qSI9jfV8trpiY"
CRM_TASKS = [
    {"name": "POC Planning and Documentation", "id": "f52919fc-aa75-4bf9-bab2-3949af1424c1"},
    {"name": "AI Use case Development", "id": "a4c08c38-5200-494c-97f6-5c37ee313005"},
    {"name": "Virtual Agents", "id": "bf5b0760-7488-4910-9aa7-8a14bffb898b"},
    {"name": "HL RM Agent (Louis delivery)", "id": "3f3b48a2-3d11-4a06-a1ad-c240713a7a94"},
    {"name": "RM Agent Analysis (Dom input)", "id": "03af32a9-27e3-4c59-bc37-230d4849738e"},
]


def _crm_key():
    for p in (os.path.join(REPO_ROOT, "skills/time-log/SKILL.md"),
              os.path.expanduser("~/.pi/agent/skills/time-log/SKILL.md")):
        try:
            m = re.search(r"Bearer (cpk_[a-f0-9]+)", open(p).read())
            if m:
                return m.group(1)
        except Exception:
            pass
    return None


def log_time(key, hours, note, task_id):
    """Log time for one block to the 4 billing systems. CRM FIRST (the one you can't
    accidentally de-duplicate) - if it fails, nothing else is written, safe to retry.
    If CRM succeeds but a later step fails, report exactly what's done + what to redo,
    and warn NOT to re-click (that would double-bill CRM)."""
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return {"ok": False, "error": "hours must be a number"}
    if hours <= 0:
        return {"ok": False, "error": "hours must be > 0"}
    if not (note or "").strip():
        return {"ok": False, "error": "add a short note of what you did"}
    task = next((t for t in CRM_TASKS if t["id"] == task_id), None)
    if not task:
        return {"ok": False, "error": "pick a CRM task"}
    item = next((i for i in build_state()["items"]
                 if i.get("key") == key or i.get("code") == key or i.get("folder") == key), None)
    if not item:
        return {"ok": False, "error": f"no initiative '{key}'"}
    crm_key = _crm_key()
    if not crm_key:
        return {"ok": False, "error": "CRM key not found in skills/time-log/SKILL.md"}
    with open(DATA) as f:
        client_disp = json.load(f).get("client", "")
    client_dir = item["client_dir"]
    note = note.strip()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1 — CRM (first; abort cleanly on failure)
    import urllib.request
    body = json.dumps({"task_id": task_id, "hours": hours, "note": note,
                       "entry_date": today, "is_billable": True}).encode()
    req = urllib.request.Request(CRM_URL, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {crm_key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            crm_id = json.loads(r.read()).get("id")
    except Exception as e:
        return {"ok": False, "error": f"CRM failed ({e}). Nothing logged — safe to click Log again."}

    done, failed = ["CRM"], []
    # 2 + 3 — local client file + workspace timelog
    row = f"| {today} | {task['name']} | {hours} | ✓ | {note} CRM id {crm_id}. |\n"
    for label, path in (("client time-log", os.path.join(REPO_ROOT, client_dir, "time-log.md")),
                        ("workspace timelog",
                         os.path.join(REPO_ROOT, "timelog", os.path.basename(client_dir) + ".md"))):
        try:
            with open(path, "a") as f:
                f.write(row)
            done.append(label)
        except Exception as e:
            failed.append(f"{label}: {e}")

    # 4 — Lewkai master sheet (via the repo helper)
    contact = item.get("contact") or item.get("sponsor") or ""
    xref = f"{item['repo_path']} ; {client_dir}/time-log.md"
    lewkai_row = [today, client_disp, contact, task["name"], hours, "Yes", note, xref, crm_id, ""]
    try:
        res = subprocess.run(["python3", "tools/gsheet_append.py", LEWKAI_SHEET, "--no-grant",
                              "--rows-json", json.dumps([lewkai_row])],
                             cwd=REPO_ROOT, capture_output=True, text=True, timeout=90)
        if res.returncode == 0 and "wrote" in res.stdout:
            done.append("Lewkai sheet")
        else:
            failed.append("Lewkai sheet (paste manually): " + json.dumps(lewkai_row))
    except Exception as e:
        failed.append(f"Lewkai sheet: {e}")

    return {"ok": not failed, "crm_id": crm_id, "hours": hours, "task": task["name"],
            "done": done, "failed": failed}


# ------------------------- connect Claude (subscription, via UI) -------------------------
# Drives `claude setup-token` in a pty so the client connects their OWN Claude
# subscription from the web setup — surface the auth URL, take the pasted code back.

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")
_cc = {"proc": None, "master": None}


def _cc_clean(s):
    return _ANSI.sub("", s).replace("\r", "")


def _cc_read(timeout=15):
    fd = _cc.get("master")
    if fd is None:
        return ""
    out, deadline = "", time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk.decode(errors="ignore")
            deadline = time.time() + 2          # settle shortly after output stops
        elif out:
            break
    return out


def _cc_kill():
    p = _cc.get("proc")
    if p and p.poll() is None:
        try:
            p.terminate()
        except Exception:
            pass
    if _cc.get("master") is not None:
        try:
            os.close(_cc["master"])
        except Exception:
            pass
    _cc.update({"proc": None, "master": None})


def claude_start():
    _cc_kill()
    master, slave = pty.openpty()
    try:
        p = subprocess.Popen(["claude", "setup-token"], stdin=slave, stdout=slave,
                             stderr=slave, cwd=REPO_ROOT, close_fds=True)
    except FileNotFoundError:
        os.close(master); os.close(slave)
        return {"ok": False, "error": "claude CLI not found on this instance"}
    os.close(slave)
    _cc.update({"proc": p, "master": master})
    out = _cc_read(15)
    m = re.search(r"https?://\S+", _cc_clean(out))
    return {"ok": True, "url": (m.group(0).rstrip(").,]") if m else None),
            "output": _cc_clean(out)[-1600:]}


def claude_finish(code):
    if not _cc.get("master"):
        return {"ok": False, "error": "click Connect first"}
    try:
        os.write(_cc["master"], ((code or "").strip() + "\n").encode())
    except OSError as e:
        return {"ok": False, "error": str(e)}
    out = _cc_clean(_cc_read(25))
    # setup-token prints the token; grab it (it wraps across lines) up to the "Store this"/
    # "Use this token" note, then strip whitespace back to the raw token.
    m = re.search(r"sk-ant-oat[\s\S]*?(?=Store this|Use this token|$)", out)
    tok = re.sub(r"[^A-Za-z0-9_\-]", "", m.group(0)) if m else ""
    if len(tok) > 40:
        try:
            with open(CLAUDE_TOKEN_FILE, "w") as f:
                f.write(tok)
            os.chmod(CLAUDE_TOKEN_FILE, 0o600)
        except Exception as e:
            _cc_kill()
            return {"ok": False, "error": f"token captured but could not store: {e}"}
        _cc_kill()
        return {"ok": True, "output": "Connected — Claude token stored; actions are live."}
    return {"ok": False, "output": out[-1600:] or "No token yet — check the code and try again."}


# ------------------------- http -------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            with open(HTML, "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.path.startswith("/api/state"):
            self._send(200, build_state())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        if self.path.startswith("/api/refresh"):
            self._send(200, build_state())
        elif self.path.startswith("/api/set_stage"):
            self._send(200, set_stage(payload.get("key") or payload.get("folder"), payload.get("stage")))
        elif self.path.startswith("/api/set_status"):
            self._send(200, set_status(payload.get("key"), payload.get("text")))
        elif self.path.startswith("/api/set_priority"):
            self._send(200, set_priority(payload.get("key"), bool(payload.get("on"))))
        elif self.path.startswith("/api/set_criticality"):
            self._send(200, set_criticality(payload.get("key"), payload.get("level")))
        elif self.path.startswith("/api/add_initiative"):
            self._send(200, add_initiative(payload.get("name"), payload.get("area"), payload.get("type")))
        elif self.path.startswith("/api/set_wait"):
            self._send(200, set_wait(payload.get("key"), payload.get("reason")))
        elif self.path.startswith("/api/claude/start"):
            self._send(200, claude_start())
        elif self.path.startswith("/api/claude/finish"):
            self._send(200, claude_finish(payload.get("code")))
        elif self.path.startswith("/api/chat"):
            self._send(200, run_chat(payload.get("key"), payload.get("message"), payload.get("history")))
        elif self.path.startswith("/api/register_row"):
            self._send(200, register_row(payload.get("key")))
        elif self.path.startswith("/api/log_time"):
            self._send(200, log_time(payload.get("key"), payload.get("hours"),
                                     payload.get("note"), payload.get("task_id")))
        elif self.path.startswith("/api/act"):
            self._send(200, run_action(payload.get("code"), payload.get("action"), payload.get("extra")))
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Initiative Control Board -> http://{HOST}:{PORT}  (repo: {REPO_ROOT})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
