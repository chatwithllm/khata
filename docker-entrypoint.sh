#!/usr/bin/env bash
# Migrate the DB to head, then start gunicorn. DB lives on a mounted volume
# (/data) so it survives container rebuilds.
set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting gunicorn on :5057"
exec gunicorn -w 2 -b 0.0.0.0:5057 --access-logfile - --error-logfile - 'khata:create_app()'
