#!/usr/bin/env bash
# Khata raw-SQLite restore — REPLACE the live DB with a backup file (exact snapshot).
# This is the disaster-recovery path: it overwrites the current database entirely.
# (For additive/merge restore, use the in-app JSON: Settings -> Data -> Restore.)
#
# Usage:
#   ./scripts/restore.sh BACKUP_FILE [DB_PATH]
# DB_PATH defaults to $KHATA_DATABASE_URL (sqlite:///...) or ./khata_app.db
#
# STOP the app before running this so nothing is mid-write. A timestamped copy of the
# current DB is saved next to it before overwriting, so this step is itself undoable.
set -euo pipefail

BACKUP="${1:-}"
[ -n "$BACKUP" ] && [ -f "$BACKUP" ] || { echo "usage: $0 BACKUP_FILE [DB_PATH]" >&2; exit 1; }

DB="${2:-}"
if [ -z "$DB" ]; then
  if [ -n "${KHATA_DATABASE_URL:-}" ] && [[ "$KHATA_DATABASE_URL" == sqlite:///* ]]; then
    DB="${KHATA_DATABASE_URL#sqlite:///}"
  else
    DB="khata_app.db"
  fi
fi

# Verify the backup is a valid SQLite database before touching the live one.
sqlite3 "$BACKUP" "pragma integrity_check;" >/dev/null \
  || { echo "error: '$BACKUP' is not a valid SQLite database" >&2; exit 1; }

echo "This will REPLACE '$DB' with '$BACKUP'. The app should be stopped."
printf "Type 'restore' to confirm: "
read -r ans
[ "$ans" = "restore" ] || { echo "aborted."; exit 1; }

if [ -f "$DB" ]; then
  SAFETY="$DB.pre-restore-$(date +%Y%m%d-%H%M%S)"
  cp "$DB" "$SAFETY"
  echo "current DB saved to: $SAFETY"
fi

cp "$BACKUP" "$DB"
echo "restored '$DB' from '$BACKUP'. Restart the app."
