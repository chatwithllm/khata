#!/usr/bin/env bash
# Khata raw-SQLite backup — exact byte-for-byte snapshot of the whole instance.
# Uses SQLite's online .backup so it is safe to run while the app is live.
#
# Usage:
#   ./scripts/backup.sh [DB_PATH] [DEST_DIR]
# DB_PATH defaults to $KHATA_DATABASE_URL (sqlite:///...) or ./khata_app.db
# DEST_DIR defaults to <db_dir>/backups
#
# Restore the resulting file with scripts/restore.sh (this is the exact-REPLACE path;
# for additive/merge restore use the in-app JSON: Settings -> Data -> Restore).
set -euo pipefail

DB="${1:-}"
if [ -z "$DB" ]; then
  if [ -n "${KHATA_DATABASE_URL:-}" ] && [[ "$KHATA_DATABASE_URL" == sqlite:///* ]]; then
    DB="${KHATA_DATABASE_URL#sqlite:///}"
  else
    DB="khata_app.db"
  fi
fi
[ -f "$DB" ] || { echo "error: database not found: $DB" >&2; exit 1; }

DB_DIR="$(cd "$(dirname "$DB")" && pwd)"
DEST_DIR="${2:-$DB_DIR/backups}"
mkdir -p "$DEST_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$DEST_DIR/$(basename "$DB" .db)-$STAMP.db"

sqlite3 "$DB" ".backup '$DEST'"
echo "backup written: $DEST"
ls -la "$DEST"
