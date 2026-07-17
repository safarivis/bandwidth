#!/usr/bin/env bash
# ship.sh — commit + push Bandwidth to GitHub, then deploy to a client instance.
#
#   ./ship.sh "commit message" [instance]     (instance defaults to "main" = Kelly)
#
# Infra targets are read from a gitignored .deploy.env so they stay out of the
# public repo. Create it once (see .deploy.env.example):
#   BANDWIDTH_HOST=<vps-ip>
#   BANDWIDTH_KEY=$HOME/.ssh/lewkai_deploy
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$DIR"
MSG="${1:-update}"; INSTANCE="${2:-main}"
[ -f .deploy.env ] && . ./.deploy.env
HOST="${BANDWIDTH_HOST:?set BANDWIDTH_HOST in .deploy.env}"
KEY="${BANDWIDTH_KEY:-$HOME/.ssh/lewkai_deploy}"
SSH="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

echo "→ 1/3 commit + push"
git add -A
git commit -q -m "$MSG" || echo "  (nothing to commit)"
git push -q origin main

echo "→ 2/3 deploy code to instance '$INSTANCE' (per-client config/data untouched)"
rsync -az --exclude '.git' --exclude '__pycache__' --exclude 'server.log' --exclude 'BOARD.md' \
  --exclude 'data.json' --exclude 'registry.csv' --exclude '*.pyc' --exclude 'data/' \
  --exclude '.deploy.env' --exclude 'provision.sh' -e "$SSH" ./ "root@$HOST:/srv/bandwidth/$INSTANCE/app/"

echo "→ 3/3 re-lock framework read-only + restart"
$SSH "root@$HOST" "chown -R root:root /srv/bandwidth/$INSTANCE/app && chmod -R a+rX /srv/bandwidth/$INSTANCE/app && systemctl restart bandwidth-$INSTANCE && sleep 2 && systemctl is-active bandwidth-$INSTANCE"
echo "✅ shipped '$MSG' → GitHub + $INSTANCE"
