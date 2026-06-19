#!/usr/bin/env bash
# Canonical Khata test instance — ONE port, latest main code, your real data.
# Re-run this after any change to pick it up (static edits are live already; Python edits need this).
set -e
ROOT=/Users/assistant/dev/active/khata
WT=/tmp/khata-landing            # clean main worktree (auto-managed below)
PORT=5057
DB="$ROOT/khata_app.db"          # your real data

# Self-heal the worktree: create or refresh a clean main checkout at $WT so a pruned
# worktree can't break this launcher. (main is the canonical app — landing-page merged.)
git -C "$ROOT" fetch -q origin main || true
git -C "$ROOT" worktree prune
if git -C "$ROOT" worktree list --porcelain | grep -q "^worktree $WT$"; then
  git -C "$WT" fetch -q origin main || true
  git -C "$WT" checkout -q --detach origin/main
else
  rm -rf "$WT"
  git -C "$ROOT" worktree add -q --detach "$WT" origin/main
fi

set -a; . "$ROOT/.env.app"; set +a
export PYTHONPATH="$WT/src" KHATA_DATABASE_URL="sqlite:///$DB" KHATA_ENV=production KHATA_ENABLE_SCHEDULER=1
( cd "$WT" && KHATA_DATABASE_URL="sqlite:///$DB" "$ROOT/.venv/bin/alembic" upgrade head ) >/dev/null 2>&1 || true
lsof -ti:$PORT | xargs kill 2>/dev/null || true; sleep 1
nohup "$ROOT/.venv/bin/python" -c "from khata import create_app; create_app().run(host='0.0.0.0', port=$PORT, debug=False)" > /tmp/khata_app.log 2>&1 &
sleep 3
curl -s -o /dev/null -w "Khata up on :$PORT  (http://$(ipconfig getifaddr en0 2>/dev/null || echo 192.168.50.189):$PORT/)  -> %{http_code}\n" "http://127.0.0.1:$PORT/"
