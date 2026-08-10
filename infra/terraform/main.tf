data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name                  = "${var.project_name}-${var.environment}"
  account_id            = data.aws_caller_identity.current.account_id
  data_bucket_name      = "${local.name}-${local.account_id}-${var.aws_region}-data"
  cognito_domain_prefix = coalesce(var.cognito_domain_prefix, "${local.name}-${local.account_id}")
  oauth_issuer          = "https://cognito-idp.${var.aws_region}.amazonaws.com/${aws_cognito_user_pool.users.id}"
  cognito_domain        = "https://${aws_cognito_user_pool_domain.users.domain}.auth.${var.aws_region}.amazoncognito.com"
  web_logout_urls       = length(var.web_logout_urls) > 0 ? var.web_logout_urls : var.web_callback_urls
  web_origins           = [for url in var.web_callback_urls : regex("^https?://[^/]+", url)]
  cors_origins          = distinct(concat(var.cors_origins, local.web_origins))
  bedrock_foundation_id = trimprefix(var.bedrock_model_id, "eu.")
}

resource "aws_s3_bucket" "data" {
  bucket        = local.data_bucket_name
  force_destroy = var.force_destroy_data
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "trim-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_policy" "data_tls" {
  bucket = aws_s3_bucket.data.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.data.arn,
        "${aws_s3_bucket.data.arn}/*"
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.force_destroy_ecr

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Verwijder ongetagde buildlagen na één dag"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Bewaar de vijf recentste releases"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = { type = "expire" }
      }
    ]
  })
}

resource "aws_cognito_user_pool" "users" {
  name                     = "${local.name}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  deletion_protection      = var.protect_user_data ? "ACTIVE" : "INACTIVE"
  mfa_configuration        = "OPTIONAL"

  admin_create_user_config {
    allow_admin_create_user_only = false
  }

  software_token_mfa_configuration {
    enabled = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_domain" "users" {
  domain       = local.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.users.id
}

resource "aws_cognito_user_pool_client" "mcp" {
  name                                 = "${local.name}-mcp"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = var.oauth_generate_secret
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes = [
    "openid",
    "email",
    "profile",
    "aws.cognito.signin.user.admin"
  ]
  callback_urls                 = var.oauth_callback_urls
  logout_urls                   = var.oauth_logout_urls
  supported_identity_providers  = ["COGNITO"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "${local.name}-web"
  user_pool_id                         = aws_cognito_user_pool.users.id
  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes = [
    "openid",
    "email",
    "profile",
    "aws.cognito.signin.user.admin"
  ]
  callback_urls                 = var.web_callback_urls
  logout_urls                   = local.web_logout_urls
  supported_identity_providers  = ["COGNITO"]
  prevent_user_existence_errors = "ENABLED"
  enable_token_revocation       = true

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

resource "aws_dynamodb_table" "chat" {
  name         = "${local.name}-chat"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  deletion_protection_enabled = var.protect_user_data

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.chat_point_in_time_recovery
  }

  server_side_encryption {
    enabled = true
  }
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid       = "ListTenantState"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["tenants/*"]
    }
  }

  statement {
    sid = "ReadWriteTenantState"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]
    # tenants/* = privé draftstate per gebruiker; public/* = deel-referenties
    # (alleen {uid, draft_id}) voor read-only share-links.
    resources = [
      "${aws_s3_bucket.data.arn}/tenants/*",
      "${aws_s3_bucket.data.arn}/public/*"
    ]
  }

  statement {
    sid = "ReadWriteOwnChatPartitions"
    actions = [
      "dynamodb:BatchWriteItem",
      "dynamodb:DeleteItem",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:Query",
      "dynamodb:UpdateItem"
    ]
    resources = [aws_dynamodb_table.chat.arn]
  }

  statement {
    sid = "InvokeClaudeViaBedrock"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream"
    ]
    resources = [
      "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.bedrock_model_id}",
      "arn:${data.aws_partition.current.partition}:bedrock:*::foundation-model/${local.bedrock_foundation_id}"
    ]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.name}-runtime"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "app" {
  count = var.image_uri == null ? 0 : 1

  function_name                  = local.name
  package_type                   = "Image"
  image_uri                      = var.image_uri
  role                           = aws_iam_role.lambda.arn
  architectures                  = ["x86_64"]
  memory_size                    = var.lambda_memory_mb
  timeout                        = 900
  reserved_concurrent_executions = var.max_concurrency

  ephemeral_storage {
    size = var.lambda_ephemeral_storage_mb
  }

  environment {
    variables = {
      AWS_LWA_ASYNC_INIT          = "true"
      AWS_LWA_INVOKE_MODE         = "response_stream"
      JAVA_OPTS                   = var.java_opts
      LUSMAKER_BEDROCK_MODEL_ID   = var.bedrock_model_id
      LUSMAKER_BEDROCK_REGION     = var.aws_region
      LUSMAKER_CHAT_TABLE         = aws_dynamodb_table.chat.name
      LUSMAKER_AUTH_MODE          = "cognito"
      LUSMAKER_OAUTH_CLIENT_ID    = aws_cognito_user_pool_client.mcp.id
      LUSMAKER_OAUTH_CLIENT_IDS   = join(",", [aws_cognito_user_pool_client.mcp.id, aws_cognito_user_pool_client.web.id])
      LUSMAKER_OAUTH_ISSUER       = local.oauth_issuer
      LUSMAKER_OAUTH_SCOPE        = "aws.cognito.signin.user.admin"
      LUSMAKER_REGION             = var.region_slug
      LUSMAKER_STATE_BUCKET       = aws_s3_bucket.data.id
      LUSMAKER_TMP                = "/tmp/lusmaker"
      LUSMAKER_TOKEN_AUTH_METHODS = var.oauth_generate_secret ? "client_secret_basic,client_secret_post" : "none"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda
  ]

  lifecycle {
    precondition {
      condition     = try(startswith(var.image_uri, "${aws_ecr_repository.app.repository_url}@sha256:"), false)
      error_message = "image_uri moet de immutable digest-URI van de Lusmaker ECR-repository zijn."
    }
  }
}

# AWS_IAM is ongeschikt voor externe MCP OAuth-clients. Daarom is de URL
# publiek op AWS-niveau en valideert de app elke bearer token via Cognito.
resource "aws_lambda_function_url" "app" {
  count = var.image_uri == null ? 0 : 1

  function_name      = aws_lambda_function.app[0].function_name
  authorization_type = "NONE"
  invoke_mode        = "RESPONSE_STREAM"

  cors {
    allow_credentials = false
    allow_origins     = local.cors_origins
    allow_methods     = ["GET", "POST", "PATCH", "DELETE"]
    allow_headers = [
      "accept",
      "authorization",
      "content-type",
      "last-event-id",
      "mcp-protocol-version"
    ]
    expose_headers = ["mcp-session-id", "www-authenticate"]
    max_age        = 3600
  }
}

resource "aws_budgets_budget" "monthly" {
  count = var.billing_email == null ? 0 : 1

  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.billing_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.billing_email]
  }
}
