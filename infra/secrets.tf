# Application secrets, in SSM Parameter Store as SecureString.
#
# Parameter Store rather than Secrets Manager: this is a handful of static values
# with no rotation requirement, and Parameter Store's standard tier is free where
# Secrets Manager is $0.40 per secret per month. If these ever need automatic
# rotation, that is the reason to move.
#
# They are fetched by the instance at boot rather than passed through user data,
# because user data is readable by anything on the host that can reach the
# instance metadata service — including a compromised container.

locals {
  parameter_prefix = "/building-quality-score/${var.environment}"

  optional_secret_values = {
    sarvam_api_key_primary   = var.sarvam_api_key_primary
    sarvam_api_key_secondary = var.sarvam_api_key_secondary
    mapbox_access_token      = var.mapbox_access_token
  }

  # Which optional secrets were actually supplied. Sarvam and Mapbox are genuinely
  # optional — the app degrades to no voice and to zoom-19 imagery without them —
  # so writing empty parameters would create things that exist but mean nothing.
  #
  # `nonsensitive` wraps the emptiness test, never the value. for_each keys become
  # resource addresses, so Terraform refuses a set derived from sensitive data;
  # whether a key was provided is not itself a secret, but its contents are, and
  # those stay marked all the way into the parameter below.
  present_optional_secrets = toset([
    for name, value in local.optional_secret_values : name
    if nonsensitive(value) != ""
  ])
}

resource "aws_ssm_parameter" "postgres_password" {
  name        = "${local.parameter_prefix}/postgres_password"
  description = "Password for the application's Postgres role."
  type        = "SecureString"
  value       = var.postgres_password
}

resource "aws_ssm_parameter" "optional" {
  for_each = local.present_optional_secrets

  name  = "${local.parameter_prefix}/${each.key}"
  type  = "SecureString"
  value = local.optional_secret_values[each.key]
}
