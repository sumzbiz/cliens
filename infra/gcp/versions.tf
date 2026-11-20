# Provider and state configuration.
#
# State lives in a GCS bucket that deploy/gcp/deploy.sh creates before the first
# `terraform init` (a bucket cannot hold the state of the configuration that
# creates it). The bucket name is passed at init time, not hardcoded, so the same
# configuration deploys to any project:
#
#   terraform init -backend-config="bucket=<project>-tfstate"

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 8.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.0, < 8.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "gcs" {
    prefix = "cliens/gcp"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Declared so resources that only exist in beta can be added without touching the
# provider setup; nothing here needs it yet.
provider "google-beta" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {
  project_id = var.project_id
}
