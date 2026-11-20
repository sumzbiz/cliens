# Frontend image for Cloud Run: the Vite build served by Caddy, which also proxies
# /api to the backend.
#
# BUILD FROM THE REPOSITORY ROOT (the npm workspace lockfile lives there):
#     docker build -f deploy/gcp/web/Dockerfile -t cliens-frontend .

FROM node:22-slim AS build

WORKDIR /repo

# Manifests first, so the dependency layer is reused until they change.
COPY package.json package-lock.json ./
COPY frontend/package.json ./frontend/
RUN npm ci --workspace frontend --include-workspace-root=false --no-audit --no-fund

COPY frontend/ ./frontend/
RUN npm run build --workspace frontend

FROM caddy:2.10-alpine

COPY deploy/gcp/web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /repo/frontend/dist /srv/site

# Caddy refuses to start on a Caddyfile error, so a broken config fails the build
# rather than the first deploy. The upstream is a placeholder for validation only.
RUN API_UPSTREAM=https://example.invalid caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

EXPOSE 8080
