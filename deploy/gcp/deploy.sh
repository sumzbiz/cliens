#!/usr/bin/env bash
#
# Deploy Climate Lien Score to Google Cloud. Run from the repository root:
#
#     PROJECT_ID=my-project deploy/gcp/deploy.sh            # everything, in order
#     PROJECT_ID=my-project deploy/gcp/deploy.sh <step>     # one step
#
# Steps, in order:
#   bootstrap  create the Terraform state bucket (once), terraform init, then a
#              targeted apply of what the image build needs: APIs, Artifact
#              Registry, the build service account and staging bucket, and the
#              empty Secret Manager containers for API keys
#   secrets    copy API keys from the local .env into Secret Manager
#   build      build and push both images with Cloud Build, tagged by git commit
#   apply      the full terraform apply: network, Cloud SQL, Cloud Run, alerts
#   verify     check the live deployment end to end
#
# Prerequisites (human steps): `gcloud auth login`, `gcloud auth
# application-default login`, and billing enabled on the project.
#
# No secret is ever printed. API keys go from .env to Secret Manager over stdin,
# and the database password is generated inside Terraform.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
NAME_PREFIX="${NAME_PREFIX:-cliens}"
ENV_FILE="${ENV_FILE:-.env}"
TF_DIR="infra/gcp"
STATE_BUCKET="${STATE_BUCKET:-${PROJECT_ID}-tfstate}"
TAG="${TAG:-$(git rev-parse --short=12 HEAD)}"

# Must match var.optional_secrets in infra/gcp/variables.tf.
OPTIONAL_SECRETS=(GEMINI_API_KEY SARVAM_API_KEY_PRIMARY SARVAM_API_KEY_SECONDARY MAPBOX_ACCESS_TOKEN)

log() { printf '\n==> %s\n' "$*"; }

tf() { terraform -chdir="$TF_DIR" "$@"; }

tf_vars() {
  printf '%s\n' "-var=project_id=${PROJECT_ID}" "-var=region=${REGION}" \
    "-var=name_prefix=${NAME_PREFIX}" "-var=image_tag=${TAG}" \
    "-var=populated_secrets=$(populated_secrets_json)"
}

# Read one key from the .env file without echoing it, the way python-dotenv (and
# so the app) reads it: whitespace around the key, the `=` and the value is
# dropped, then one pair of surrounding quotes. A space left after `=` once
# reached Secret Manager and made every API key an illegal HTTP header value.
env_value() {
  local line
  line="$(grep -E "^[[:space:]]*${1}[[:space:]]*=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line//$'\r'/}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

# The optional secrets that have a value in .env, as a Terraform list.
populated_secrets_json() {
  local names=() name
  for name in "${OPTIONAL_SECRETS[@]}"; do
    if [[ -f "$ENV_FILE" && -n "$(env_value "$name")" ]]; then
      names+=("\"${name}\"")
    fi
  done
  local IFS=,
  printf '[%s]' "${names[*]}"
}

bootstrap() {
  log "Terraform state bucket gs://${STATE_BUCKET}"
  if ! gcloud storage buckets describe "gs://${STATE_BUCKET}" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${STATE_BUCKET}" --project "$PROJECT_ID" \
      --location "$REGION" --uniform-bucket-level-access --public-access-prevention
  fi
  # Versioned, so a corrupted or mistaken state write can be rolled back.
  gcloud storage buckets update "gs://${STATE_BUCKET}" --versioning >/dev/null

  log "terraform init"
  tf init -input=false -reconfigure -backend-config="bucket=${STATE_BUCKET}"

  log "Targeted apply: what the image build needs"
  mapfile -t vars < <(tf_vars)
  tf apply -input=false -auto-approve "${vars[@]}" \
    -target=google_project_service.apis \
    -target=google_artifact_registry_repository.images \
    -target=google_storage_bucket.build_staging \
    -target=google_service_account.build \
    -target=google_project_iam_member.build_logs \
    -target=google_storage_bucket_iam_member.build_source \
    -target=google_artifact_registry_repository_iam_member.build_push \
    -target=google_secret_manager_secret.optional
}

secrets() {
  log "API keys: ${ENV_FILE} -> Secret Manager"
  [[ -f "$ENV_FILE" ]] || { echo "no ${ENV_FILE}; skipping"; return; }
  local name value current
  for name in "${OPTIONAL_SECRETS[@]}"; do
    value="$(env_value "$name")"
    if [[ -z "$value" ]]; then
      echo "  ${name}: not set in ${ENV_FILE}; left unmounted"
      continue
    fi
    current="$(gcloud secrets versions access latest --secret "$name" --project "$PROJECT_ID" 2>/dev/null || true)"
    if [[ "$current" == "$value" ]]; then
      echo "  ${name}: unchanged"
    else
      printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=- >/dev/null
      echo "  ${name}: new version added"
    fi
  done
  unset value current
}

build() {
  log "Cloud Build: backend and frontend images, tag ${TAG}"
  local build_sa staging
  build_sa="$(tf output -raw build_service_account 2>/dev/null || echo "${NAME_PREFIX}-build@${PROJECT_ID}.iam.gserviceaccount.com")"
  staging="${PROJECT_ID}-${NAME_PREFIX}-build"
  gcloud builds submit . --project "$PROJECT_ID" --region "$REGION" \
    --config deploy/gcp/cloudbuild.yaml \
    --substitutions "_REGION=${REGION},_REPOSITORY=${NAME_PREFIX},_TAG=${TAG}" \
    --service-account "projects/${PROJECT_ID}/serviceAccounts/${build_sa}" \
    --gcs-source-staging-dir "gs://${staging}/source"
}

apply() {
  log "Full terraform apply (image tag ${TAG})"
  mapfile -t vars < <(tf_vars)
  tf apply -input=false -auto-approve "${vars[@]}"
}

verify() {
  log "Verifying the live deployment"
  local app api
  app="$(tf output -raw app_url)"
  api="$(tf output -raw api_url)"

  echo "  app: ${app}"
  curl -fsS --max-time 60 "${app}/api/health/ready" && echo
  curl -fsS --max-time 30 "${app}/api/integrations" && echo
  curl -fsS --max-time 30 -o /dev/null -w "  index.html: HTTP %{http_code}\n" "${app}/"

  # The backend must refuse the public internet: its ingress is internal-only.
  local status
  status="$(curl -s --max-time 30 -o /dev/null -w '%{http_code}' "${api}/api/health/live" || true)"
  if [[ "$status" == "200" ]]; then
    echo "  FAIL: the backend answered from the public internet (HTTP 200)" >&2
    return 1
  fi
  echo "  backend from the internet: HTTP ${status} (refused, as intended)"
}

main() {
  case "${1:-all}" in
    bootstrap) bootstrap ;;
    secrets) secrets ;;
    build) build ;;
    apply) apply ;;
    verify) verify ;;
    all) bootstrap; secrets; build; apply; verify ;;
    *) echo "unknown step: $1" >&2; exit 2 ;;
  esac
}

main "$@"
