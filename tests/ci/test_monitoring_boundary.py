"""Exhaustive official-catalog check for the boundary-only SSM compaction."""

import fnmatch
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class MonitoringBoundaryTests(unittest.TestCase):
    def test_ssm_action_families_match_exactly_the_existing_six_catalog_actions(self):
        catalog = json.loads(
            (ROOT / "tests/ci/fixtures/aws-ssm-action-catalog.json").read_text()
        )
        self.assertEqual(catalog["version"], "v1.5")
        self.assertEqual(len(catalog["actions"]), 164)
        self.assertEqual(
            catalog["source_sha256"],
            "c7de3c0eb97c48594a268629e5bcea9f3f05e1605d138bfa5e9ea5c4292e1ee7",
        )
        source = (
            ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf"
        ).read_text()
        patterns = json.loads(re.search(r'actions = (\["ssm:[^\n]+\])', source)[1])
        matched = {
            name
            for name in catalog["actions"]
            if any(
                fnmatch.fnmatchcase(("ssm:" + name).lower(), pattern.lower())
                for pattern in patterns
            )
        }
        literal = {
            "GetParameter",
            "PutParameter",
            "DeleteParameter",
            "AddTagsToResource",
            "ListTagsForResource",
            "RemoveTagsFromResource",
        }
        self.assertEqual(matched, literal)
        identity = (
            ROOT / "infra/terraform/modules/pawlocal-environment/configuration.tf"
        ).read_text()
        actions = set(re.findall(r'"ssm:([A-Za-z*]+)"', identity))
        self.assertEqual(actions, literal)
        self.assertNotIn("*", "".join(actions))
        for name in (
            "GetParameters",
            "GetParameterHistory",
            "GetParametersByPath",
            "DescribeParameters",
            "PutResourcePolicy",
        ):
            self.assertFalse(
                any(
                    fnmatch.fnmatchcase(("ssm:" + name).lower(), p.lower())
                    for p in patterns
                )
            )

    def test_public_resource_ceiling_excludes_existing_and_future_bootstrap_and_secret_paths(
        self,
    ):
        source = (
            ROOT / "infra/terraform/iam-bootstrap/environment_permissions.tf"
        ).read_text()
        components = json.loads(re.search(r"for component in (\[[^\n]+\])", source)[1])
        base = "arn:aws:ssm:ap-southeast-2:111111111111:parameter/pawlocal/development/"
        patterns = [base + "config/" + component for component in components]
        allowed = lambda value: any(fnmatch.fnmatchcase(value, p) for p in patterns)
        for suffix in (
            "observability/enabled",
            "grafana/stack-url",
            "grafana/otlp-endpoint",
            "grafana/otlp-instance-id",
            "grafana/faro-collector-url",
            "oncall/webhook-url",
        ):
            self.assertTrue(allowed(base + "config/" + suffix))
        for suffix in (
            "config/iam/runtime-role-arn",
            "config/iam/future-key",
            "config/aws/account-id",
            "config/terraform/future-key",
            "secrets/grafana/otlp-token",
            "secrets/grafana/webhook-hmac",
            "secrets/oncall/dispatch-app-private-key",
        ):
            self.assertFalse(allowed(base + suffix))
        self.assertFalse(
            allowed(
                base.replace("/development/", "/production/")
                + "config/grafana/stack-url"
            )
        )
        self.assertFalse(
            allowed(
                base.replace("111111111111", "222222222222")
                + "config/grafana/stack-url"
            )
        )
        self.assertFalse(
            allowed(
                base.replace("ap-southeast-2", "us-east-1") + "config/grafana/stack-url"
            )
        )
        # This is deliberately a namespace ceiling: exact identity grants must
        # exclude unowned future names even though the ceiling covers them.
        self.assertTrue(allowed(base + "config/grafana/unowned-future-key"))

    def test_application_writer_intersection_denies_unowned_public_family_keys(self):
        module = ROOT / "infra/terraform/modules/pawlocal-environment"
        configuration = (module / "configuration.tf").read_text()
        hosted = (module / "hosted-observability.tf").read_text()
        base = re.search(
            r"configuration_suffixes\s*=\s*setunion\(local.hosted_public_suffixes,\s*toset\(\[(.*?)\]\)",
            configuration,
            re.DOTALL,
        )
        extra = re.search(
            r"hosted_public_suffixes\s*=\s*toset\(\[(.*?)\]\)", hosted, re.DOTALL
        )
        owned = set(re.findall(r'"([a-z/-]+)"', base[1] + extra[1]))
        self.assertEqual(len(owned), 17)
        for suffix in (
            "grafana/stack-url",
            "grafana/faro-collector-url",
            "observability/enabled",
        ):
            self.assertIn(suffix, owned)
        for suffix in (
            "grafana/unowned-future-key",
            "other-public-service/future",
            "oncall/webhook-url",
            "iam/runtime-role-arn",
            "secrets/grafana/otlp-token",
        ):
            self.assertNotIn(suffix, owned)
        self.assertIn("resources = local.configuration_parameter_arns", configuration)
        self.assertIn(
            "for suffix in sort(tolist(local.configuration_suffixes))", configuration
        )
