output "environment_targets" {
  description = "Non-secret public endpoints, resources, and deployment IAM role ARNs, keyed by environment."
  value = { for name, config in local.environments : name => {
    frontend_url       = "https://${config.hostname}.${trimsuffix(var.root_domain, ".")}"
    api_health_url     = "https://${config.api_name}.${trimsuffix(var.root_domain, ".")}/health"
    instance_name      = aws_lightsail_instance.api[name].name
    static_ip          = aws_lightsail_static_ip.api[name].ip_address
    api_hostname       = "${config.api_name}.${trimsuffix(var.root_domain, ".")}"
    frontend_bucket    = aws_s3_bucket.frontend[name].bucket
    distribution_id    = aws_cloudfront_distribution.app[name].id
    dsql_cluster_arn   = aws_dsql_cluster.app[name].arn
    dsql_endpoint      = "${aws_dsql_cluster.app[name].identifier}.dsql.${var.aws_region}.on.aws"
    app_iam_user       = aws_iam_user.app[name].name
    dsql_database_role = config.database_role
    deploy_role_arn    = aws_iam_role.github_deploy[name].arn
  } }
}

output "dsql_auth_alert_topic_arn" {
  description = "Present only when DSQL data-event capture and an alert email are configured. Confirm the SNS subscription before relying on delivery."
  value       = try(aws_sns_topic.dsql_auth[0].arn, null)
}
