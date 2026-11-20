# Uptime, alerting, a log-based metric, and request logs exported to BigQuery.
#
# The backend writes Cloud Logging's own fields (severity, message, trace) when
# GOOGLE_CLOUD_PROJECT is set, so its JSON lines arrive as structured entries
# grouped by request.

locals {
  web_host = trimprefix(google_cloud_run_v2_service.web.uri, "https://")
  channels = var.alert_email == "" ? [] : [google_monitoring_notification_channel.email[0].id]
}

resource "google_monitoring_notification_channel" "email" {
  count = var.alert_email == "" ? 0 : 1

  display_name = "Cliens alerts"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

# Readiness through the public origin: exercises Caddy, the internal hop to the
# backend, the backend itself and its database in one probe.
resource "google_monitoring_uptime_check_config" "ready" {
  display_name = "${var.name_prefix} ready"
  timeout      = "10s"
  period       = "300s"

  http_check {
    path         = "/api/health/ready"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = local.web_host
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "uptime" {
  display_name          = "${var.name_prefix}: site not ready"
  combiner              = "OR"
  notification_channels = local.channels

  conditions {
    display_name = "Readiness check failing"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\" AND metric.label.check_id=\"${google_monitoring_uptime_check_config.ready.uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "600s"
      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.project_id", "resource.label.host"]
      }
      trigger {
        count = 1
      }
    }
  }
}

resource "google_monitoring_alert_policy" "api_errors" {
  display_name          = "${var.name_prefix}: backend 5xx rate"
  combiner              = "OR"
  notification_channels = local.channels

  conditions {
    display_name = "5xx responses above threshold for 5 minutes"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.label.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.error_rate_threshold
      duration        = "300s"
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
      trigger {
        count = 1
      }
    }
  }
}

# Counts explanations discarded for citing a figure the engine did not compute.
# A rising count means the prompt or the model needs attention.
resource "google_logging_metric" "explanation_rejected" {
  name   = "${var.name_prefix}_explanation_rejected"
  filter = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"explanation_rejected_untraced_numbers\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
  }

  depends_on = [google_project_service.apis]
}

# --- Request log analytics in BigQuery ------------------------------------------

resource "google_bigquery_dataset" "logs" {
  dataset_id    = replace("${var.name_prefix}_logs", "-", "_")
  location      = var.region
  description   = "Completed backend requests, exported from Cloud Logging."
  friendly_name = "Cliens request logs"

  # A year of request history; older partitions expire on their own.
  default_partition_expiration_ms = 31536000000

  depends_on = [google_project_service.apis]
}

resource "google_logging_project_sink" "requests" {
  name        = "${var.name_prefix}-requests-to-bigquery"
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.logs.dataset_id}"
  filter      = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${local.api_service_name}\" AND jsonPayload.event=\"request_completed\""

  unique_writer_identity = true
  bigquery_options {
    use_partitioned_tables = true
  }
}

resource "google_bigquery_dataset_iam_member" "sink_writer" {
  dataset_id = google_bigquery_dataset.logs.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.requests.writer_identity
}
