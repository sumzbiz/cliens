# PostgreSQL 16 on a private IP. PostGIS is not a Cloud SQL setting: the backend's
# entrypoint runs `CREATE EXTENSION IF NOT EXISTS postgis` before migrating, which
# the built-in user may do as a member of cloudsqlsuperuser.

resource "random_password" "db" {
  length = 32
  # Alphanumeric only: the password is embedded in connection URLs, where
  # characters such as @ / : # would need percent-encoding to parse correctly.
  special = false
}

resource "google_sql_database_instance" "main" {
  name                = "${var.name_prefix}-pg"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_size         = var.db_disk_gb
    disk_autoresize   = true

    deletion_protection_enabled = var.deletion_protection

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
      # Traffic never leaves the private peering. Requiring TLS would also need
      # driver-specific options in both connection URLs (asyncpg and psycopg
      # spell them differently); tracked in the README's known limitations.
      ssl_mode = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "20:30" # UTC; 02:00 IST, the quietest hour.
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [google_service_networking_connection.private_services]
}

resource "google_sql_database" "app" {
  name     = "climate_lien_score"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "app" {
  name     = "cls"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
}

locals {
  db_host     = google_sql_database_instance.main.private_ip_address
  db_userinfo = "${google_sql_user.app.name}:${random_password.db.result}"
  db_path     = "${local.db_host}:5432/${google_sql_database.app.name}"
}
