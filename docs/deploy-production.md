# Production deployment — Khata

Deploy Khata to a Linux server behind nginx + HTTPS, with Google Sign-In enabled.
Target in this guide: **Ubuntu 22.04+/Debian**, app served by **gunicorn** under
**systemd**, **nginx** terminating TLS via **Let's Encrypt**, reachable on the public
internet at `https://khata.npalakurla.com` (substitute your own domain throughout).

> Why not `run-app.sh`? That launches Flask's dev server — fine for local testing, not
> for production. Production = gunicorn (real WSGI) + a process manager + a reverse proxy.

## Prerequisites

- A Linux server with SSH + `sudo`, and its **public IP**.
- DNS control for your domain.
- Ports **80** and **443** reachable from the internet to the server (cloud security
  group rule and/or home-router port-forward).
- A Google OAuth 2.0 **Web** client with `https://<your-domain>` in its *Authorized
  JavaScript origins* (see `docs/google-signin-setup.md`). Note its **Client ID**.

---

## Phase 1 — DNS

Add an **A record**: `khata` → `<server-public-IP>`.

```bash
dig +short khata.npalakurla.com    # must print the server's public IP before continuing
```

## Phase 2 — install + fetch the app (on the server)

```bash
sudo apt update
sudo apt install -y python3 python3-venv git nginx certbot python3-certbot-nginx
sudo mkdir -p /opt/khata && sudo chown "$USER" /opt/khata
git clone https://github.com/chatwithllm/khata.git /opt/khata   # private repo: use a deploy key/token, or rsync the code up
cd /opt/khata
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt gunicorn
```

(`gunicorn` is not in `requirements.txt` — install it explicitly as above.)

## Phase 3 — bring real data over (optional)

To carry existing data, copy the SQLite DB from the machine that has it. **Checkpoint
the WAL first** so the copy is complete:

```bash
# on the source machine
sqlite3 /path/to/khata_app.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp /path/to/khata_app.db /tmp/khata_prod.db
```

```bash
# copy up + migrate (on the server)
scp /tmp/khata_prod.db <user>@<server>:/opt/khata/khata_app.db
cd /opt/khata
KHATA_DATABASE_URL="sqlite:////opt/khata/khata_app.db" PYTHONPATH=src \
  .venv/bin/alembic upgrade head
```

Or skip this phase and start with an empty DB (`alembic upgrade head` against a fresh
file) and sign in fresh.

## Phase 4 — env + gunicorn service

Generate a strong secret and write the prod env file:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # copy the output
sudo tee /opt/khata/.env.prod >/dev/null <<'EOF'
KHATA_SECRET_KEY=<paste-the-strong-secret>
KHATA_DATABASE_URL=sqlite:////opt/khata/khata_app.db
KHATA_ENV=production
KHATA_GOOGLE_CLIENT_ID=<your-client-id>.apps.googleusercontent.com
KHATA_SECURE_COOKIES=1
PYTHONPATH=/opt/khata/src
EOF
sudo chmod 600 /opt/khata/.env.prod
```

- `KHATA_SECURE_COOKIES=1` makes the app trust nginx's `X-Forwarded-Proto` (so it knows
  it's HTTPS) and marks the session cookie `Secure; HttpOnly; SameSite=Lax`. **Only set
  this when behind the HTTPS proxy** — over plain http the Secure cookie would never be
  sent and login would silently fail.
- `KHATA_GOOGLE_CLIENT_ID` reveals the "Continue with Google" button and enables
  `POST /api/auth/google`.

systemd unit:

```bash
sudo tee /etc/systemd/system/khata.service >/dev/null <<'EOF'
[Unit]
Description=Khata
After=network.target

[Service]
WorkingDirectory=/opt/khata
EnvironmentFile=/opt/khata/.env.prod
ExecStart=/opt/khata/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5057 "khata:create_app()"
Restart=on-failure
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
EOF
sudo chown -R www-data:www-data /opt/khata
sudo systemctl daemon-reload && sudo systemctl enable --now khata
curl -s -o /dev/null -w "app local -> %{http_code}\n" http://127.0.0.1:5057/   # expect 200
```

Notes:
- SQLite is fine for a personal/family instance. The app uses WAL mode (concurrent reads
  are fine; writes serialize). Keep workers modest (`-w 2`); raise only if needed.
- Logs: `journalctl -u khata -f`.

## Phase 5 — nginx + Let's Encrypt

```bash
sudo tee /etc/nginx/sites-available/khata >/dev/null <<'EOF'
server {
    server_name khata.npalakurla.com;
    location / {
        proxy_pass http://127.0.0.1:5057;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/khata /etc/nginx/sites-enabled/khata
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d khata.npalakurla.com   # issues the cert, rewrites to HTTPS + http→https redirect, sets auto-renew
```

certbot edits the nginx block to serve TLS and adds the redirect; after it,
`X-Forwarded-Proto` is `https`, which is what `KHATA_SECURE_COOKIES=1` relies on.

## Phase 6 — verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://khata.npalakurla.com/    # 200
```

On a phone/browser: open `https://khata.npalakurla.com` → **Continue with Google** →
sign in. (The origin is already authorized on the OAuth client, so it works as soon as
the cert is live.)

## Updating later

```bash
cd /opt/khata && git pull
.venv/bin/pip install -r requirements.txt gunicorn
KHATA_DATABASE_URL="sqlite:////opt/khata/khata_app.db" PYTHONPATH=src .venv/bin/alembic upgrade head
sudo systemctl restart khata
```

## Hardening (recommended)

- Firewall: `sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable`.
- Backups: cron the in-app/CLI backup (`scripts/backup.sh`) off the server.
- Cert auto-renew is installed by certbot; check with `sudo certbot renew --dry-run`.
- Keep the OAuth consent screen in "Testing" (only added users can sign in) until you
  intend to open it up.
