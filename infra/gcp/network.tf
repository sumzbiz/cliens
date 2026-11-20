# A private network for Cloud SQL and Cloud Run.
#
# Cloud SQL has no public IP at all; it is reached over private services access
# (VPC peering). Cloud Run joins the subnet through Direct VPC egress, which needs
# no Serverless VPC Access connector VMs.

resource "google_compute_network" "vpc" {
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "run" {
  name    = "${var.name_prefix}-run"
  region  = var.region
  network = google_compute_network.vpc.id

  # Direct VPC egress takes instance IPs from this range: a /24 covers the
  # instance ceilings in variables.tf with room for revisions overlapping.
  ip_cidr_range = "10.10.0.0/24"

  # Lets the frontend reach the backend's internal-only run.app URL through the
  # VPC, and lets instances reach Google APIs without public egress.
  private_ip_google_access = true
}

# The range Google allocates Cloud SQL addresses from, peered into the VPC.
resource "google_compute_global_address" "private_services" {
  name          = "${var.name_prefix}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}
