output "url" {
  description = "The deployed site. This is the address to open."
  value       = local.public_origin
}

output "public_ip" {
  description = "Elastic IP of the instance. Point an A record here if using a domain."
  value       = aws_eip.app.public_ip
}

output "instance_id" {
  description = "EC2 instance id, for `aws ssm start-session --target <id>`."
  value       = aws_instance.app.id
}

output "ssm_session_command" {
  description = "Open a shell on the instance without SSH or a key pair."
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.aws_region}"
}

output "artifact_bucket" {
  description = "S3 bucket the deploy script uploads to; the instance pulls from it."
  value       = aws_s3_bucket.artifacts.id
}

output "region" {
  description = "Region everything was created in."
  value       = var.aws_region
}
