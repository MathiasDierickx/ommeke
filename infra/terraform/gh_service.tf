# Alle resources en lookups zijn opt-in; Lambda houdt zonder deze vlag zijn env.
data "aws_vpc" "gh" {
  count   = var.gh_service_enabled ? 1 : 0
  default = true
}

data "aws_subnets" "gh" {
  count = var.gh_service_enabled ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.gh[0].id]
  }
}

data "aws_subnet" "gh" {
  count = var.gh_service_enabled ? 1 : 0
  id    = sort(data.aws_subnets.gh[0].ids)[0]
}

data "aws_ami" "gh" {
  count       = var.gh_service_enabled ? 1 : 0
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  count = var.gh_service_enabled ? 1 : 0
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "random_password" "gh_origin" {
  count   = var.gh_service_enabled ? 1 : 0
  length  = 48
  special = false
}

resource "aws_security_group" "gh" {
  count       = var.gh_service_enabled ? 1 : 0
  name        = "${local.name}-gh"
  description = "GraphHopper uitsluitend via CloudFront origin-facing"
  vpc_id      = data.aws_vpc.gh[0].id
  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront[0].id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "gh" {
  count = var.gh_service_enabled ? 1 : 0
  name  = "${local.name}-gh"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy" "gh" {
  count = var.gh_service_enabled ? 1 : 0
  role  = aws_iam_role.gh[0].id
  name  = "read-region-pack"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "arn:${data.aws_partition.current.partition}:s3:::${var.gh_pack_bucket}/region-packs/${var.region_slug}.tar.gz"
    }]
  })
}

resource "aws_iam_instance_profile" "gh" {
  count = var.gh_service_enabled ? 1 : 0
  name  = "${local.name}-gh"
  role  = aws_iam_role.gh[0].name
}

resource "aws_ebs_volume" "gh" {
  count             = var.gh_service_enabled ? 1 : 0
  availability_zone = data.aws_subnet.gh[0].availability_zone
  type              = "gp3"
  size              = var.gh_volume_size_gb
  encrypted         = true
  tags              = { Name = "${local.name}-gh-graph" }
}

resource "aws_instance" "gh" {
  count                       = var.gh_service_enabled ? 1 : 0
  ami                         = data.aws_ami.gh[0].id
  instance_type               = var.gh_instance_type
  subnet_id                   = data.aws_subnet.gh[0].id
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.gh[0].id]
  iam_instance_profile        = aws_iam_instance_profile.gh[0].name
  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/gh-user-data.sh.tftpl", {
    volume_id     = replace(aws_ebs_volume.gh[0].id, "-", "")
    pack_sha256   = var.gh_pack_sha256
    pack_bucket   = var.gh_pack_bucket
    region_slug   = var.region_slug
    origin_secret = random_password.gh_origin[0].result
    aws_region    = var.aws_region
  })
  metadata_options {
    http_tokens = "required"
  }
  root_block_device {
    volume_type = "gp3"
    volume_size = 16
    encrypted   = true
  }
  tags       = { Name = "${local.name}-gh" }
  depends_on = [aws_iam_role_policy.gh]
  lifecycle {
    precondition {
      condition     = var.gh_pack_bucket != ""
      error_message = "gh_pack_bucket (TF_STATE_BUCKET) is verplicht met gh_service_enabled=true."
    }
  }
}

resource "aws_volume_attachment" "gh" {
  count       = var.gh_service_enabled ? 1 : 0
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.gh[0].id
  instance_id = aws_instance.gh[0].id
}

resource "aws_cloudfront_distribution" "gh" {
  count   = var.gh_service_enabled ? 1 : 0
  enabled = true
  comment = "${local.name}-gh"
  origin {
    domain_name = aws_instance.gh[0].public_dns
    origin_id   = "graphhopper"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60
    }
  }
  default_cache_behavior {
    target_origin_id       = "graphhopper"
    viewer_protocol_policy = "https-only"
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    min_ttl                = 0
    default_ttl            = 0
    max_ttl                = 0
    forwarded_values {
      query_string = true
      headers      = ["X-Ommeke-Origin", "Content-Type"]
      cookies { forward = "none" }
    }
  }
  custom_error_response {
    error_code            = 403
    error_caching_min_ttl = 0
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}
