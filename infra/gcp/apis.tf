# Every Google API the deployment uses. disable_on_destroy is false: turning an
# API off on destroy would break anything else in the project that relies on it.

locals {
  services = toset([
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "earthengine.googleapis.com",
    "generativelanguage.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}

resource "google_project_service" "apis" {
  for_each = local.services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
