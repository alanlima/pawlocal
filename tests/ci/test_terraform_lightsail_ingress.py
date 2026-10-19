from __future__ import annotations

import unittest
import importlib.util
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PLAN_VALIDATOR_PATH = ROOT / "ops/validate-lightsail-ingress-plan.py"
PLAN_VALIDATOR_SPEC = importlib.util.spec_from_file_location("ingress_plan_validator", PLAN_VALIDATOR_PATH)
assert PLAN_VALIDATOR_SPEC and PLAN_VALIDATOR_SPEC.loader
PLAN_VALIDATOR = importlib.util.module_from_spec(PLAN_VALIDATOR_SPEC)
PLAN_VALIDATOR_SPEC.loader.exec_module(PLAN_VALIDATOR)
SEEDED_PLACES_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "seeded_places_validator", ROOT / "ops/validate-seeded-places.py"
)
assert SEEDED_PLACES_VALIDATOR_SPEC and SEEDED_PLACES_VALIDATOR_SPEC.loader
SEEDED_PLACES_VALIDATOR = importlib.util.module_from_spec(SEEDED_PLACES_VALIDATOR_SPEC)
SEEDED_PLACES_VALIDATOR_SPEC.loader.exec_module(SEEDED_PLACES_VALIDATOR)


class TerraformLightsailIngressTests(unittest.TestCase):
    def test_temporary_cidr_is_environment_scoped_and_baseline_is_required(self) -> None:
        root_variables = (ROOT / "infra/terraform/variables.tf").read_text(encoding="utf-8")
        module_variables = (ROOT / "infra/terraform/fullstack/variables.tf").read_text(encoding="utf-8")
        module = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")

        for source in (root_variables, module_variables):
            self.assertIn('type        = map(list(string))', source)
            self.assertIn('temporary_ssh_environment', source)
            self.assertIn('temporary_ssh_cidr', source)
            self.assertIn('can(regex("/32$", var.temporary_ssh_cidr))', source)
            self.assertIn('var.temporary_ssh_environment == null ? true :', source)
            self.assertIn('var.temporary_ssh_cidr == null ? true :', source)

        self.assertIn('var.temporary_ssh_environment == environment ? [var.temporary_ssh_cidr] : []', module)
        self.assertIn('for_each = local.effective_ssh_cidr_blocks[each.key]', module)
        self.assertIn('from_port         = 80', module)
        self.assertIn('from_port         = 443', module)

    def test_terraform_ingress_role_is_environment_and_resource_scoped(self) -> None:
        module = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        self.assertIn('resource "aws_iam_role" "github_terraform_ingress"', module)
        self.assertIn('environment:${each.key}', module)
        self.assertIn('"arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate"', module)
        self.assertIn('"arn:aws:s3:::${var.terraform_state_bucket_name}/pawlocal/terraform.tfstate.tflock"', module)
        self.assertIn('"lightsail:PutInstancePublicPorts"', module)
        self.assertIn('"lightsail:CloseInstancePublicPorts"', module)
        self.assertIn('"ec2:DescribeAvailabilityZones"', module)
        self.assertIn('"dsql:GetCluster"', module)
        self.assertIn('"dsql:GetVpcEndpointServiceName"', module)
        self.assertIn('"cognito-idp:DescribeUserPool", "cognito-idp:DescribeUserPoolClient"', module)
        self.assertIn('resources = [aws_lightsail_instance.api[each.key].arn]', module)

    def test_ingress_helper_targets_and_checks_one_firewall_update(self) -> None:
        script = (ROOT / "ops/terraform-lightsail-ingress.sh").read_text(encoding="utf-8")
        self.assertIn('module.fullstack.aws_lightsail_instance_public_ports.api[', script)
        self.assertIn('-target="$target"', script)
        self.assertNotIn('-refresh=false', script)
        self.assertIn('ops/validate-lightsail-ingress-plan.py', script)
        self.assertNotIn('aws lightsail ', script.lower())

    @staticmethod
    def _firewall(ssh_cidrs: list[str], web443: list[str] | None = None) -> dict[str, Any]:
        return {
            "instance_name": "pawlocal-development-api",
            "port_info": [
                {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidrs": ["0.0.0.0/0"], "ipv6_cidrs": ["::/0"], "cidr_list_aliases": []},
                {"protocol": "tcp", "from_port": 443, "to_port": 443, "cidrs": web443 or ["0.0.0.0/0"], "ipv6_cidrs": ["::/0"], "cidr_list_aliases": []},
                *[
                    {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidrs": [cidr], "ipv6_cidrs": [], "cidr_list_aliases": []}
                    for cidr in ssh_cidrs
                ],
            ]
        }

    @staticmethod
    def _plan(
        before: dict[str, Any],
        after: dict[str, Any],
        address: str | None = None,
        actions: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "resource_changes": [
                {
                    "address": address or 'module.fullstack.aws_lightsail_instance_public_ports.api["development"]',
                    "change": {"actions": actions or ["update"], "before": before, "after": after},
                }
            ]
        }

    def test_plan_validator_allows_only_one_runner_cidr_open_or_restore(self) -> None:
        baseline = {"development": ["198.51.100.8/32"], "production": ["198.51.100.8/32"]}
        baseline_json = json.dumps(baseline)
        runner = "203.0.113.10/32"
        before_open = self._firewall(baseline["development"])
        after_open = self._firewall([*baseline["development"], runner])
        PLAN_VALIDATOR.validate(self._plan(before_open, after_open), "open", "development", runner, baseline_json)
        PLAN_VALIDATOR.validate(
            self._plan(before_open, after_open, actions=["delete", "create"]),
            "open", "development", runner, baseline_json,
        )

        PLAN_VALIDATOR.validate(self._plan(after_open, before_open), "restore", "development", runner, baseline_json)

    def test_plan_validator_rejects_replacement_that_changes_web_or_broadens_ssh(self) -> None:
        baseline = {"development": ["198.51.100.8/32"], "production": ["198.51.100.8/32"]}
        baseline_json = json.dumps(baseline)
        runner = "203.0.113.10/32"
        before = self._firewall(baseline["development"])
        after = self._firewall([*baseline["development"], runner])
        for changed in (
            self._firewall(["0.0.0.0/0", runner]),
            self._firewall([*baseline["development"], runner], ["192.0.2.3/32"]),
        ):
            with self.assertRaises(ValueError):
                PLAN_VALIDATOR.validate(
                    self._plan(before, changed, actions=["delete", "create"]),
                    "open", "development", runner, baseline_json,
                )

    def test_plan_validator_rejects_ssh_alias_and_wrong_instance(self) -> None:
        baseline = {"development": ["198.51.100.8/32"], "production": ["198.51.100.8/32"]}
        baseline_json = json.dumps(baseline)
        runner = "203.0.113.10/32"
        before = self._firewall(baseline["development"])
        after = self._firewall([*baseline["development"], runner])
        after["port_info"][-1]["cidr_list_aliases"] = ["lightsail-connect"]
        with self.assertRaisesRegex(ValueError, "CIDR aliases"):
            PLAN_VALIDATOR.validate(self._plan(before, after), "open", "development", runner, baseline_json)

        after = self._firewall([*baseline["development"], runner])
        after["instance_name"] = "pawlocal-production-api"
        with self.assertRaisesRegex(ValueError, "unexpected Lightsail instance"):
            PLAN_VALIDATOR.validate(self._plan(before, after), "open", "development", runner, baseline_json)

    def test_plan_validator_allows_create_only_restore_recovery(self) -> None:
        baseline = {"development": ["198.51.100.8/32"], "production": ["198.51.100.8/32"]}
        baseline_json = json.dumps(baseline)
        runner = "203.0.113.10/32"
        restore_state = self._firewall(baseline["development"])
        plan = self._plan(None, restore_state, actions=["create"])
        PLAN_VALIDATOR.validate(plan, "restore", "development", runner, baseline_json)

        for web443 in (["192.0.2.3/32"], ["0.0.0.0/0"]):
            altered = self._firewall(baseline["development"], web443)
            if web443 == ["0.0.0.0/0"]:
                altered["port_info"].append({
                    "protocol": "tcp", "from_port": 443, "to_port": 443,
                    "cidrs": ["0.0.0.0/0"], "ipv6_cidrs": ["::/0"], "cidr_list_aliases": [],
                })
            with self.assertRaisesRegex(ValueError, "exactly one unchanged"):
                PLAN_VALIDATOR.validate(
                    self._plan(None, altered, actions=["create"]),
                    "restore", "development", runner, baseline_json,
                )

    def test_plan_validator_rejects_zero_updates_and_changes_to_web_or_other_rules(self) -> None:
        baseline = {"development": ["198.51.100.8/32"], "production": ["198.51.100.8/32"]}
        baseline_json = json.dumps(baseline)
        runner = "203.0.113.10/32"
        before = self._firewall(baseline["development"])
        after = self._firewall([*baseline["development"], runner])

        for plan in (
            {"resource_changes": []},
            self._plan(before, after, 'module.fullstack.aws_lightsail_instance_public_ports.api["production"]'),
            self._plan(before, self._firewall([*baseline["development"], runner], ["192.0.2.3/32"])),
            {
                "resource_changes": [
                    *self._plan(before, after)["resource_changes"],
                    {"address": "aws_s3_bucket.example", "change": {"actions": ["update"], "before": {}, "after": {}}},
                ]
            },
        ):
            with self.subTest(plan=plan):
                with self.assertRaises(ValueError):
                    PLAN_VALIDATOR.validate(plan, "open", "development", runner, baseline_json)

    def test_dev_and_prod_deploys_share_noncanceling_ingress_concurrency(self) -> None:
        development = (ROOT / ".github/workflows/fullstack-release.yml").read_text(encoding="utf-8")
        production = (ROOT / ".github/workflows/deploy-production.yml").read_text(encoding="utf-8")
        for workflow in (development, production):
            self.assertIn('group: pawlocal-lightsail-deploy', workflow)
            self.assertIn('cancel-in-progress: false', workflow)
            self.assertIn('ops/terraform-lightsail-ingress.sh restore', workflow)
            self.assertIn("steps.enable-ingress.outputs.ingress_state_may_have_changed == 'true'", workflow)

        self.assertIn('workflow_dispatch:', development)
        self.assertIn('github.event_name == \'workflow_dispatch\'', development)
        self.assertGreaterEqual(development.count("github.event_name != 'workflow_dispatch' || github.ref == 'refs/heads/main'"), 2)
        self.assertIn("github.ref == 'refs/heads/main' && vars.PAWLOCAL_DEPLOY_MODE", development)
        self.assertIn("inputs.seed_development == true", development)
        self.assertIn("github.event_name == 'workflow_dispatch'", development)
        self.assertIn("type: boolean", development)
        self.assertIn('ops/run-deployment-adapter.sh seed --environment development', development)

    def test_bootstrap_seed_is_dev_only_and_uses_protected_readonly_credentials(self) -> None:
        bootstrap = (ROOT / "infra/terraform/fullstack/templates/bootstrap.sh.tftpl").read_text(encoding="utf-8")
        self.assertIn('"$1" == seed-development', bootstrap)
        self.assertIn("environment=development", bootstrap)
        self.assertIn('PAWLOCAL_EXPECTED_DSQL_ENDPOINT="$expected_endpoint"', bootstrap)
        self.assertIn('/etc/pawlocal/aws-credentials:/run/pawlocal/aws-credentials:ro', bootstrap)
        self.assertIn('"$image" python -m pawlocal.seed_places --environment development', bootstrap)
        self.assertIn('/usr/local/sbin/pawlocal-deploy seed-development *', bootstrap)

    def test_seed_helper_accepts_generated_dsql_url_and_rejects_wrong_target(self) -> None:
        bootstrap = (ROOT / "infra/terraform/fullstack/templates/bootstrap.sh.tftpl").read_text(encoding="utf-8")
        match = re.search(r"database_url_regex='(.+)'", bootstrap)
        self.assertIsNotNone(match, "seed helper must validate the DSQL URL format")
        bash_ere = match.group(1).replace("${aws_region}", "ap-southeast-2")
        self.assertIn(r"auroradsql\+psycopg", bash_ere)

        def matches(url: str) -> bool:
            return re.fullmatch(bash_ere.removeprefix("^").removesuffix("$"), url) is not None

        generated = (
            "auroradsql+psycopg://pawlocal_development_app@"
            "cluster-123.dsql.ap-southeast-2.on.aws/postgres?application_name=pawlocal-development"
        )
        self.assertTrue(matches(generated), f"Generated endpoint was rejected by the seed helper ERE: {bash_ere}")
        self.assertFalse(matches(generated.replace("auroradsql+psycopg", "postgresql")))
        self.assertFalse(matches(generated.replace("ap-southeast-2", "us-east-1")))
        self.assertFalse(matches(generated.replace("pawlocal_development_app", "pawlocal_production_app")))

    def test_seeded_content_validator_requires_both_places_and_emits_names(self) -> None:
        valid_page = {
            "items": [{"name": "Orleigh Park"}, {"name": "Whites Hill Reserve"}],
            "page": 1,
            "page_size": 100,
            "total": 2,
        }
        self.assertEqual(
            SEEDED_PLACES_VALIDATOR.validate_page(valid_page),
            ["Orleigh Park", "Whites Hill Reserve"],
        )
        with self.assertRaisesRegex(ValueError, "Whites Hill Reserve"):
            SEEDED_PLACES_VALIDATOR.validate_page(
                {**valid_page, "items": [{"name": "Orleigh Park"}], "total": 1}
            )
        with self.assertRaisesRegex(ValueError, "Orleigh Park"):
            SEEDED_PLACES_VALIDATOR.validate_page({"items": []})


if __name__ == "__main__":
    unittest.main()
