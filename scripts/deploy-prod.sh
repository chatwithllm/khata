#!/bin/bash
# Khata — deploy to production box (Debian 12) over SSH, no sudo needed except
# the final systemd install block which is printed for the operator to paste.
#
#   bash scripts/deploy-prod.sh
#
# What it does:
#   1. rsync code (main checkout) -> prod ~/khata/app
#   2. venv + pip install (incl. gunicorn) on prod
#   3. consistent SQLite snapshot of the real DB -> prod (FIRST RUN ONLY —
#      never overwrites an existing prod DB)
#   4. .env.prod on prod (secret key + Google client id carried from .env.app)
#   5. alembic upgrade + smoke-boot gunicorn + curl check
#   6. prints the one sudo block to install the systemd service
set -euo pipefail

HOST=npalakurla@192.168.50.14
RHOME=/home/npalakurla
ROOT=/Users/assistant/dev/active/khata
SRC=/tmp/khata-landing          # clean main checkout
SSH="ssh -o BatchMode=yes $HOST"

echo "── 1/6 code sync ──"
test -d "$SRC/src/khata" || { echo "FATAL: $SRC missing main checkout"; exit 1; }
$SSH "mkdir -p $RHOME/khata/app"
rsync -az --delete \
  --exclude .git --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '*.db' --exclude '*.db-shm' --exclude '*.db-wal' \
  --exclude '.env*' --exclude mobile --exclude OD_khata_mockup \
  --exclude _build-dashboard --exclude notes --exclude backups \
  "$SRC/" "$HOST:$RHOME/khata/app/"
echo "code synced"

echo "── 2/6 venv + deps ──"
# Debian box ships no python3-venv/pip; bootstrap pip via get-pip into a
# --without-pip venv (no apt/sudo needed).
$SSH "if ! test -x $RHOME/khata/venv/bin/pip; then
        rm -rf $RHOME/khata/venv
        python3 -m venv --without-pip $RHOME/khata/venv
        curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
        $RHOME/khata/venv/bin/python /tmp/get-pip.py -q
      fi
      $RHOME/khata/venv/bin/pip install -q --upgrade pip
      $RHOME/khata/venv/bin/pip install -q -r $RHOME/khata/app/requirements.txt gunicorn
      $RHOME/khata/venv/bin/gunicorn --version"

echo "── 3/6 data snapshot ──"
if $SSH "test -f $RHOME/khata/khata_app.db"; then
  echo "prod DB already exists — NOT overwriting (delete it on the box first if you really want a re-seed)"
else
  sqlite3 "$ROOT/khata_app.db" ".backup /tmp/khata-prod-seed.db"   # consistent even while app runs
  scp -q /tmp/khata-prod-seed.db "$HOST:$RHOME/khata/khata_app.db"
  rm /tmp/khata-prod-seed.db
  echo "real data copied -> prod ($($SSH "du -h $RHOME/khata/khata_app.db | cut -f1"))"
fi

echo "── 4/6 .env.prod ──"
SECRET=$(grep '^KHATA_SECRET_KEY=' "$ROOT/.env.app" | cut -d= -f2-)
GCID=$(grep '^KHATA_GOOGLE_CLIENT_ID=' "$ROOT/.env.app" | cut -d= -f2-)
$SSH "cat > $RHOME/khata/.env.prod <<EOF
KHATA_SECRET_KEY=$SECRET
KHATA_GOOGLE_CLIENT_ID=$GCID
KHATA_DATABASE_URL=sqlite:///$RHOME/khata/khata_app.db
KHATA_ENV=production
EOF
chmod 600 $RHOME/khata/.env.prod"
echo ".env.prod written (KHATA_SECURE_COOKIES intentionally NOT set until proxy is live)"

echo "── 5/6 migrate + smoke test ──"
$SSH "cd $RHOME/khata/app && set -a && . $RHOME/khata/.env.prod && set +a
      PYTHONPATH=src $RHOME/khata/venv/bin/alembic upgrade head
      PYTHONPATH=src nohup $RHOME/khata/venv/bin/gunicorn -w 2 -b 127.0.0.1:5057 'khata:create_app()' >/tmp/khata-smoke.log 2>&1 &
      GPID=\$!   # kill by PID, not pattern (pattern matches our own ssh cmdline)
      sleep 4
      code=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5057/)
      users=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5057/welcome)
      kill \$GPID 2>/dev/null || true
      echo \"smoke: / -> \$code, /welcome -> \$users\"
      [ \"\$code\" = 200 ] || { tail -20 /tmp/khata-smoke.log; exit 1; }"

echo "── 6/6 systemd unit (needs your sudo) ──"
$SSH "cat > $RHOME/khata/khata.service <<'EOF'
[Unit]
Description=Khata ledger
After=network.target

[Service]
User=npalakurla
WorkingDirectory=/home/npalakurla/khata/app
EnvironmentFile=/home/npalakurla/khata/.env.prod
Environment=PYTHONPATH=/home/npalakurla/khata/app/src
ExecStart=/home/npalakurla/khata/venv/bin/gunicorn -w 2 -b 0.0.0.0:5057 'khata:create_app()'
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF"

echo
echo "ALL NON-SUDO STEPS DONE. Now paste this ON THE PROD BOX (ssh in first):"
echo "──────────────────────────────────────────────────────"
echo "sudo cp ~/khata/khata.service /etc/systemd/system/khata.service"
echo "sudo systemctl daemon-reload"
echo "sudo systemctl enable --now khata"
echo "systemctl status khata --no-pager | head -5"
echo "──────────────────────────────────────────────────────"
echo "Then from any LAN device: http://192.168.50.14:5057/"
