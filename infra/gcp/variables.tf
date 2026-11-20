variable "project_id" {
  description = "Google Cloud project to deploy into. Must be registered for Earth Engine."
  type        = string
}

variable "region" {
  description = "Region for every regional resource. asia-south1 (Mumbai) is the closest to Tamil Nadu."
  type        = string
  default     = "asia-south1"
}

variable "name_prefix" {
  description = "Prefix for resource names."
  type        = string
  default     = "cliens"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,18}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-20 lowercase letters, digits or hyphens."
  }
}

variable "image_tag" {
  description = "Tag of the backend and frontend images in Artifact Registry. deploy.sh passes the git commit."
  type        = string
  default     = "latest"
}

# --- Database -----------------------------------------------------------------

variable "db_tier" {
  description = "Cloud SQL machine tier. db-g1-small (shared core, 1.7 GB) is ample for this workload."
  type        = string
  default     = "db-g1-small"
}

variable "db_disk_gb" {
  description = "Initial Cloud SQL disk size in GB; autoresize grows it."
  type        = number
  default     = 10
}

variable "deletion_protection" {
  description = "Protect the database from `terraform destroy`. Set false only to tear down deliberately."
  type        = bool
  default     = true
}

# --- Cloud Run ----------------------------------------------------------------

variable "api_min_instances" {
  description = "Warm backend instances. 0 scales to zero (cold starts run migrations and load the model)."
  type        = number
  default     = 0
}

variable "api_max_instances" {
  description = "Upper bound on backend instances; bounds cost and Cloud SQL connections."
  type        = number
  default     = 4
}

variable "web_max_instances" {
  description = "Upper bound on frontend (Caddy) instances."
  type        = number
  default     = 4
}

# --- Application configuration -------------------------------------------------

variable "custom_domain" {
  description = "Public hostname for the app, e.g. cliens.example.com. Empty serves only the run.app URL."
  type        = string
  default     = ""
}

variable "gemini_model" {
  description = "Gemini model used for plain-language explanations."
  type        = string
  default     = "gemini-3.8-flash"
}

variable "gemini_fallback_models" {
  description = "Comma-separated Gemini models tried in order when gemini_model is overloaded or unavailable."
  type        = string
  default     = "gemini-3.5-flash-lite"
}

variable "optional_secrets" {
  description = <<-EOT
    API keys the app can use when present. Terraform creates an empty Secret
    Manager secret for each; their values are added from the operator's local .env
    by deploy.sh and never pass through Terraform or its state.
  EOT
  type        = set(string)
  default = [
    "GEMINI_API_KEY",
    "SARVAM_API_KEY_PRIMARY",
    "SARVAM_API_KEY_SECONDARY",
    "MAPBOX_ACCESS_TOKEN",
  ]
}

variable "populated_secrets" {
  description = <<-EOT
    The subset of optional_secrets that has a value, and so is mounted into the
    backend. A secret with no version cannot be mounted: the revision would fail
    to start. deploy.sh computes this list after uploading.
  EOT
  type        = set(string)
  default     = []

  validation {
    condition     = length(setsubtract(var.populated_secrets, var.optional_secrets)) == 0
    error_message = "populated_secrets must be a subset of optional_secrets."
  }
}

# --- Observability ------------------------------------------------------------

variable "alert_email" {
  description = "Address for uptime and error-rate alerts. Empty creates the alert policies without a channel."
  type        = string
  default     = ""
}

variable "error_rate_threshold" {
  description = "Backend 5xx responses per second, sustained for five minutes, that raise an alert."
  type        = number
  default     = 0.1
}
