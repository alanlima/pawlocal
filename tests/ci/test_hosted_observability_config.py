"""Reject private/ambiguous operator bindings before saved Terraform plans."""

import importlib.util
import json
import unittest
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
    "faro_collector_url": "https://faro.grafana.net/collect/public-key",
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

    def test_browser_only_needs_no_otlp_and_requires_strict_frontend_boolean(self):
        value = dict(PUBLIC)
        value["frontend_enabled"] = True
        module.validate(json.dumps(value), "111111111111", "ap-southeast-2")
        for bad in (None, 0, "true"):
            with self.assertRaises(ValueError):
                module.validate(json.dumps(value | {"frontend_enabled": bad}), "111111111111", "ap-southeast-2")

    def test_discovery_mode_allows_public_bindings_with_optional_slug(self):
        module.validate(json.dumps(PUBLIC | {"enabled": True}), "111111111111", "ap-southeast-2")
        module.validate(json.dumps(PUBLIC | {"enabled": True, "stack_slug": "fixture"}), "111111111111", "ap-southeast-2")

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
            {"faro_collector_url": "https://foreign.example.test/collect/public"},
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
