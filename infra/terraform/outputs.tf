output "ecr_repository_url" {
  value       = aws_ecr_repository.app.repository_url
  description = "ECR-doel voor de Lambda-container."
}

output "mcp_endpoint" {
  value       = var.image_uri == null ? null : "${trimsuffix(aws_lambda_function_url.app[0].function_url, "/")}/mcp"
  description = "Remote MCP Streamable HTTP endpoint."
}

output "health_endpoint" {
  value       = var.image_uri == null ? null : "${trimsuffix(aws_lambda_function_url.app[0].function_url, "/")}/health"
  description = "Publieke lichte healthcheck."
}

output "oauth_issuer" {
  value       = local.oauth_issuer
  description = "Cognito OIDC issuer."
}

output "oauth_authorization_endpoint" {
  value       = "https://${aws_cognito_user_pool_domain.users.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/authorize"
  description = "OAuth 2.0 authorization endpoint."
}

output "oauth_token_endpoint" {
  value       = "https://${aws_cognito_user_pool_domain.users.domain}.auth.${var.aws_region}.amazoncognito.com/oauth2/token"
  description = "OAuth 2.0 token endpoint."
}

output "oauth_client_id" {
  value       = aws_cognito_user_pool_client.mcp.id
  description = "OAuth client-ID voor de MCP-connector."
}

output "oauth_client_secret" {
  value       = aws_cognito_user_pool_client.mcp.client_secret
  description = "OAuth client secret; leeg bij een public client."
  sensitive   = true
}

output "cognito_user_pool_id" {
  value       = aws_cognito_user_pool.users.id
  description = "Pool waarin een beheerder eindgebruikers aanmaakt."
}

output "state_bucket" {
  value       = aws_s3_bucket.data.id
  description = "Versleutelde tenant-state en artifacts."
}

output "zero_idle_compute" {
  value = {
    provisioned_concurrency = 0
    reserved_concurrency    = var.max_concurrency
    persistent_compute      = false
  }
  description = "Compute-instellingen die scale-to-zero afdwingen."
}
