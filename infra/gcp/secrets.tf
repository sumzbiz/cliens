# Secret Manager.
#
# Generated secrets (the database password and the URLs built from it) are
# written by Terraform, so they exist in state; the state bucket is private and
# versioned. Third-party API keys are not: Terraform creates their empty
# containers, and deploy.sh adds the values straight from the operator's .env.

locals {
  generated_secrets = {
    POSTGRES_PASSWORD = random_password.db.result
    DATABASE_URL      = "postgresql+asyncpg://${local.db_userinfo}@${local.db_path}"
    DATABASE_URL_SYNC = "postgresql+psycopg://${local.db_userinfo}@${local.db_path}"
  }
}

resource "google_secret_manager_secret" "generated" {
  for_each = toset(keys(local.generated_secrets))

  secret_id = each.value
  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "generated" {
  for_each = google_secret_manager_secret.generated

  secret      = each.value.id
  secret_data = local.generated_secrets[each.key]
}

resource "google_secret_manager_secret" "optional" {
  for_each = var.optional_secrets

  secret_id = each.value
  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# Per-secret access for the backend, rather than secretAccessor on the project:
# it can read exactly the secrets it mounts, nothing else in the project.
resource "google_secret_manager_secret_iam_member" "api_generated" {
  for_each = toset(["DATABASE_URL", "DATABASE_URL_SYNC"])

  secret_id = google_secret_manager_secret.generated[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}

resource "google_secret_manager_secret_iam_member" "api_optional" {
  for_each = var.populated_secrets

  secret_id = google_secret_manager_secret.optional[each.value].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}
