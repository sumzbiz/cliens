# What the instance does on first boot.
#
# Installs Docker, pulls the secrets it is allowed to read, writes the .env the
# Compose stack expects, and creates the directory the deploy script uploads
# into. It deliberately does not start the stack: there is no image and no
# frontend build on the box yet. `deploy/deploy.sh` does that.

locals {
  user_data = <<-CLOUDINIT
    #!/usr/bin/env bash
    set -euxo pipefail

    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl unzip

    # Docker from Docker's own repository rather than Ubuntu's, because the
    # distribution package lags and ships the old `docker-compose` v1 rather than
    # the `docker compose` plugin this stack uses.
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    systemctl enable --now docker
    usermod -aG docker ubuntu

    # The AWS CLI is how the instance reads its own secrets from Parameter Store.
    ARCH=$(uname -m)
    curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$${ARCH}.zip" -o /tmp/awscli.zip
    unzip -q /tmp/awscli.zip -d /tmp
    /tmp/aws/install
    rm -rf /tmp/awscli.zip /tmp/aws

    install -d -o ubuntu -g ubuntu /opt/bqs /opt/bqs/site

    # Fetch every parameter under this deployment's prefix in one call and write
    # the .env Compose reads. Written 0600 and owned by ubuntu: the file holds
    # the database password and the Sarvam keys.
    fetch() {
      aws ssm get-parameter \
        --region ${var.aws_region} \
        --name "${local.parameter_prefix}/$1" \
        --with-decryption \
        --query 'Parameter.Value' \
        --output text 2>/dev/null || true
    }

    POSTGRES_PASSWORD=$(fetch postgres_password)
    SARVAM_PRIMARY=$(fetch sarvam_api_key_primary)
    SARVAM_SECONDARY=$(fetch sarvam_api_key_secondary)
    MAPBOX_TOKEN=$(fetch mapbox_access_token)

    cat > /opt/bqs/.env <<ENVFILE
    POSTGRES_USER=bqs
    POSTGRES_PASSWORD=$${POSTGRES_PASSWORD}
    POSTGRES_DB=building_quality_score

    PUBLIC_HOST=${var.public_host}
    PUBLIC_ORIGIN=${local.public_origin}

    API_IMAGE=bqs-backend:latest

    SARVAM_API_KEY_PRIMARY=$${SARVAM_PRIMARY}
    SARVAM_API_KEY_SECONDARY=$${SARVAM_SECONDARY}
    SARVAM_TTS_SPEAKER=kavitha
    SARVAM_TTS_LANGUAGE=ta-IN
    MAPBOX_ACCESS_TOKEN=$${MAPBOX_TOKEN}
    ENVFILE

    chown ubuntu:ubuntu /opt/bqs/.env
    chmod 600 /opt/bqs/.env

    touch /opt/bqs/.provisioned
  CLOUDINIT

  # The origin the browser will use, which is what the app's CORS check compares
  # against. ":80" means no domain was set, so it is the Elastic IP over plain
  # HTTP; anything else is a real hostname and therefore HTTPS, because Caddy
  # obtains a certificate for it automatically.
  public_origin = var.public_host == ":80" ? "http://${aws_eip.app.public_ip}" : "https://${var.public_host}"
}
