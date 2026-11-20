# The instance, its network exposure, and how it gets its secrets.

resource "aws_security_group" "app" {
  name_prefix = "bqs-app-"
  description = "Building Quality Score: public web traffic in, everything out."
  vpc_id      = data.aws_vpc.default.id

  lifecycle {
    # The security group is referenced by the running instance, so a change that
    # forces replacement has to create the new group before destroying the old.
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.app.id
  description       = "HTTP. Caddy redirects to HTTPS, and serves the ACME challenge on this port."
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.app.id
  description       = "HTTPS"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

# Normally none of these exist. Postgres is deliberately absent from this list:
# it listens only on the Compose bridge network, so it is unreachable from
# outside the host regardless of what the security group says.
resource "aws_vpc_security_group_ingress_rule" "ssh" {
  for_each = toset(var.allowed_ssh_cidrs)

  security_group_id = aws_security_group.app.id
  description       = "SSH fallback; prefer SSM Session Manager."
  cidr_ipv4         = each.value
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
}

# Outbound must stay open: the app fetches satellite tiles from Esri, geocodes
# through Nominatim, and synthesises speech through Sarvam. Restricting egress
# would mean pinning third-party IP ranges that change without notice.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.app.id
  description       = "Outbound to Esri, Nominatim, Sarvam, and the package registries."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# ---------------------------------------------------------------------------
# Instance identity
#
# SSM rather than an SSH key pair: no port 22 open, no private key to distribute
# or lose, and every session is logged in CloudTrail.
# ---------------------------------------------------------------------------
resource "aws_iam_role" "instance" {
  name_prefix = "bqs-instance-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Read access scoped to this deployment's own parameters, so the instance can
# fetch its secrets at boot and nothing else in the account's Parameter Store.
resource "aws_iam_role_policy" "read_secrets" {
  name_prefix = "bqs-read-secrets-"
  role        = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter${local.parameter_prefix}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com" }
        }
      }
    ]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name_prefix = "bqs-instance-"
  role        = aws_iam_role.instance.name
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name

  user_data                   = local.user_data
  user_data_replace_on_change = true

  root_block_device {
    volume_size = var.root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  metadata_options {
    # IMDSv2 only. The v1 endpoint is reachable by any process on the host,
    # including a compromised container, and hands out the instance's role
    # credentials without authentication.
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  tags = { Name = "bqs-app" }
}

# A stable address across stop/start and instance replacement. Without it the
# public IP changes on every stop, which breaks DNS and any Let's Encrypt
# certificate tied to the name.
#
# Allocated standalone and associated separately, rather than with `instance` set
# here, to break a dependency cycle: the instance's user data needs the public
# address to write PUBLIC_ORIGIN, so the address has to exist before the instance
# does.
resource "aws_eip" "app" {
  domain = "vpc"
  tags   = { Name = "bqs-app" }
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
