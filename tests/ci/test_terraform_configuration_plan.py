"""Strict application-plan ownership checks for generated public configuration."""
from __future__ import annotations

import copy
import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/terraform-environment-plan.py"
spec = importlib.util.spec_from_file_location("configuration_plan_guard", SCRIPT)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def parameter_change(environment="development", suffix="auth/client-id", actions=None):
    values = {
        "name": f"/pawlocal/{environment}/config/{suffix}",
        "type": "String",
        "tier": "Standard",
        "overwrite": None,
        "value": "unreported-private-fixture-value",
    }
    selected_actions = ["create"] if actions is None else actions
    return {
        "address": f'module.pawlocal.aws_ssm_parameter.configuration["{suffix}"]',
        "type": "aws_ssm_parameter",
        "index": suffix,
        "change": {
            "actions": selected_actions,
            "before": None if selected_actions == ["create"] else copy.deepcopy(values),
            "after": values,
        },
    }


class ConfigurationPlanOwnershipTests(unittest.TestCase):
    def validate(self, change, environment="development", release_only=False):
        return guard.validate({"resource_changes": [change]}, environment, release_only)

    def test_all_twelve_owned_parameters_are_accepted_for_both_environments(self):
        for environment in ("development", "production"):
            with self.subTest(environment=environment):
                changes = [parameter_change(environment, suffix) for suffix in sorted(guard.APPLICATION_PARAMETER_SUFFIXES)]
                rows = guard.validate({"resource_changes": changes}, environment, False)
                self.assertEqual(rows, [("aws_ssm_parameter", "create")] * 12)
                summary = guard.render(rows, environment)
                self.assertNotIn("unreported-private-fixture-value", summary)
                self.assertNotIn("/pawlocal/", summary)

    def test_owned_update_and_noop_are_accepted_but_release_changes_are_not(self):
        for environment in ("development", "production"):
            for actions in (["update"], ["no-op"]):
                with self.subTest(environment=environment, actions=actions):
                    change = parameter_change(environment, actions=actions)
                    rows = self.validate(change, environment)
                    self.assertEqual(rows, [] if actions == ["no-op"] else [("aws_ssm_parameter", "update")])
                    if actions != ["no-op"]:
                        with self.assertRaisesRegex(SystemExit, "release-only"):
                            self.validate(change, environment, True)

    def test_cross_environment_bootstrap_and_unknown_sources_are_rejected(self):
        for actions in (["create"], ["update"], ["no-op"]):
            for change in (
                parameter_change("production", actions=actions),
                parameter_change(suffix="iam/runtime-role-arn", actions=actions),
                parameter_change(suffix="aws/account-id", actions=actions),
                parameter_change(suffix="terraform/plan-bucket", actions=actions),
                parameter_change(suffix="auth/unknown-setting", actions=actions),
            ):
                with self.subTest(actions=actions, address=change["address"]):
                    with self.assertRaises(SystemExit):
                        self.validate(change)

    def test_name_address_type_tier_and_adoption_cannot_escape_ownership(self):
        mutations = (
            ("name", "/pawlocal/production/config/auth/client-id"),
            ("name", "/pawlocal/development/secrets/auth/client-id"),
            ("name", "/pawlocal/development/config/auth/another-name"),
            ("type", "SecureString"),
            ("tier", "Advanced"),
            ("overwrite", True),
        )
        for field, value in mutations:
            for side in ("before", "after"):
                with self.subTest(field=field, side=side):
                    change = parameter_change(actions=["update"])
                    change["change"][side][field] = value
                    with self.assertRaises(SystemExit) as rejected:
                        self.validate(change)
                    self.assertNotIn("unreported-private-fixture-value", str(rejected.exception))
        change = parameter_change()
        change["address"] = 'module.other.aws_ssm_parameter.configuration["auth/client-id"]'
        with self.assertRaises(SystemExit):
            self.validate(change)

    def test_deletes_replacements_and_imports_remain_rejected(self):
        for actions in (["delete"], ["delete", "create"], ["create", "delete"]):
            with self.subTest(actions=actions):
                change = parameter_change(actions=actions)
                if actions == ["delete"]:
                    change["change"]["after"] = None
                with self.assertRaises(SystemExit):
                    self.validate(change)
        for actions in (["create"], ["no-op"]):
            for location in ("change", "resource"):
                with self.subTest(actions=actions, location=location):
                    change = parameter_change(actions=actions)
                    target = change["change"] if location == "change" else change
                    target["importing"] = {"id": "not-an-adoption-permission"}
                    with self.assertRaisesRegex(SystemExit, "import"):
                        self.validate(change)

    def test_guard_allowlist_matches_only_application_owned_terraform_keys(self):
        source = (ROOT / "infra/terraform/modules/pawlocal-environment/configuration.tf").read_text(encoding="utf-8")
        declaration = re.search(r"configuration_suffixes\s*=\s*toset\(\[(.*?)\]\)", source, re.S)
        assert declaration
        self.assertEqual(set(re.findall(r'"([a-z/-]+)"', declaration.group(1))), guard.APPLICATION_PARAMETER_SUFFIXES)


if __name__ == "__main__":
    unittest.main()
