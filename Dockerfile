FROM python:3.12-slim

# System deps: sqlite3 CLI handy for backups/inspection inside the container
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching). gunicorn is NOT in requirements.txt
# — it's the prod WSGI server, added here the same way deploy-prod.sh did.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# App code + migrations
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    KHATA_ENV=production

EXPOSE 5057

# Entrypoint runs alembic upgrade, then execs gunicorn
ENTRYPOINT ["/app/docker-entrypoint.sh"]
