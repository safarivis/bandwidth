#!/usr/bin/env bash
# provision.sh — stand up a NEW Bandwidth client instance on the VPS in one command.
#
#   ./provision.sh <client> [port]        e.g.  ./provision.sh acme
#   ./provision.sh <client> --dry-run     print every action, touch nothing
#
# Mirrors the hardened live "main" (Kelly) setup exactly:
#   • dedicated bw-<client> user (isolation)         • /srv/bandwidth/<client>/{app,data}
#   • systemd bandwidth-<client>.service, sandboxed  • nginx <client>.bandwidth.lewkai.com
#     (ProtectSystem=strict, ReadWritePaths=data+home)  + basic-auth + TLS (certbot)
#   • seeds an empty registry.csv + per-client data.json (never clobbered by ship.sh)
#
# Runs LOCALLY and drives the VPS over SSH (same model as ship.sh); infra targets
# come from the gitignored .deploy.env. The basic-auth password is prompted here and
# HASHED locally (openssl apr1) — the plaintext never leaves this machine.
#
# After it finishes, one manual step remains: the client connects THEIR Claude in-app
# (Welcome → Connect Claude), or you run `sudo -iu bw-<client> claude` on the box.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$DIR"

# ---- args ----
CLIENT="${1:-}"; PORT=""; DRY=0
for a in "${@:2}"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    [0-9]*)    PORT="$a" ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done
[ -n "$CLIENT" ] || { echo "usage: ./provision.sh <client> [port] [--dry-run]" >&2; exit 2; }
[[ "$CLIENT" =~ ^[a-z][a-z0-9-]*$ ]] || { echo "client must be lowercase letters/digits/dashes (start with a letter): '$CLIENT'" >&2; exit 2; }

# ---- infra targets (shared with ship.sh) ----
[ -f .deploy.env ] && . ./.deploy.env
HOST="${BANDWIDTH_HOST:?set BANDWIDTH_HOST in .deploy.env}"
KEY="${BANDWIDTH_KEY:-$HOME/.ssh/lewkai_deploy}"
DOMAIN="${BANDWIDTH_DOMAIN:-bandwidth.lewkai.com}"        # wildcard *.$DOMAIN must resolve to the box
CERT_EMAIL="${BANDWIDTH_CERT_EMAIL:-}"                    # optional; certbot reuses the box account if empty
SSH="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
FQDN="$CLIENT.$DOMAIN"
BASE="/srv/bandwidth/$CLIENT"
USER="bw-$CLIENT"
SVC="bandwidth-$CLIENT"

echo "→ target: $FQDN  (user $USER, dir $BASE, service $SVC)"

# ---- refuse to clobber an existing client ----
if $SSH "root@$HOST" "test -e $BASE || id $USER >/dev/null 2>&1"; then
  echo "✗ '$CLIENT' already exists on the box ($BASE or user $USER). Refusing to clobber — use ship.sh to update its code." >&2
  exit 1
fi

# ---- pick a free port if not given (scan existing instances' env files) ----
if [ -z "$PORT" ]; then
  USED="$($SSH "root@$HOST" "cat /srv/bandwidth/*/env 2>/dev/null | sed -n 's/^BOARD_PORT=//p'" || true)"
  PORT=8791
  while echo "$USED" | grep -qx "$PORT"; do PORT=$((PORT+1)); done
  echo "→ auto-picked free port $PORT (in use: $(echo $USED | tr '\n' ' '))"
fi

# ---- basic-auth password → hash locally (plaintext never sent) ----
if [ "$DRY" = 1 ]; then
  HTPASS_LINE="$CLIENT:<apr1-hash-of-your-password>"
else
  read -r -s -p "Set basic-auth password for user '$CLIENT': " PW; echo
  [ -n "$PW" ] || { echo "empty password, aborting" >&2; exit 2; }
  read -r -s -p "Confirm: " PW2; echo
  [ "$PW" = "$PW2" ] || { echo "passwords did not match" >&2; exit 2; }
  HASH="$(openssl passwd -apr1 "$PW")"; unset PW PW2
  HTPASS_LINE="$CLIENT:$HASH"
fi

# ---- the remote provisioning script (runs as root on the box) ----
REMOTE=$(cat <<REMOTE_EOF
set -euo pipefail
CLIENT=$CLIENT; USER=$USER; BASE=$BASE; SVC=$SVC; PORT=$PORT; FQDN=$FQDN; DOMAIN=$DOMAIN

# 1. isolated service user
id "\$USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "\$USER"

# 2. dirs: framework code (app, root-owned) + client data (data, user-owned, git for status derivation)
mkdir -p "\$BASE/app" "\$BASE/data"
chown -R "\$USER:\$USER" "\$BASE/data"
sudo -u "\$USER" git -C "\$BASE/data" rev-parse >/dev/null 2>&1 || sudo -u "\$USER" git -C "\$BASE/data" init -q

# 3. per-instance env (BOARD_REPO = their data dir; unique port)
cat > "\$BASE/env" <<EOF
BOARD_REPO=\$BASE/data
BOARD_PORT=\$PORT
EOF

# 4. seed empty registry.csv (in the DATA dir the board reads/writes) — owned by the user
if [ ! -f "\$BASE/data/registry.csv" ]; then
  echo 'code,name,type,sponsor,contact,repo_path,status_file,what_it_does,why_it_matters,dept,requested_by,sa' > "\$BASE/data/registry.csv"
  chown "\$USER:\$USER" "\$BASE/data/registry.csv"
fi

# 5. hardened systemd service — SAME sandbox as the live 'main' instance
cat > /etc/systemd/system/\$SVC.service <<EOF
[Unit]
Description=Bandwidth - \$CLIENT
After=network.target
[Service]
User=\$USER
EnvironmentFile=\$BASE/env
WorkingDirectory=\$BASE/app
ExecStart=/usr/bin/python3 server.py
Restart=always
RestartSec=3
ProtectSystem=strict
ReadWritePaths=\$BASE/data /home/\$USER
NoNewPrivileges=true
PrivateTmp=true
ProtectKernelTunables=true
[Install]
WantedBy=multi-user.target
EOF

# 6. nginx site (subdomain, basic-auth) — board has no auth of its own
mkdir -p /etc/nginx/bandwidth
cat > /etc/nginx/bandwidth/\$CLIENT.htpasswd <<EOF
$HTPASS_LINE
EOF
cat > /etc/nginx/sites-available/\$SVC <<EOF
server {
    server_name \$FQDN;
    location / {
        auth_basic "Bandwidth";
        auth_basic_user_file /etc/nginx/bandwidth/\$CLIENT.htpasswd;
        proxy_pass http://127.0.0.1:\$PORT;
        proxy_set_header Host \\\$host;
        proxy_set_header X-Real-IP \\\$remote_addr;
    }
    listen 80;
}
EOF
ln -sf /etc/nginx/sites-available/\$SVC /etc/nginx/sites-enabled/\$SVC
nginx -t
REMOTE_EOF
)

# code sync + service start + TLS are done outside the heredoc so we can rsync from local
if [ "$DRY" = 1 ]; then
  echo "──────── DRY RUN — would run on $HOST ────────"
  echo "# rsync framework code → $BASE/app (excludes per-client data.json / registry.csv):"
  echo "rsync -az --exclude .git --exclude __pycache__ --exclude server.log --exclude 'data.json' --exclude 'registry.csv' ... ./ root@$HOST:$BASE/app/"
  echo "# seed per-client data.json (client name; BOARD_REPO env points repo_root at the data dir):"
  echo "  {\"client\": \"$CLIENT\", \"client_dir\": \".\"}  → $BASE/app/data.json"
  echo
  echo "$REMOTE"
  echo
  echo "# lock framework read-only, then enable + start + TLS:"
  echo "chown -R root:root $BASE/app && chmod -R a+rX $BASE/app"
  echo "systemctl daemon-reload && systemctl enable --now $SVC"
  echo "certbot --nginx -d $FQDN -n --agree-tos ${CERT_EMAIL:+-m $CERT_EMAIL} --redirect"
  echo "──────── end dry run ────────"
  exit 0
fi

echo "→ 1/5 create user, dirs, env, service, nginx"
$SSH "root@$HOST" "$REMOTE"

echo "→ 2/5 sync framework code (per-client config untouched)"
rsync -az --exclude '.git' --exclude '__pycache__' --exclude 'server.log' --exclude 'BOARD.md' \
  --exclude 'data.json' --exclude 'registry.csv' --exclude '*.pyc' --exclude 'data/' \
  --exclude '.deploy.env' --exclude 'provision.sh' -e "$SSH" ./ "root@$HOST:$BASE/app/"

echo "→ 3/5 seed per-client data.json + lock framework read-only"
$SSH "root@$HOST" "printf '{\n  \"client\": \"%s\",\n  \"client_dir\": \".\"\n}\n' '$CLIENT' > $BASE/app/data.json \
  && chown -R root:root $BASE/app && chmod -R a+rX $BASE/app"

echo "→ 4/5 enable + start service"
$SSH "root@$HOST" "systemctl daemon-reload && systemctl enable --now $SVC && sleep 2 && systemctl is-active $SVC"

echo "→ 5/5 reload nginx + obtain TLS cert"
$SSH "root@$HOST" "systemctl reload nginx && certbot --nginx -d $FQDN -n --agree-tos ${CERT_EMAIL:+-m $CERT_EMAIL} --redirect"

cat <<DONE

✅ Provisioned '$CLIENT'
   URL:        https://$FQDN
   Basic auth: user '$CLIENT' (password you just set)
   Service:    $SVC on 127.0.0.1:$PORT   (systemctl status $SVC)

Last step (client's own Claude, so actions bill to them):
   open the URL → Welcome → "Connect Claude", OR on the box:
   ssh -i $KEY root@$HOST 'sudo -iu $USER claude'   then  systemctl restart $SVC
DONE
