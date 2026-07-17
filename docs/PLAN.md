# Plan — Claude-connect (UI) + Delay tracking

## 1. Connect Claude via the web UI (subscription)
**Mechanism:** `claude setup-token` (v2.1.211) — long-lived token, requires a Claude subscription (keeps their sub billing).

**Flow (guided, in-app during setup):**
1. Setup screen → "Connect your Claude" button → `POST /api/claude/start`.
2. Server (as the sandboxed service user) spawns `claude setup-token` in a pty, captures the auth URL it prints, returns it.
3. UI shows the URL ("Authorize on claude.ai") + a field to paste the code.
4. User authorizes on claude.ai (their subscription), pastes the code → `POST /api/claude/finish` → server feeds it to the pty → token stored → service can act.
5. UI confirms "Claude connected".

**Notes:** pty handling is the fragile bit; must be **live-tested** with a real authorization (can't fully test blind). Token stored in the service user's home (already in the sandbox's writable paths). **Interim:** Kelly can be unblocked today via `sudo -iu bw-main claude` on the box. → *Build as a focused, tested pass.*

## 2. Delay tracking — "where does a project's time go?"
**Capture (chosen):** light reason-tag + timestamps. Mark a block "waiting on X" → board timestamps entry; clear/move → banks the duration in that bucket.

**Categories (chosen):** `approval` · `reply` (follow-ups) · `access` (tech setup) · `data` (client input).

**Storage:** bounded markers in the block's status file —
`<!-- board-wait reason=approval since=<iso> -->` (open) → `<!-- board-wait-done reason=approval since=<iso> until=<iso> -->` (closed). One open wait per block.

**Metrics (computed each refresh):**
- per block: current open wait (reason + days), wait-days by category, total wait days.
- aggregate: total programme wait-days, days by category, top delay category, % waiting.

**Surface (chosen — both):**
- **Panel:** a "Waiting on" dropdown (none / approval / reply / access / data) + the block's own wait breakdown.
- **Delays view** (new toggle): aggregate bars (days lost by category) + per-project list.

**API:** `POST /api/set_wait {key, reason|""}`. **Build now** (deterministic + testable).
