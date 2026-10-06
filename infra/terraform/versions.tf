terraform {
  required_version = ">= 1.10.0"

  backend "s3" {}

  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "3.8.1"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = var.project_name
      ManagedBy   = "Terraform"
      Environment = var.environment
    }
  }
}
