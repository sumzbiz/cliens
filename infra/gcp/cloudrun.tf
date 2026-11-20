# Two Cloud Run services on one public origin.
#
#   browser ──https──▶ cliens-web (Caddy: static app + /api proxy, public)
#                           │  Direct VPC egress, all traffic
#                           ▼
#                      cliens-api (FastAPI, ingress internal-only)
#                           │  Direct VPC egress, private ranges only
#                           ▼
#                      Cloud SQL (private IP)
#
# The backend accepts traffic only from inside the VPC, so the API is reachable
# solely through the frontend's proxy. The browser sees one origin, as in local
# development, and needs no CORS.

locals {
  image_base = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"

  # run.app URLs are deterministic: https://<service>-<project number>.<region>.run.app.
  # Computing the frontend's here lets the backend's CORS setting name it without a
  # dependency cycle (the frontend depends on the backend's URL, not the reverse).
  api_service_name = "${var.name_prefix}-api"
  web_service_name = "${var.name_prefix}-web"
  web_origin       = "https://${local.web_service_name}-${data.google_project.current.number}.${var.region}.run.app"

  api_plain_env = {
    ENVIRONMENT                          = "production"
    LOG_LEVEL                            = "INFO"
    CORS_ALLOWED_ORIGINS                 = local.web_origin
    FORWARDED_ALLOW_IPS                  = "*"
    GOOGLE_CLOUD_PROJECT                 = var.project_id
    EARTH_ENGINE_PROJECT_ID              = var.project_id
    EARTH_ENGINE_USE_APPLICATION_DEFAULT = "true"
    GEMINI_MODEL                         = var.gemini_model
  }

  api_secret_env = merge(
    {
      DATABASE_URL      = google_secret_manager_secret.generated["DATABASE_URL"].secret_id
      DATABASE_URL_SYNC = google_secret_manager_secret.generated["DATABASE_URL_SYNC"].secret_id
    },
    { for name in var.populated_secrets : name => google_secret_manager_secret.optional[name].secret_id },
  )
}

resource "google_cloud_run_v2_service" "api" {
  name                = local.api_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = false

  template {
    service_account = google_service_account.api.email
    # Above the backend's 90 s Earth Engine budget and the proxy's 110 s.
    timeout = "120s"

    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = var.api_max_instances
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.run.id
      }
      # Only Cloud SQL's private range goes through the VPC; Gemini and Earth
      # Engine are reached directly.
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = "${local.image_base}/backend:${var.image_tag}"

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        # Startup runs migrations and loads the model; full CPU while it does.
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.api_plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      # The entrypoint waits for the database, ensures PostGIS, migrates and
      # seeds before serving: allow up to four minutes for that.
      startup_probe {
        period_seconds    = 10
        timeout_seconds   = 5
        failure_threshold = 24
        http_get {
          path = "/api/health/live"
          port = 8000
        }
      }

      liveness_probe {
        period_seconds = 30
        http_get {
          path = "/api/health/live"
          port = 8000
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.api,
    google_secret_manager_secret_iam_member.api_generated,
    google_secret_manager_secret_iam_member.api_optional,
    google_secret_manager_secret_version.generated,
    google_sql_user.app,
    google_sql_database.app,
  ]
}

# Unauthenticated invocation is safe here only because ingress is internal: the
# public internet cannot reach this service, and the frontend proxy carries no
# identity token to present.
resource "google_cloud_run_v2_service_iam_member" "api_invoker" {
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "web" {
  name                = local.web_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.web.email
    timeout         = "120s"

    scaling {
      min_instance_count = 0
      max_instance_count = var.web_max_instances
    }

    # All egress through the VPC, so calls to the backend's run.app URL arrive
    # as internal traffic and pass its internal-only ingress.
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.run.id
      }
      egress = "ALL_TRAFFIC"
    }

    containers {
      image = "${local.image_base}/frontend:${var.image_tag}"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi" # Cloud Run's minimum with a whole CPU allocated
        }
      }

      env {
        name  = "API_UPSTREAM"
        value = google_cloud_run_v2_service.api.uri
      }
    }
  }

  depends_on = [google_project_iam_member.web]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  name     = google_cloud_run_v2_service.web.name
  location = google_cloud_run_v2_service.web.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
