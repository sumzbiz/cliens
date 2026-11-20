# Building Quality Score — single-host infrastructure.
#
# One EC2 instance running the Compose stack in deploy/, with an Elastic IP so
# the address survives a stop/start, and SSM Session Manager instead of SSH keys.
#
# WHY ONE HOST RATHER THAN THE MANAGED SERVICES
# App Runner plus RDS plus CloudFront is the better production answer, but it is
# not the better answer for this workload today. The app makes heavy outbound
# calls (every map tile is fetched and recomposited server-side), so App Runner
# would need a VPC connector to reach a private RDS, and a VPC connector needs a
# NAT gateway — about $32/month before any data passes through it. The whole of
# this stack costs less than that NAT gateway alone.
#
# It also deploys in minutes rather than the ~45 the managed path spends waiting
# on RDS and CloudFront. What it gives up is real: no horizontal scaling, and the
# instance is a single point of failure. See README.md for what to change when
# that stops being acceptable.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "building-quality-score"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

# The default VPC is used deliberately. A purpose-built VPC would add subnets,
# route tables and an internet gateway to manage for a single public instance
# that needs none of the isolation they buy — the database is not exposed to the
# network at all, because it listens only on the Compose bridge.
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Canonical's official Ubuntu 24.04 LTS for the instance's architecture. Looked
# up rather than hardcoded: an AMI ID is region-specific and goes stale as
# Canonical publishes patched images.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-*-server-*"]
  }

  # x86_64 only. See the note on var.instance_type: the official PostGIS image
  # is amd64-only, so the whole stack is pinned to that architecture.
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}
