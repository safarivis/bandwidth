#!/usr/bin/env bash
# Initiative Control Board - restart the local engine clean and open the board.
# Safe to run repeatedly (desktop shortcut): kills any old instance, starts fresh.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="http://127.0.0.1:8787"

# stop any previous instance on the port, then start a fresh one that survives logout of this launcher
fuser -k 8787/tcp 2>/dev/null || true
sleep 1
nohup python3 "$DIR/server.py" >"$DIR/server.log" 2>&1 &
disown || true
sleep 1.5

# open the board in the default browser (best-effort, cross-platform)
( command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 & ) \
  || ( command -v open >/dev/null && open "$URL" 2>/dev/null & ) \
  || echo "Open $URL in your browser."
echo "Initiative Board running at $URL (log: $DIR/server.log)"
