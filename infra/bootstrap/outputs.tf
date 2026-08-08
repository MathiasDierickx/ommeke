output "terraform_state_bucket" {
  value       = aws_s3_bucket.terraform_state.id
  description = "S3-bucket voor de applicatie-Terraform-state."
}

output "github_deploy_role_arn" {
  value       = aws_iam_role.github_deploy.arn
  description = "OIDC-role voor GitHub Actions."
}

output "github_oidc_subjects" {
  value       = local.github_subjects
  description = "Exacte GitHub subjects die de deployrol mogen aannemen."
}
