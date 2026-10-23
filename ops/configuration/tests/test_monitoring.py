"""Copy-only YAML behavior and protected-target regression tests."""

import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

import yaml
from test_integration import store_for, values
from test_reconcile import SENTINEL, FakeAPI, FakeSSM, Response, entry, module


class MonitoringTests(unittest.TestCase):
    def oncall(self):
        return [
            m
            for m in module.inventory_mappings("development")
            if m.github_environment == "oncall-development"
        ]

    def test_one_manifest_has_no_active_secret_copy(self):
        for environment in ("development", "production"):
            selected = module.inventory_mappings(environment)
            self.assertFalse(any(m.secret for m in selected))
            self.assertEqual(
                len({(m.github_environment, m.env_name) for m in selected}),
                len(selected),
            )

    def test_missing_source_warns_and_skips_in_both_modes(self):
        selected = self.oncall()
        for mode in ("audit", "enforce"):
            api = FakeAPI()
            messages = []
            result = module.reconcile(
                selected,
                module.ParameterStore(FakeSSM()),
                module.GitHub("alanlima/pawlocal", SENTINEL, api),
                mode=mode,
                report=messages.append,
            )
            self.assertEqual(result, {})
            self.assertTrue(
                any("WARNING missing-source" in message for message in messages)
            )
            self.assertFalse(api.variables)
            self.assertFalse(api.secrets)

    def test_missing_target_skips_before_source_read_in_both_modes(self):
        for mode in ("audit", "enforce"):
            source = FakeSSM()
            messages = []

            def missing(request, timeout):
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)

            result = module.reconcile(
                self.oncall(),
                module.ParameterStore(source),
                module.GitHub("alanlima/pawlocal", SENTINEL, missing),
                mode=mode,
                report=messages.append,
            )
            self.assertEqual(result, {})
            self.assertEqual(source.calls, [])
            self.assertTrue(
                any("WARNING missing-target" in message for message in messages)
            )

    def test_target_access_denied_is_not_missing(self):
        source = FakeSSM()

        def denied(request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        with self.assertRaises(module.ReconciliationError):
            module.reconcile(
                self.oncall(),
                module.ParameterStore(source),
                module.GitHub("alanlima/pawlocal", SENTINEL, denied),
                report=lambda _: None,
            )
        self.assertEqual(source.calls, [])

    def test_missing_optional_target_does_not_block_other_yaml_rows(self):
        ordinary = next(
            m
            for m in module.inventory_mappings("development")
            if m.github_environment == "development"
        )
        selected = [ordinary, *self.oncall()]
        store = store_for(selected, values("development"))
        api = FakeAPI()

        def transport(request, timeout):
            if "/environments/oncall-development" in request.full_url:
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            return api.__call__(request, timeout)

        result = module.reconcile(
            selected,
            store,
            module.GitHub("alanlima/pawlocal", SENTINEL, transport),
            mode="enforce",
            report=lambda _: None,
        )
        self.assertEqual(
            result, {ordinary.env_name: values("development")[ordinary.env_name]}
        )
        self.assertEqual([c["Name"] for c in store.client.calls], [ordinary.store_key])
        self.assertEqual(
            api.variables[("development", ordinary.env_name)],
            values("development")[ordinary.env_name],
        )

    def test_workflow_copy_only_interface_and_internal_destroy_boundary(self):
        root = Path(__file__).resolve().parents[3]
        workflow = yaml.safe_load(
            (root / ".github/workflows/reconcile-environment.yml").read_text()
        )
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(
            set(triggers["workflow_dispatch"]["inputs"]), {"environment", "mode"}
        )
        self.assertEqual(
            set(triggers["workflow_call"]["inputs"]),
            {"environment", "mode", "caller_holds_lifecycle_lock"},
        )
        cleanup = yaml.safe_load(
            (root / ".github/workflows/cleanup-destroyed-configuration.yml").read_text()
        )
        self.assertEqual(set(cleanup.get("on", cleanup.get(True))), {"workflow_call"})
        guard = cleanup["jobs"]["cleanup"]["steps"][0]["run"]
        self.assertIn("Terraform production destroy", guard)
        self.assertIn('"$DESTROY_CONFIRMED" == true', guard)
        self.assertIn("DESTROY production", guard)
        destroy = yaml.safe_load(
            (root / ".github/workflows/terraform-environment-destroy.yml").read_text()
        )
        caller = destroy["jobs"]["cleanup-generated-targets"]
        self.assertEqual(
            caller["uses"], "./.github/workflows/cleanup-destroyed-configuration.yml"
        )
        self.assertIn("needs.destroy-apply.result == 'success'", caller["if"])
        self.assertIn(
            "needs.prepare-plan.outputs.already_empty == 'true'", caller["if"]
        )

    def test_manifest_additions_require_no_python_inventory_update(self):
        data = entry(
            store_key="/pawlocal/{environment}/config/new-service/new-setting",
            env_name="NEW_PUBLIC_SETTING",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.yaml"
            path.write_text(yaml.safe_dump({"mappings": [data]}), encoding="utf-8")
            selected = module.load_mappings(path, "development")
            api = FakeAPI()
            result = module.reconcile(
                selected,
                store_for(selected, {"NEW_PUBLIC_SETTING": "enabled"}),
                module.GitHub("alanlima/pawlocal", SENTINEL, api),
                mode="enforce",
                report=lambda _: None,
            )
            self.assertEqual(result, {"NEW_PUBLIC_SETTING": "enabled"})
            self.assertEqual(
                module.configuration_outputs(result),
                {
                    "configuration": {"NEW_PUBLIC_SETTING": "enabled"},
                    "frontend_config": {},
                },
            )
            self.assertEqual(
                api.variables[("development", "NEW_PUBLIC_SETTING")], "enabled"
            )

    def test_existing_unrestricted_or_tag_target_denied_before_source_read(self):
        selected = self.oncall()
        for policy in (
            None,
            {"protected_branches": True, "custom_branch_policies": False},
            {"protected_branches": False, "custom_branch_policies": True},
        ):
            store = FakeSSM()

            def unsafe(request, timeout, selected_policy=policy):
                if request.full_url.endswith("/deployment-branch-policies"):
                    return Response(
                        {
                            "total_count": 1,
                            "branch_policies": [{"name": "main", "type": "tag"}],
                        }
                    )
                return Response(
                    {
                        "name": "oncall-development",
                        "deployment_branch_policy": selected_policy,
                    }
                )

            with (
                self.subTest(policy=policy),
                self.assertRaises(module.ReconciliationError),
            ):
                module.reconcile(
                    selected,
                    module.ParameterStore(store),
                    module.GitHub("alanlima/pawlocal", SENTINEL, unsafe),
                    report=lambda _: None,
                )
            self.assertEqual(store.calls, [])
