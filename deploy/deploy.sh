#!/usr/bin/env bash
#
# Build, upload, and start the stack on the instance Terraform created.
#
# Nothing here touches the AWS console, and nothing needs SSH. The instance has
# no open port 22 and no key pair; everything below reaches it through SSM, and
# the artifacts travel through the private S3 bucket the instance's IAM role
# allows it to read.
#
#     bash deploy/deploy.sh
#
# Safe to re-run. It is the same script for the first deploy and every one after.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# --- Where Terraform says everything is ------------------------------------
# Read from state rather than hardcoded, so this cannot drift from what was
# actually created.
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }

need_output() {
  local value
  value="$(terraform -chdir=infra output -raw "$1" 2>/dev/null || true)"
  if [[ -z "$value" ]]; then
    echo "Missing Terraform output '$1'. Run 'terraform -chdir=infra apply' first." >&2
    exit 1
  fi
  printf '%s' "$value"
}

BUCKET="$(need_output artifact_bucket)"
INSTANCE_ID="$(need_output instance_id)"
REGION="$(need_output region)"
URL="$(need_output url)"

say "Deploying to $INSTANCE_ID in $REGION"

# --- Frontend ---------------------------------------------------------------
# Built here rather than on the instance: it needs the full node_modules tree,
# which is far larger than the output it produces.
say "Building the frontend"
if command -v npm.cmd >/dev/null 2>&1; then
  npm.cmd run build --workspace frontend
else
  npm run build --workspace frontend
fi

# --- Package the backend ----------------------------------------------------
# Only what the image actually needs. The 129 MB GRIB record and its derived CSV
# are excluded — the app reads the small district profile bundle that already
# lives inside backend/app/repositories/data/.
say "Packaging the backend"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

tar --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.venv' \
    --exclude='app/tests' \
    -czf "$BUILD_DIR/backend.tar.gz" \
    backend/Dockerfile \
    backend/docker-entrypoint.sh \
    backend/pyproject.toml \
    backend/alembic.ini \
    backend/app \
    db/migrations \
    ml/models \
    deploy/docker-compose.prod.yml \
    deploy/Caddyfile

tar -czf "$BUILD_DIR/site.tar.gz" -C frontend/dist .

# --- Upload -----------------------------------------------------------------
say "Uploading artifacts"
aws s3 cp "$BUILD_DIR/backend.tar.gz" "s3://$BUCKET/backend.tar.gz" --region "$REGION" --only-show-errors
aws s3 cp "$BUILD_DIR/site.tar.gz" "s3://$BUCKET/site.tar.gz" --region "$REGION" --only-show-errors

# --- Tell the instance to deploy -------------------------------------------
# The build happens on the instance. Every heavy dependency ships prebuilt
# manylinux wheels for both architectures, so this is a download rather than a
# compile, and it avoids cross-architecture emulation entirely.
#
# `set -eux` without pipefail: SSM's AWS-RunShellScript executes these under
# /bin/sh, which on Ubuntu is dash, and dash has no `set -o pipefail`. There are
# no pipelines below, so nothing is lost by leaving it out.
#
# The docker build writes its output to a file on the instance rather than to
# stdout, and only the tail is echoed on failure. SSM truncates an invocation's
# output at 24 KB, and a build log is far larger than that — which meant the
# actual error was always the part that got cut off.
say "Building and starting on the instance (a few minutes on first run)"

# Keep the site directory inode stable: Caddy bind-mounts it, and replacing the directory
# would leave the running container attached to the old tree.
COMMAND_ID="$(aws ssm send-command \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --comment "Building Quality Score deploy" \
  --timeout-seconds 1800 \
  --parameters commands="[
    \"set -eux\",
    \"cd /opt/bqs\",
    \"for i in \$(seq 1 60); do [ -f /opt/bqs/.provisioned ] && break; echo waiting-for-cloud-init; sleep 5; done\",
    \"aws s3 cp s3://$BUCKET/backend.tar.gz /opt/bqs/backend.tar.gz --region $REGION\",
    \"aws s3 cp s3://$BUCKET/site.tar.gz /opt/bqs/site.tar.gz --region $REGION\",
    \"rm -rf /opt/bqs/build && mkdir -p /opt/bqs/build\",
    \"tar -xzf /opt/bqs/backend.tar.gz -C /opt/bqs/build\",
    \"mkdir -p /opt/bqs/site\",
    \"find /opt/bqs/site -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +\",
    \"tar -xzf /opt/bqs/site.tar.gz -C /opt/bqs/site\",
    \"cp /opt/bqs/build/deploy/docker-compose.prod.yml /opt/bqs/docker-compose.yml\",
    \"cp /opt/bqs/build/deploy/Caddyfile /opt/bqs/Caddyfile\",
    \"chown -R ubuntu:ubuntu /opt/bqs\",
    \"cd /opt/bqs/build && (docker build -f backend/Dockerfile -t bqs-backend:latest . > /var/log/bqs-build.log 2>&1 || (echo BUILD FAILED; tail -40 /var/log/bqs-build.log; exit 1))\",
    \"cd /opt/bqs && (docker compose --env-file .env -f docker-compose.yml up -d --remove-orphans > /var/log/bqs-up.log 2>&1 || (echo COMPOSE FAILED; tail -40 /var/log/bqs-up.log; exit 1))\",
    \"cd /opt/bqs && docker compose --env-file .env -f docker-compose.yml up -d --force-recreate web\",
    \"docker image prune -f > /dev/null 2>&1 || true\",
    \"docker compose -f /opt/bqs/docker-compose.yml ps\"
  ]" \
  --query 'Command.CommandId' --output text)"

say "SSM command $COMMAND_ID — waiting"

# `ssm wait command-executed` gives up after 100 attempts; a first build takes
# longer than that, so this polls directly.
STATUS="Pending"
for _ in $(seq 1 240); do
  sleep 10
  STATUS="$(aws ssm get-command-invocation \
    --region "$REGION" \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --query 'Status' --output text 2>/dev/null || echo Pending)"
  printf '.'
  case "$STATUS" in
    Success|Failed|Cancelled|TimedOut) break ;;
  esac
done
printf '\n'

if [[ "$STATUS" != "Success" ]]; then
  echo "Deploy finished with status: $STATUS" >&2
  aws ssm get-command-invocation \
    --region "$REGION" --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
    --query 'StandardErrorContent' --output text >&2 || true
  exit 1
fi

# --- Confirm it is actually serving ----------------------------------------
say "Waiting for the app to answer"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "$URL/api/health/live" >/dev/null 2>&1; then
    say "Live: $URL"
    exit 0
  fi
  sleep 5
  printf '.'
done

printf '\n'
echo "The stack started but $URL/api/health/live did not answer yet." >&2
echo "Check with: aws ssm start-session --target $INSTANCE_ID --region $REGION" >&2
echo "Then: docker compose -f /opt/bqs/docker-compose.yml logs --tail 100" >&2
exit 1
