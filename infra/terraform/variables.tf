variable "aws_region" {
  description = "AWS-regio voor de applicatie."
  type        = string
  default     = "eu-west-1"
}

variable "project_name" {
  description = "Korte resourceprefix."
  type        = string
  default     = "lusmaker"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,28}[a-z0-9]$", var.project_name))
    error_message = "project_name gebruikt 3-30 kleine letters, cijfers of streepjes."
  }
}

variable "environment" {
  description = "Deploymentomgeving."
  type        = string
  default     = "prod"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,15}$", var.environment))
    error_message = "environment gebruikt maximaal 16 kleine letters, cijfers of streepjes."
  }
}

variable "image_uri" {
  description = "Immutable ECR image URI, bij voorkeur repository@sha256:digest."
  type        = string
  default     = null
  nullable    = true
}

variable "region_slug" {
  description = "Regioslug die in het containerimage is gebundeld."
  type        = string
  default     = "vlaanderen"

  validation {
    condition     = can(regex("^[a-z0-9]+(?:-[a-z0-9]+)*$", var.region_slug))
    error_message = "region_slug gebruikt kleine letters, cijfers en streepjes."
  }
}

variable "lambda_memory_mb" {
  description = "Lambda-geheugen; 3008 MB werkt ook in accounts met de lage startquota."
  type        = number
  default     = 3008

  validation {
    condition     = var.lambda_memory_mb >= 1769 && var.lambda_memory_mb <= 10240
    error_message = "lambda_memory_mb moet tussen 1769 en 10240 liggen."
  }
}

variable "lambda_ephemeral_storage_mb" {
  description = "Schrijfbare /tmp voor de gekopieerde GraphHopper-cache."
  type        = number
  default     = 10240

  validation {
    condition     = var.lambda_ephemeral_storage_mb >= 512 && var.lambda_ephemeral_storage_mb <= 10240
    error_message = "lambda_ephemeral_storage_mb moet tussen 512 en 10240 liggen."
  }
}

variable "max_concurrency" {
  description = "Optionele reserved-concurrencycap; null gebruikt de accountquota."
  type        = number
  default     = null
  nullable    = true

  validation {
    condition     = var.max_concurrency == null ? true : var.max_concurrency >= 1 && var.max_concurrency <= 10
    error_message = "max_concurrency moet null of een getal tussen 1 en 10 zijn."
  }
}

variable "java_opts" {
  description = "JVM heapinstellingen binnen het Lambda-geheugen."
  type        = string
  default     = "-Xms256m -Xmx2g"
}

variable "oauth_callback_urls" {
  description = "Toegestane OAuth callbacks van ChatGPT, Claude of een eigen client."
  type        = list(string)

  validation {
    condition = length(var.oauth_callback_urls) > 0 && alltrue([
      for url in var.oauth_callback_urls : can(regex("^https://|^http://localhost(?::[0-9]+)?/", url))
    ])
    error_message = "Geef minstens één HTTPS callback (of localhost voor development)."
  }
}

variable "oauth_logout_urls" {
  description = "Optionele OAuth logout redirects."
  type        = list(string)
  default     = []
}

variable "oauth_generate_secret" {
  description = "Maak een confidential Cognito client secret."
  type        = bool
  default     = true
}

variable "web_callback_urls" {
  description = "Cognito callbacks voor de publieke Next.js-app, inclusief trailing slash."
  type        = list(string)

  validation {
    condition = length(var.web_callback_urls) > 0 && alltrue([
      for url in var.web_callback_urls : can(regex("^https://|^http://localhost(?::[0-9]+)?/", url))
    ])
    error_message = "Geef minstens één HTTPS webcallback (of localhost voor development)."
  }
}

variable "web_logout_urls" {
  description = "Optionele logout redirects; leeg hergebruikt web_callback_urls."
  type        = list(string)
  default     = []
}

variable "cognito_domain_prefix" {
  description = "Globaal unieke Cognito domainprefix; null gebruikt project-account."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = var.cognito_domain_prefix == null || can(regex(
      "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$",
      var.cognito_domain_prefix
    ))
    error_message = "cognito_domain_prefix gebruikt 1-63 kleine letters, cijfers of streepjes."
  }
}

variable "cors_origins" {
  description = "Extra browser origins naast de origins uit web_callback_urls."
  type        = list(string)
  default     = []
}

variable "bedrock_model_id" {
  description = "EU cross-region inference profile voor Claude in Amazon Bedrock."
  type        = string
  # Tijdelijk Nova Pro: Claude wacht op Marketplace-betaalactivatie
  # (terugzetten naar eu.anthropic.claude-sonnet-4-6 zodra de billing-case rond is)
  default = "eu.amazon.nova-pro-v1:0"

  validation {
    condition     = can(regex("^eu\\.(anthropic\\.claude|amazon\\.nova)-[a-z0-9.:-]+$", var.bedrock_model_id))
    error_message = "bedrock_model_id moet een Europees Anthropic Claude of Amazon Nova inference profile zijn."
  }
}

variable "chat_point_in_time_recovery" {
  description = "Schakel betaalde DynamoDB point-in-time recovery in voor chatgeschiedenis."
  type        = bool
  default     = false
}

variable "protect_user_data" {
  description = "Bescherm Cognito en DynamoDB tegen een onbedoelde Terraform destroy."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Korte logretentie beperkt opslagkosten."
  type        = number
  default     = 7

  validation {
    condition = contains([
      1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096,
      1827, 2192, 2557, 2922, 3288, 3653
    ], var.log_retention_days)
    error_message = "log_retention_days moet een door CloudWatch ondersteunde waarde zijn."
  }
}

variable "monthly_budget_usd" {
  description = "Maandelijks AWS-budget; alarm alleen wanneer billing_email is gezet."
  type        = number
  default     = 10
}

variable "billing_email" {
  description = "Optionele ontvanger van 80% forecast en 100% actual budgetmeldingen."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.billing_email == null || can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.billing_email))
    error_message = "billing_email moet null of een geldig e-mailadres zijn."
  }
}

variable "force_destroy_data" {
  description = "Sta verwijderen van een niet-lege data-bucket toe."
  type        = bool
  default     = false
}

variable "force_destroy_ecr" {
  description = "Sta verwijderen van een ECR-repository met images toe."
  type        = bool
  default     = false
}
