#!/usr/bin/env bash
#
# Bring the database to the state the app expects, then serve.
#
# Every step here is idempotent, because this runs on every container start —
# including restarts — not just on first deploy.
set -euo pipefail

echo "[entrypoint] waiting for the database"
# The app cannot migrate against a Postgres that is still starting, and on a
# single host Compose brings both up together. Poll rather than sleep a fixed
# amount, so a fast start is fast and a slow one still succeeds.
python - <<'PY'
import os
import sys
import time
import urllib.parse

import psycopg

url = os.environ["DATABASE_URL"]
# The app talks to Postgres over asyncpg; psycopg needs the plain scheme.
dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)

deadline = time.monotonic() + 120
last = ""
while time.monotonic() < deadline:
    try:
        with psycopg.connect(dsn, connect_timeout=5):
            print("[entrypoint] database is up")
            sys.exit(0)
    except Exception as error:  # noqa: BLE001 - any failure here means "not yet"
        last = str(error).strip().splitlines()[0]
        time.sleep(2)

sys.exit(f"[entrypoint] database unreachable after 120s: {last}")
PY

# PostGIS must exist before the migrations run: the sites table declares a
# geometry column, and ST_Area on the geography type is what computes the
# authoritative site area. IF NOT EXISTS makes a restart a no-op.
echo "[entrypoint] ensuring PostGIS"
python - <<'PY'
import os

import psycopg

dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
with psycopg.connect(dsn, autocommit=True) as connection:
    connection.execute("CREATE EXTENSION IF NOT EXISTS postgis")
PY

echo "[entrypoint] applying migrations"
# Alembic takes its own lock, so this is safe even if two containers start
# together — the second waits and then finds nothing to do.
python -m alembic upgrade head

echo "[entrypoint] seeding the material catalogue"
# Upserts by code, so re-running updates rather than duplicating. Scoring is
# impossible against an empty catalogue, which is why this is not optional.
python -m app.cli seed-materials

echo "[entrypoint] starting server"
# --proxy-headers with --forwarded-allow-ips is not optional behind a reverse
# proxy. Without it every request appears to come from the proxy's address, and
# the per-IP rate limiter would throttle all users as if they were one client.
exec python -m uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" \
    --workers "${WEB_CONCURRENCY:-1}"
