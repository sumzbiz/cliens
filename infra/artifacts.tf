# Where deploy artifacts land on their way to the instance.
#
# The instance has no SSH port and no key pair, so nothing can be copied to it
# directly. Instead the deploy script uploads here and then asks SSM to run a
# command on the instance that pulls from here — the instance's IAM role is what
# grants the read, so no credentials ever travel with the artifacts.
#
# The image is built on the instance rather than pushed to ECR. Every heavy
# dependency (numpy, scikit-learn, shapely, Pillow) publishes prebuilt manylinux
# wheels for both x86_64 and arm64, so building there is fast, and it avoids both
# cross-architecture emulation and pushing a ~700 MB image over a home uplink.

resource "aws_s3_bucket" "artifacts" {
  bucket_prefix = "bqs-deploy-"
  force_destroy = true # holds only build output; nothing here is a source of truth
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Build output is superseded on every deploy, so old versions are just cost.
resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    id     = "expire-old-artifacts"
    status = "Enabled"

    filter {}

    expiration {
      days = 7
    }
  }
}

resource "aws_iam_role_policy" "read_artifacts" {
  name_prefix = "bqs-read-artifacts-"
  role        = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.artifacts.arn
      }
    ]
  })
}
