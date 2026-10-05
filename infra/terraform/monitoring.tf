resource "aws_cloudwatch_log_metric_filter" "http_errors" {
  name           = "${local.name}-http-errors"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "{ $.event = \"http\" && $.status >= 500 }"
  metric_transformation {
    name          = "HttpErrors"
    namespace     = "Ommeke/${local.name}"
    value         = "1"
    default_value = 0
  }
}

# SNS-topic voor de alarmen hieronder; bestaat alleen wanneer monitoring aan staat.
resource "aws_sns_topic" "alarms" {
  count = var.enable_application_monitoring ? 1 : 0
  name  = "${local.name}-alarms"
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.enable_application_monitoring && var.alarm_email != null ? 1 : 0
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alarm_actions = concat(
    var.monitoring_alarm_actions,
    aws_sns_topic.alarms[*].arn,
  )
}

resource "aws_cloudwatch_metric_alarm" "http_errors" {
  count               = var.enable_application_monitoring ? 1 : 0
  alarm_name          = "${local.name}-http-errors"
  alarm_description   = "Minstens vijf HTTP-serverfouten in vijf minuten. Zie docs/OPERATIONS.md."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 5
  period              = 300
  statistic           = "Sum"
  metric_name         = "HttpErrors"
  namespace           = "Ommeke/${local.name}"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_metric_alarm" "duration" {
  count               = var.enable_application_monitoring && var.image_uri != null ? 1 : 0
  alarm_name          = "${local.name}-slow-requests"
  alarm_description   = "p95 Lambda-duur boven vier minuten; voorlopige pilotgrens, na baseline bijstellen."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 240000
  period              = 300
  extended_statistic  = "p95"
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  dimensions          = { FunctionName = aws_lambda_function.app[0].function_name }
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  ok_actions          = local.alarm_actions
}

resource "aws_cloudwatch_dashboard" "pilot" {
  count          = var.enable_application_monitoring ? 1 : 0
  dashboard_name = "${local.name}-pilot"
  dashboard_body = jsonencode({ widgets = [
    {
      type = "metric", x = 0, y = 0, width = 12, height = 6
      properties = {
        region = var.aws_region, title = "Lambda duur (p50/p95)", view = "timeSeries", period = 300
        metrics = [
          ["AWS/Lambda", "Duration", "FunctionName", local.name, { stat = "p50" }],
          ["AWS/Lambda", "Duration", "FunctionName", local.name, { stat = "p95" }]
        ]
      }
    },
    {
      type = "metric", x = 12, y = 0, width = 12, height = 6
      properties = {
        region = var.aws_region, title = "Fouten en throttling", view = "timeSeries", period = 300, stat = "Sum"
        metrics = [
          ["Ommeke/${local.name}", "HttpErrors"],
          ["AWS/Lambda", "Throttles", "FunctionName", local.name],
          ["AWS/Lambda", "Errors", "FunctionName", local.name]
        ]
      }
    }
  ] })
}

# Preserve addresses for installations that already created these resources.
moved {
  from = aws_cloudwatch_metric_alarm.http_errors
  to   = aws_cloudwatch_metric_alarm.http_errors[0]
}
moved {
  from = aws_cloudwatch_dashboard.pilot
  to   = aws_cloudwatch_dashboard.pilot[0]
}
