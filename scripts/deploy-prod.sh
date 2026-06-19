#!/bin/bash
# Khata — deploy to the production box (Debian 12) over SSH as a Docker container.
# No sudo needed (operator is in the docker group).
#
#   bash scripts/deploy-prod.sh
#
# What it does:
#   1. refresh a clean `main` checkout (Docker files live on main) -> rsync to prod ~/khata/app
#   2. first run only: seed a consistent SQLite snapshot into the bind-mounted data/ volume
#   3. first run only: write ~/khata/app/.env.prod (secret + Google id carried from local .env.app)
#   4. docker compose up -d --build  (gunicorn -w 2 :5057, restart:always)
#   5. curl smoke test on :5057
#
# Deploy source is ALWAYS main — the live DB's alembic head (fxsnapshot01) lives there.
# Deploying a feature branch crash-loops on `alembic upgrade head`.
set -euo pipefail

HOST=npalakurla@192.168.50.14
RHOME=/home/npalakurla
APP=$RHOME/khata/app
ROOT=$(cd "$(dirname "$0")/.." && git rev-parse --show-toplevel)
SRC=/tmp/khata-deploy-main       # clean main worktree, auto-managed below
SSH="ssh -o BatchMode=yes $HOST"

echo "── 1/5 refresh clean main checkout ──"
# Always (re)create a clean main checkout at $SRC. Nuke + prune the (possibly stale,
# /tmp→/private/tmp symlink-mismatched) registration, then force-add — robust to a
# pruned/missing-but-registered worktree.
git -C "$ROOT" fetch -q origin main
rm -rf "$SRC"
git -C "$ROOT" worktree prune
git -C "$ROOT" worktree add -f --detach "$SRC" origin/main
test -f "$SRC/Dockerfile" || { echo "FATAL: $SRC has no Dockerfile — Docker files not on main?"; exit 1; }
echo "main @ $(git -C "$SRC" rev-parse --short HEAD)"

echo "── code sync -> $APP ──"
$SSH "mkdir -p $APP/data"
rsync -az --delete \
  --exclude .git --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '*.db' --exclude '*.db-shm' --exclude '*.db-wal' \
  --exclude '.env*' --exclude mobile --exclude OD_khata_mockup \
  --exclude _build-dashboard --exclude site --exclude notes --exclude backups \
  --exclude data --exclude '*.log' --exclude '*.pid' \
  "$SRC/" "$HOST:$APP/"
echo "code synced"

echo "── 2/5 data seed (first run only) ──"
if $SSH "test -f $APP/data/khata_app.db"; then
  echo "prod DB exists at $APP/data/khata_app.db — NOT overwriting"
else
  # consistent snapshot of the local DB (safe while it runs); local Mac has sqlite3
  sqlite3 "$ROOT/khata_app.db" ".backup /tmp/khata-prod-seed.db"
  scp -q /tmp/khata-prod-seed.db "$HOST:$APP/data/khata_app.db"
  rm /tmp/khata-prod-seed.db
  echo "real data seeded -> $APP/data/khata_app.db ($($SSH "du -h $APP/data/khata_app.db | cut -f1"))"
fi

echo "── 3/5 .env.prod (first run only) ──"
if $SSH "test -f $APP/.env.prod"; then
  echo ".env.prod exists — NOT overwriting (edit on the box to change secrets)"
else
  SECRET=$(grep '^KHATA_SECRET_KEY=' "$ROOT/.env.app" | cut -d= -f2-)
  GCID=$(grep '^KHATA_GOOGLE_CLIENT_ID=' "$ROOT/.env.app" | cut -d= -f2-)
  # KHATA_DATABASE_URL / KHATA_ENV are set by docker-compose.yml, not here.
  $SSH "umask 077; cat > $APP/.env.prod <<EOF
KHATA_SECRET_KEY=$SECRET
KHATA_GOOGLE_CLIENT_ID=$GCID
EOF"
  echo ".env.prod written (KHATA_SECURE_COOKIES intentionally NOT set until a TLS proxy is live)"
fi

echo "── 4/5 build + up ──"
$SSH "cd $APP && docker compose up -d --build"

echo "── 5/5 smoke test ──"
$SSH "sleep 6
      code=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5057/)
      welcome=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5057/welcome)
      echo \"smoke: / -> \$code, /welcome -> \$welcome\"
      docker ps --filter name=khata --format '{{.Names}} {{.Status}}'
      [ \"\$code\" = 200 ] || { docker compose -f $APP/docker-compose.yml logs --tail=30; exit 1; }"

echo
echo "DEPLOYED. http://192.168.50.14:5057/"
echo "Ops on the box:  docker ps | docker compose {restart,logs -f,down}  (in $APP)"
