locals {
  hosted_dashboards_enabled = var.hosted_observability != null && local.hosted_telemetry_enabled

  grafana_datasource_metrics_uid = "grafanacloud-prom"
  grafana_datasource_logs_uid    = "grafanacloud-logs"
  grafana_datasource_traces_uid  = "grafanacloud-traces"
  grafana_datasource_usage_uid   = "grafanacloud-prom"

  dashboard_template_vars = {
    environment = var.environment
    metrics_uid = local.grafana_datasource_metrics_uid
    logs_uid    = local.grafana_datasource_logs_uid
    traces_uid  = local.grafana_datasource_traces_uid
    usage_uid   = local.grafana_datasource_usage_uid
  }
}

resource "grafana_dashboard" "journey" {
  count       = local.hosted_dashboards_enabled ? 1 : 0
  folder      = "pawlocal-${var.environment}"
  overwrite   = true
  config_json = templatefile("${path.module}/dashboards/journey.json.tftpl", local.dashboard_template_vars)
}

resource "grafana_dashboard" "application" {
  count       = local.hosted_dashboards_enabled ? 1 : 0
  folder      = "pawlocal-${var.environment}"
  overwrite   = true
  config_json = templatefile("${path.module}/dashboards/application.json.tftpl", local.dashboard_template_vars)
}

resource "grafana_dashboard" "dependencies" {
  count       = local.hosted_dashboards_enabled ? 1 : 0
  folder      = "pawlocal-${var.environment}"
  overwrite   = true
  config_json = templatefile("${path.module}/dashboards/dependencies.json.tftpl", local.dashboard_template_vars)
}

resource "grafana_dashboard" "releases" {
  count       = local.hosted_dashboards_enabled ? 1 : 0
  folder      = "pawlocal-${var.environment}"
  overwrite   = true
  config_json = templatefile("${path.module}/dashboards/releases.json.tftpl", local.dashboard_template_vars)
}

resource "grafana_dashboard" "telemetry" {
  count       = local.hosted_dashboards_enabled ? 1 : 0
  folder      = "pawlocal-${var.environment}"
  overwrite   = true
  config_json = templatefile("${path.module}/dashboards/telemetry.json.tftpl", local.dashboard_template_vars)
}

resource "grafana_dashboard" "incidents" {
  count       = local.hosted_dashboards_enabled ? 1 : 0
  folder      = "pawlocal-${var.environment}"
  overwrite   = true
  config_json = templatefile("${path.module}/dashboards/incidents.json.tftpl", local.dashboard_template_vars)
}
