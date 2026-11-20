# Container images, and the bucket Cloud Build stages source in.

resource "google_artifact_registry_repository" "images" {
  repository_id = var.name_prefix
  location      = var.region
  format        = "DOCKER"
  description   = "Backend and frontend images, tagged by git commit."

  # Old images are deleted automatically; the most recent ten of each are kept
  # so a rollback to a recent commit never needs a rebuild.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "build_staging" {
  name     = "${var.project_id}-${var.name_prefix}-build"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true

  # Uploaded source tarballs are only needed for the build that uses them.
  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }
}
