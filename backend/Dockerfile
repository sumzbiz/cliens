# Backend image: FastAPI + the trained model, ready to serve.
#
# BUILD FROM THE REPOSITORY ROOT, not from backend/:
#     docker build -f backend/Dockerfile -t bqs-backend .
#
# The image needs three directories that are siblings, not children, of backend/ —
# the app, the Alembic migrations in db/, and the model artifact in ml/models/ —
# and a Dockerfile cannot COPY above its build context. Rooting the context at the
# repository is the only way to get all three, so every path below is repo-relative.
#
# Two stages. The builder compiles wheels for the packages that need a toolchain —
# shapely, numpy, Pillow, psycopg — and the runtime stage installs those wheels
# into a clean image. Without the split, gcc and the Python headers ship to
# production for no reason and roughly double the image.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# GEOS is shapely's C dependency; libpq is what psycopg builds against; the rest
# is the usual toolchain.
RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        libgeos-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Only the dependency manifest and the package marker, so this layer stays cached
# until dependencies actually change. Copying the source here would rebuild every
# wheel on every edit to a Python file.
COPY backend/pyproject.toml ./
COPY backend/app/__init__.py ./app/

RUN python -m pip install --upgrade pip wheel \
    && python -m pip wheel --wheel-dir /wheels .

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Runtime shared libraries only — the -dev headers stay in the builder.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libgeos-c1v5 \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# --no-index: install strictly from the wheels built above, so the runtime image
# can never silently resolve a different version of a pinned dependency.
#
# scikit-learn matters most here. pyproject.toml pins it exactly because
# unpickling a model built under a different version is unsupported and can shift
# predictions without raising, and the artifact copied below was pickled under
# that exact version.
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

WORKDIR /srv

COPY backend/app/ ./app/
COPY backend/alembic.ini ./
# alembic.ini sets script_location to %(here)s/../db/migrations, so the migrations
# must sit one level above the working directory — not inside it.
COPY db/migrations /db/migrations
# The trained artifact. Loaded once at startup by the model registry; scoring
# fails with a typed MODEL_UNAVAILABLE error without it, so a build that forgets
# this fails loudly rather than serving wrong numbers.
COPY ml/models /ml/models

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Non-root. Nothing here writes to disk at runtime — the tile and voice caches
# are in memory — so the app never needs a writable filesystem.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

# Compose and the proxy both need to know when this is actually serving. The
# liveness probe is used rather than readiness: readiness also reports on the
# database, and a container that is up but waiting on Postgres should not be
# restarted in a loop for it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=4).status == 200 else 1)"

ENTRYPOINT ["docker-entrypoint.sh"]
