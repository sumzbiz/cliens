# A custom domain for the frontend, through a global external Application Load
# Balancer.
#
# Cloud Run's own domain mapping is not offered in asia-south1, so the domain
# reaches the service through a serverless network endpoint group behind a load
# balancer with a static IP and a Google-managed certificate. DNS needs one A
# record: <custom_domain> -> output "custom_domain_ip". The certificate stays in
# PROVISIONING until that record resolves, then renews itself.
#
# Everything here is skipped while var.custom_domain is empty.

locals {
  domain_enabled = var.custom_domain != ""
}

resource "google_compute_global_address" "web" {
  count = local.domain_enabled ? 1 : 0
  name  = "${var.name_prefix}-web-ip"

  depends_on = [google_project_service.apis]
}

resource "google_compute_region_network_endpoint_group" "web" {
  count                 = local.domain_enabled ? 1 : 0
  name                  = "${var.name_prefix}-web-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"

  cloud_run {
    service = google_cloud_run_v2_service.web.name
  }
}

resource "google_compute_backend_service" "web" {
  count                 = local.domain_enabled ? 1 : 0
  name                  = "${var.name_prefix}-web-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.web[0].id
  }
}

resource "google_compute_managed_ssl_certificate" "web" {
  count = local.domain_enabled ? 1 : 0
  # The name carries the domain so changing the domain creates a new certificate
  # before the old one is removed.
  name = "${var.name_prefix}-web-${substr(sha256(var.custom_domain), 0, 8)}"

  managed {
    domains = [var.custom_domain]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_url_map" "web" {
  count           = local.domain_enabled ? 1 : 0
  name            = "${var.name_prefix}-web"
  default_service = google_compute_backend_service.web[0].id
}

resource "google_compute_target_https_proxy" "web" {
  count            = local.domain_enabled ? 1 : 0
  name             = "${var.name_prefix}-web-https"
  url_map          = google_compute_url_map.web[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.web[0].id]
}

resource "google_compute_global_forwarding_rule" "web_https" {
  count                 = local.domain_enabled ? 1 : 0
  name                  = "${var.name_prefix}-web-https"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.web[0].address
  port_range            = "443"
  target                = google_compute_target_https_proxy.web[0].id
}

# Plain HTTP on the same IP only redirects to HTTPS.
resource "google_compute_url_map" "web_redirect" {
  count = local.domain_enabled ? 1 : 0
  name  = "${var.name_prefix}-web-redirect"

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "web_redirect" {
  count   = local.domain_enabled ? 1 : 0
  name    = "${var.name_prefix}-web-http"
  url_map = google_compute_url_map.web_redirect[0].id
}

resource "google_compute_global_forwarding_rule" "web_http" {
  count                 = local.domain_enabled ? 1 : 0
  name                  = "${var.name_prefix}-web-http"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.web[0].address
  port_range            = "80"
  target                = google_compute_target_http_proxy.web_redirect[0].id
}
