output "app_url" {
  description = "The public URL of the application."
  value       = google_cloud_run_v2_service.web.uri
}

output "api_url" {
  description = "The backend's internal-only URL (reachable from the VPC, not the internet)."
  value       = google_cloud_run_v2_service.api.uri
}

output "image_repository" {
  description = "Artifact Registry path images are pushed to."
  value       = local.image_base
}

output "build_service_account" {
  description = "Service account Cloud Build runs as."
  value       = google_service_account.build.email
}

output "build_staging_bucket" {
  description = "Bucket Cloud Build stages source in."
  value       = google_storage_bucket.build_staging.name
}

output "database_instance" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.main.name
}

output "database_private_ip" {
  description = "Cloud SQL private IP."
  value       = google_sql_database_instance.main.private_ip_address
}

output "logs_dataset" {
  description = "BigQuery dataset holding exported request logs."
  value       = google_bigquery_dataset.logs.dataset_id
}
