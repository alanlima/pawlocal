"""Reject private/ambiguous operator bindings before saved Terraform plans."""

import importlib.util
import json
import os
import unittest
from unittest.mock import patch
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hosted_operator", ROOT / ".github/scripts/validate-hosted-observability.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PUBLIC = {
    "enabled": False,
    "stack_url": "https://fixture.grafana.net/",
}


class HostedOperatorTests(unittest.TestCase):
    def test_public_modes_and_null_are_valid(self):
        module.validate("null", "111111111111", "ap-southeast-2")
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                module.validate(
                    json.dumps({**PUBLIC, "enabled": enabled}),
                    "111111111111",
                    "ap-southeast-2",
                )

    def test_disabled_config_does_not_require_stack_url(self):
        # stack_url is only required when enabled or frontend_enabled is true
        module.validate(
            json.dumps({"enabled": False}), "111111111111", "ap-southeast-2"
        )
        module.validate(
            json.dumps({"enabled": False, "frontend_enabled": False}),
            "111111111111",
            "ap-southeast-2",
        )
        # enabled=true without stack_url must fail
        with self.assertRaisesRegex(ValueError, "stack_url"):
            module.validate(
                json.dumps({"enabled": True}), "111111111111", "ap-southeast-2"
            )
        # frontend_enabled=true without stack_url must also fail
        with self.assertRaisesRegex(ValueError, "stack_url"):
            module.validate(
                json.dumps({"enabled": False, "frontend_enabled": True}),
                "111111111111",
                "ap-southeast-2",
            )

    def test_browser_only_needs_no_otlp_and_requires_strict_frontend_boolean(self):
        value = dict(PUBLIC)
        value["frontend_enabled"] = True
        module.validate(json.dumps(value), "111111111111", "ap-southeast-2")
        for bad in (None, 0, "true"):
            with self.assertRaises(ValueError):
                module.validate(json.dumps(value | {"frontend_enabled": bad}), "111111111111", "ap-southeast-2")

    def test_discovery_mode_allows_public_bindings_with_optional_slug_and_app_name(self):
        module.validate(json.dumps(PUBLIC | {"enabled": True}), "111111111111", "ap-southeast-2")
        module.validate(json.dumps(PUBLIC | {"enabled": True, "stack_slug": "fixture"}), "111111111111", "ap-southeast-2")
        module.validate(json.dumps(PUBLIC | {"enabled": True, "faro_app_name": "pawlocal-dev"}), "111111111111", "ap-southeast-2")

    def test_discovery_mode_allows_datasource_bindings(self):
        config = {
            **PUBLIC,
            "enabled": True,
            "datasources": {
                "metrics": {"uid": "prom-1", "name": "grafanacloud-prom"},
                "logs": {"uid": "logs-1"},
                "traces": {"uid": "traces-1"},
                "usage": {"uid": "usage-1"},
            },
            "metrics_datasource_uid": "prom-1",
            "logs_datasource_uid": "logs-1",
            "traces_datasource_uid": "traces-1",
            "usage_datasource_uid": "usage-1",
        }
        res = module.validate(json.dumps(config), "111111111111", "ap-southeast-2")
        self.assertEqual(res["datasources"]["metrics"]["uid"], "prom-1")

        bad_binding = {
            **PUBLIC,
            "enabled": True,
            "datasources": {
                "metrics": {"uid": "prom-1", "access_token": "secret"},
            },
        }
        with self.assertRaisesRegex(ValueError, "Unknown field.*access_token"):
            module.validate(json.dumps(bad_binding), "111111111111", "ap-southeast-2")

    def test_resolve_owning_stack_url_retains_former_stack_when_disabled(self):
        self.assertEqual(
            module.resolve_owning_stack_url({"stack_url": "https://custom.grafana.net"}, "ap-southeast-2"),
            "https://custom.grafana.net",
        )
        with patch.dict(os.environ, {"PAWLOCAL_GRAFANA_URL": "https://former.grafana.net"}):
            self.assertEqual(
                module.resolve_owning_stack_url(None, "ap-southeast-2"),
                "https://former.grafana.net",
            )
        with patch.dict(os.environ, {"PAWLOCAL_GRAFANA_URL": "", "PAWLOCAL_ENVIRONMENT": ""}):
            with self.assertRaises(module.MissingStackUrlError):
                module.resolve_owning_stack_url(None, "ap-southeast-2")
            with self.assertRaises(module.MissingStackUrlError):
                module.resolve_owning_stack_url({"enabled": True}, "ap-southeast-2")

    def test_missing_stack_url_error_is_value_error_subclass(self):
        self.assertTrue(issubclass(module.MissingStackUrlError, ValueError))

    def test_resolve_owning_stack_url_checks_recorded_ssm_and_prevents_unmigrated_switch(self):
        class MockSSM:
            def get_parameter(self, Name):
                if Name == "/pawlocal/production/config/grafana/stack-url":
                    return {"Parameter": {"Value": "https://stack-a.grafana.net"}}
                raise Exception("ParameterNotFound")

        with patch.dict(os.environ, {"PAWLOCAL_ENVIRONMENT": "production"}):
            with patch("boto3.client", return_value=MockSSM()):
                # When disabled, retains recorded stack-a
                self.assertEqual(
                    module.resolve_owning_stack_url(None, "ap-southeast-2"),
                    "https://stack-a.grafana.net",
                )
                # When steady-state matches stack-a, returns stack-a
                self.assertEqual(
                    module.resolve_owning_stack_url({"stack_url": "https://stack-a.grafana.net"}, "ap-southeast-2"),
                    "https://stack-a.grafana.net",
                )
                # When input attempts switch to stack-b without migration, raises ValueError
                with self.assertRaisesRegex(ValueError, "differs from recorded owning stack"):
                    module.resolve_owning_stack_url({"stack_url": "https://stack-b.grafana.net"}, "ap-southeast-2")

        class FailingSSM:
            def get_parameter(self, Name):
                raise RuntimeError("AccessDeniedException: not authorized")

        with patch.dict(os.environ, {"PAWLOCAL_ENVIRONMENT": "production"}):
            with patch("boto3.client", return_value=FailingSSM()):
                with self.assertRaises(RuntimeError):
                    module.resolve_owning_stack_url(None, "ap-southeast-2")

    def test_private_or_inconsistent_bindings_are_denied_even_when_disabled(self):
        for override in (
            {"token": "private-sentinel"},
            {"enabled": "false"},
            {"enabled": 0},
            {"otlp_endpoint": "https://user:private@gateway.grafana.net/otlp"},
            {"otlp_endpoint": "https://gateway.grafana.net/otlp?token=private"},
            {"otlp_endpoint": "https://gateway.grafana.net/otlp"},
            {"otlp_instance_id": "12345"},
            {"otlp_instance_id": "private-user-identity"},
            {"faro_collector_url": "https://faro.grafana.net/collect/public-key"},
            {"faro_collector_url": "https://foreign.example.test/collect/public"},
            {"faro_app_name": "invalid_name!"},
            {"stack_slug": "invalid_slug!"},
            {"stack_slug": "https://slug.grafana.net"},
            {
                "kms_key_arn": "arn:aws:kms:ap-southeast-2:222222222222:key/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            },
        ):
            with (
                self.subTest(override=override),
                self.assertRaises((ValueError, TypeError)),
            ):
                module.validate(
                    json.dumps({**PUBLIC, **override}), "111111111111", "ap-southeast-2"
                )

    def test_duplicate_field_is_denied(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            module.validate(
                '{"enabled": false, "enabled": true}', "111111111111", "ap-southeast-2"
            )

    def test_each_saved_plan_validates_operator_object_first(self):
        for filename in (
            "terraform-environment.yml",
            "terraform-environment-destroy.yml",
        ):
            with self.subTest(filename=filename):
                workflow = yaml.safe_load(
                    (ROOT / ".github/workflows" / filename).read_text()
                )
                selected = 0
                for job in workflow["jobs"].values():
                    if "TF_VAR_hosted_observability" not in job.get("env", {}):
                        continue
                    selected += 1
                    steps = job["steps"]
                    validation = next(
                        i
                        for i, step in enumerate(steps)
                        if "validate-hosted-observability.py" in step.get("run", "")
                    )
                    plan = next(
                        i
                        for i, step in enumerate(steps)
                        if " plan " in step.get("run", "")
                    )
                    self.assertLess(validation, plan)
                    self.assertIn(
                        "|| 'null'", job["env"]["TF_VAR_hosted_observability"]
                    )
                self.assertEqual(
                    selected, 1 if filename == "terraform-environment.yml" else 2
                )
