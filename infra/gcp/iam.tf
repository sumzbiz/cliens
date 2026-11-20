# One service account per workload, each with only what that workload uses.
#
# No service-account key is created anywhere. The backend authenticates to Earth
# Engine as its own attached identity through Application Default Credentials.

resource "google_service_account" "api" {
  account_id   = "${var.name_prefix}-api"
  display_name = "Cliens backend (Cloud Run)"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "web" {
  account_id   = "${var.name_prefix}-web"
  display_name = "Cliens frontend (Cloud Run)"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "build" {
  account_id   = "${var.name_prefix}-build"
  display_name = "Cliens image builds (Cloud Build)"

  depends_on = [google_project_service.apis]
}

locals {
  api_project_roles = toset([
    # Earth Engine: run computations, billed to this registered project.
    "roles/earthengine.viewer",
    "roles/serviceusage.serviceUsageConsumer",
    # Observability.
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
  ])
  # Not granted: roles/cloudsql.client. It is needed only by the Cloud SQL
  # connector/proxy; this service connects to the private IP directly.

  web_project_roles = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
  ])
}

resource "google_project_iam_member" "api" {
  for_each = local.api_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "web" {
  for_each = local.web_project_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.web.email}"
}

# Cloud Build: write logs, read its staged source, push to this one repository.
resource "google_project_iam_member" "build_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket_iam_member" "build_source" {
  bucket = google_storage_bucket.build_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}

resource "google_artifact_registry_repository_iam_member" "build_push" {
  repository = google_artifact_registry_repository.images.name
  location   = google_artifact_registry_repository.images.location
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build.email}"
}
