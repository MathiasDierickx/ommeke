variable "aws_region" {
  description = "AWS-regio voor state en deployments."
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Korte naam/prefix voor alle AWS-resources."
  type        = string
  default     = "lusmaker"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,28}[a-z0-9]$", var.project_name))
    error_message = "project_name gebruikt 3-30 kleine letters, cijfers of streepjes."
  }
}

variable "github_repository" {
  description = "GitHub-repository als owner/name."
  type        = string

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository moet owner/name zijn."
  }
}

variable "github_oidc_subjects" {
  description = <<-EOT
    Exacte toegestane GitHub OIDC sub-claims. Leeg gebruikt het legacy subject
    repo:<owner/name>:ref:refs/heads/main. Vul voor nieuwe repositories het
    immutable subject met owner- en repository-ID's in.
  EOT
  type        = list(string)
  default     = []
}

variable "github_oidc_provider_arn" {
  description = "Bestaande GitHub OIDC-provider ARN; null maakt er één aan."
  type        = string
  default     = null
  nullable    = true
}
