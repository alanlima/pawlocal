from __future__ import annotations

import copy
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

import yaml
from test_reconcile import ROOT, SENTINEL, FakeAPI, FakeSSM, module


def helper(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "ops/configuration" / filename
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


build = helper("build_config", "build-config.py")
cleanup = helper("cleanup_config", "cleanup.py")
collision = helper("collision_check", "check-collisions.py")


def values(environment):
    frontend = (
        "pawlocal-dev.example.test"
        if environment == "development"
        else "pawlocal.example.test"
    )
    api = "api-dev.example.test" if environment == "development" else "api.example.test"
    account = "123456789012"
    return {
        "PAWLOCAL_AWS_ACCOUNT_ID": account,
        "PAWLOCAL_TERRAFORM_PLAN_ROLE_ARN": f"arn:aws:iam::{account}:role/pawlocal-{environment}-terraform-plan",
        "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN": f"arn:aws:iam::{account}:role/pawlocal-{environment}-terraform-apply",
        "PAWLOCAL_TERRAFORM_PLAN_BUCKET": f"pawlocal-terraform-plans-{account}",
        "PAWLOCAL_RUNTIME_ROLE_ARN": f"arn:aws:iam::{account}:role/pawlocal-{environment}-dsql-runtime",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ARN": f"arn:aws:cloudfront::{account}:distribution/E123EXAMPLE",
        "PAWLOCAL_CLOUDFRONT_OAC_ARN": f"arn:aws:cloudfront::{account}:origin-access-control/E456EXAMPLE",
        "PAWLOCAL_DEPLOY_ROLE_ARN": f"arn:aws:iam::{account}:role/pawlocal-{environment}-github-deploy",
        "PAWLOCAL_PUBLIC_BASE_URL": f"https://{frontend}",
        "PAWLOCAL_API_HEALTH_URL": f"https://{api}/health",
        "PAWLOCAL_FRONTEND_BUCKET": f"pawlocal-{environment}-frontend-example",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID": "E123EXAMPLE",
        "VITE_API_BASE_URL": f"https://{api}/api/v1",
        "VITE_COGNITO_DOMAIN": f"https://pawlocal-{environment}-example.auth.ap-southeast-2.amazoncognito.com",
        "VITE_COGNITO_CLIENT_ID": "exampleclient123",
        "VITE_COGNITO_REDIRECT_URI": f"https://{frontend}/auth/callback",
        "VITE_COGNITO_LOGOUT_URI": f"https://{frontend}/",
        "VITE_COGNITO_SCOPES": "openid email profile",
    }


def mappings(environment):
    return module.load_mappings(
        ROOT / "ops/configuration/parameter-mapping.yaml", environment
    )


def store_for(selected, data):
    return module.ParameterStore(
        FakeSSM(
            {
                m.store_key: {
                    "Type": "SecureString" if m.secret else "String",
                    "Value": data[m.env_name],
                }
                for m in selected
                if m.env_name in data
            }
        )
    )


class CleanupAPI(FakeAPI):
    def __call__(self, request, timeout):
        if request.method == "DELETE":
            path = request.full_url.split("/environments/", 1)[1]
            target, kind, name = path.split("/")
            self.calls.append(request)
            (self.variables if kind == "variables" else self.secrets).pop(
                (target, name), None
            )
            from test_reconcile import Response

            return Response(None)
        if (
            "/secrets/" in request.full_url
            and not request.full_url.endswith("public-key")
            and request.method == "GET"
        ):
            target, _, name = request.full_url.split("/environments/", 1)[1].split("/")
            if (target, name) not in self.secrets:
                raise HTTPError(request.full_url, 404, "Not Found", {}, None)
            from test_reconcile import Response

            return Response({"name": name})
        return super().__call__(request, timeout)


class IntegrationTests(unittest.TestCase):
    def github(self, api):
        return module.GitHub("alanlima/pawlocal", SENTINEL, api)

    def test_enforce_reads_all_selected_values_before_any_write(self):
        for environment in ("development", "production"):
            data = values(environment)
            data.pop("VITE_COGNITO_SCOPES")  # last required source
            selected = mappings(environment)
            api = FakeAPI()
            with self.assertRaises(module.ReconciliationError):
                module.reconcile(
                    selected,
                    store_for(selected, data),
                    self.github(api),
                    lambda _: None,
                    mode="enforce",
                    environment=environment,
                    selection="all",
                )
            self.assertTrue(all(r.method == "GET" for r in api.calls))

    def test_preflight_does_not_require_future_api_or_browser_outputs(self):
        for environment in ("development", "production"):
            selected = module.select_mappings(mappings(environment), "preflight")
            data = {
                name: value
                for name, value in values(environment).items()
                if name in module.PREFLIGHT_FIELDS
            }
            result = module.reconcile(
                selected,
                store_for(selected, data),
                self.github(FakeAPI()),
                lambda _: None,
                mode="enforce",
                environment=environment,
                selection="preflight",
            )
            self.assertEqual(set(result), module.PREFLIGHT_FIELDS)
            self.assertEqual(
                module.configuration_outputs(result, "preflight")["frontend_config"], {}
            )

    def test_foundation_audit_warns_for_expected_missing_runtime_and_api(self):
        selected = mappings("development")
        data = values("development")
        for name in (
            "PAWLOCAL_RUNTIME_ROLE_ARN",
            "VITE_API_BASE_URL",
            "PAWLOCAL_API_HEALTH_URL",
        ):
            data.pop(name)
        reports = []
        module.reconcile(
            selected, store_for(selected, data), self.github(FakeAPI()), reports.append
        )
        self.assertTrue(any("missing-source" in line for line in reports))
        self.assertIn("does not establish release readiness", reports[-1])

    def test_optional_missing_warns_but_incomplete_public_snapshot_blocks_before_write(
        self,
    ):
        selected = mappings("development")
        missing = next(m for m in selected if m.env_name == "VITE_COGNITO_SCOPES")
        selected = [
            module.Mapping(
                m.store_key,
                m.github_environment,
                m.env_name,
                m.secret,
                () if m is missing else m.validations,
            )
            for m in selected
        ]
        data = values("development")
        data.pop("VITE_COGNITO_SCOPES")
        api = FakeAPI()
        with self.assertRaises(module.ReconciliationError):
            module.reconcile(
                selected,
                store_for(selected, data),
                self.github(api),
                lambda _: None,
                mode="enforce",
                selection="all",
            )
        self.assertTrue(all(r.method == "GET" for r in api.calls))
        optional = module.Mapping(
            "/pawlocal/development/config/other/optional",
            "development",
            "OPTIONAL",
            False,
            (),
        )
        module.reconcile(
            [optional],
            store_for([], {}),
            self.github(FakeAPI()),
            lambda _: None,
            mode="enforce",
        )

    def test_invalid_account_environment_and_public_formats_fail_before_writes(self):
        replacements = {
            "PAWLOCAL_RUNTIME_ROLE_ARN": "arn:aws:iam::999999999999:role/pawlocal-development-dsql-runtime",
            "VITE_API_BASE_URL": "https://api.example.test/api/v1",
            "VITE_COGNITO_DOMAIN": "http://pawlocal-development-example.auth.ap-southeast-2.amazoncognito.com",
            "VITE_COGNITO_REDIRECT_URI": "https://pawlocal-dev.other.test/auth/callback",
        }
        for name, bad in replacements.items():
            data = values("development")
            data[name] = bad
            selected = mappings("development")
            api = FakeAPI()
            with self.subTest(name=name), self.assertRaises(module.ReconciliationError):
                module.reconcile(
                    selected,
                    store_for(selected, data),
                    self.github(api),
                    lambda _: None,
                    mode="enforce",
                    selection="all",
                )
            self.assertTrue(all(r.method == "GET" for r in api.calls))

    def test_snapshot_rejects_secret_unknown_and_injected_build_settings(self):
        self.assertEqual(build.FIELDS, module.FRONTEND_FIELDS)
        public = {
            name: value
            for name, value in values("development").items()
            if name in module.FRONTEND_FIELDS
        }
        self.assertEqual(build.load_public(json.dumps(public)), public)
        for bad in (
            dict(public, PAWLOCAL_CONFIG_GITHUB_TOKEN=SENTINEL),
            dict(
                public,
                VITE_API_BASE_URL="https://api-dev.example.test/api/v1\nINJECTED=yes",
            ),
        ):
            with self.assertRaises(ValueError):
                build.load_public(json.dumps(bad))
        selected = mappings("development") + [
            module.Mapping(
                "/pawlocal/development/secrets/auth/test",
                "development",
                "PRIVATE_TEST",
                True,
                (),
            )
        ]
        data = dict(values("development"), PRIVATE_TEST=SENTINEL)
        result = module.reconcile(
            selected,
            store_for(selected, data),
            self.github(FakeAPI()),
            lambda _: None,
            mode="enforce",
            selection="all",
        )
        self.assertNotIn(
            SENTINEL, json.dumps(module.configuration_outputs(result, "all"))
        )

    def test_confirmed_destroy_then_reapply_fixture_is_exact_and_recovers(self):
        for environment in ("development", "production"):
            selected, data, api = (
                mappings(environment),
                values(environment),
                CleanupAPI(),
            )
            github = self.github(api)
            module.reconcile(
                selected,
                store_for(selected, data),
                github,
                lambda _: None,
                mode="enforce",
                environment=environment,
                selection="all",
            )
            api.variables[("development-seed", "PAWLOCAL_DSQL_ENDPOINT")] = "untouched"
            with self.assertRaises(module.ReconciliationError):
                cleanup.cleanup(
                    selected,
                    github,
                    environment,
                    "destroy-cleanup",
                    f"DESTROY {environment}",
                    ROOT,
                    lambda _: None,
                )
            before = copy.deepcopy(api.variables)
            cleanup.cleanup(
                selected,
                github,
                environment,
                "destroy-cleanup",
                f"DESTROY {environment}",
                ROOT,
                lambda _: None,
                destroy_confirmed=True,
            )
            self.assertNotIn((environment, "VITE_COGNITO_CLIENT_ID"), api.variables)
            self.assertNotIn(
                (f"{environment}-plan", "PAWLOCAL_RUNTIME_ROLE_ARN"), api.variables
            )
            self.assertIn(
                (f"{environment}-apply", "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN"),
                api.variables,
            )
            self.assertEqual(
                api.variables[("development-seed", "PAWLOCAL_DSQL_ENDPOINT")],
                "untouched",
            )
            module.reconcile(
                selected,
                store_for(selected, data),
                github,
                lambda _: None,
                mode="enforce",
                environment=environment,
                selection="all",
            )
            self.assertEqual(api.variables, before)

    def test_legacy_cleanup_proves_consumers_and_changes_only_selected_release(self):
        api = CleanupAPI()
        api.variables[("development", "PAWLOCAL_DEPLOY_ADAPTER_PATH")] = (
            "ops/deployment-adapters/lightsail-dsql.sh"
        )
        for target in (
            "development",
            "production",
            "development-plan",
            "development-seed",
        ):
            api.variables[(target, "PAWLOCAL_TF_STATE_BUCKET")] = (
                "retained-except-selected-release"
            )
            api.secrets[(target, "PAWLOCAL_DSQL_SECRET_ACCESS_KEY")] = SENTINEL
        cleanup.cleanup(
            mappings("development"),
            self.github(api),
            "development",
            "legacy-cleanup",
            "CLEAN legacy development",
            ROOT,
            lambda _: None,
        )
        self.assertNotIn(("development", "PAWLOCAL_TF_STATE_BUCKET"), api.variables)
        self.assertNotIn(
            ("development", "PAWLOCAL_DSQL_SECRET_ACCESS_KEY"), api.secrets
        )
        self.assertIn(("development-plan", "PAWLOCAL_TF_STATE_BUCKET"), api.variables)
        self.assertIn(("production", "PAWLOCAL_DSQL_SECRET_ACCESS_KEY"), api.secrets)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                ".github/workflows/fullstack-release.yml",
                ".github/workflows/deploy-production.yml",
                "ops/run-deployment-adapter.sh",
                "ops/deployment-adapters/lightsail-dsql.sh",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("PAWLOCAL_DEPLOY_HOST")
            with self.assertRaises(module.ReconciliationError):
                cleanup.prove_legacy_unused(root, self.github(api), "development")

    def test_destroy_cleanup_retries_only_after_verified_present_empty_state(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/terraform-environment-destroy.yml").read_text()
        )
        cleanup_job = workflow["jobs"]["cleanup-generated-targets"]
        self.assertEqual(cleanup_job["needs"], ["prepare-plan", "destroy-apply"])
        self.assertEqual(
            cleanup_job["if"],
            "${{ !cancelled() && needs.prepare-plan.result == 'success' && (needs.destroy-apply.result == 'success' || needs.prepare-plan.outputs.already_empty == 'true') }}",
        )
        preparation = workflow["jobs"]["prepare-plan"]
        proof = next(
            step for step in preparation["steps"] if step.get("id") == "state-status"
        )
        self.assertIn('terraform -chdir="$TF_ROOT" state pull', proof["run"])
        self.assertIn("state-status", proof["run"])
        self.assertIn("if [[ \"$status\" == 'empty' ]]", proof["run"])
        self.assertEqual(
            preparation["outputs"]["already_empty"],
            "${{ steps.state-status.outputs.already_empty }}",
        )
        self.assertEqual(
            cleanup_job["with"]["confirmation"], "${{ inputs.confirmation }}"
        )
        self.assertIs(cleanup_job["with"]["destroy_confirmed"], True)
        # Missing/malformed state fails preparation; nonempty failed/cancelled
        # destroy cannot authorize cleanup. Successful empty-state retry can.
        for preparation_result, destroy_result, empty, cancelled, expected in (
            ("success", "skipped", True, False, True),
            ("success", "success", False, False, True),
            ("failure", "skipped", False, False, False),
            ("success", "failure", False, False, False),
            ("success", "cancelled", False, True, False),
            ("success", "skipped", True, True, False),
        ):
            self.assertEqual(
                not cancelled
                and preparation_result == "success"
                and (destroy_result == "success" or empty),
                expected,
            )

    def test_nested_lifecycle_lock_contract(self):
        def load(name):
            return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())

        terraform = load("terraform-environment.yml")
        reconcile = load("reconcile-environment.yml")
        destroy = load("terraform-environment-destroy.yml")
        group = terraform["concurrency"]["group"]
        parents = json.loads(re.search(r"fromJSON\('([^']+)'\)", group)[1])
        self.assertEqual(
            parents,
            [
                "Full-stack release to development",
                "Promote verified release to production",
            ],
        )
        self.assertEqual(
            group,
            "${{ contains(fromJSON('"
            + json.dumps(parents, separators=(",", ":"))
            + "'), github.workflow) && format('pawlocal-terraform-{0}', inputs.environment)"
            + " || format('pawlocal-lifecycle-{0}', inputs.environment) }}",
        )
        self.assertEqual(
            reconcile["concurrency"]["group"],
            "${{ inputs.caller_holds_lifecycle_lock && format('pawlocal-reconcile-call-{0}-{1}', github.run_id, inputs.selection || 'all') || format('pawlocal-lifecycle-{0}', inputs.environment) }}",
        )
        contract = reconcile[True]
        self.assertEqual(
            contract["workflow_call"]["inputs"]["caller_holds_lifecycle_lock"][
                "default"
            ],
            False,
        )
        self.assertNotIn(
            "caller_holds_lifecycle_lock", contract["workflow_dispatch"]["inputs"]
        )
        for name in ("reconcile-preflight", "reconcile-after-apply"):
            self.assertIs(
                terraform["jobs"][name]["with"]["caller_holds_lifecycle_lock"], True
            )
        self.assertIs(
            destroy["jobs"]["cleanup-generated-targets"]["with"][
                "caller_holds_lifecycle_lock"
            ],
            True,
        )
        self.assertNotIn(
            "caller_holds_lifecycle_lock",
            load("ci.yml")["jobs"]["reconciliation-smoke"]["with"],
        )
        # Pin the expression above, then exercise its caller cases. GitHub keeps
        # the original caller name in nested calls, including generic callers.
        for caller in (
            "Terraform environment plan and apply",
            *parents,
            "Other automation",
        ):
            with self.subTest(caller=caller):
                tf_lock = (
                    "pawlocal-terraform-development"
                    if caller in parents
                    else "pawlocal-lifecycle-development"
                )
                child_lock = "pawlocal-reconcile-call-123-all"
                if caller in parents:
                    parent = load(
                        "fullstack-release.yml"
                        if caller == parents[0]
                        else "deploy-production.yml"
                    )
                    self.assertIn("pawlocal-lifecycle-", parent["concurrency"]["group"])
                    self.assertNotEqual(tf_lock, "pawlocal-lifecycle-development")
                else:
                    self.assertEqual(tf_lock, "pawlocal-lifecycle-development")
                self.assertNotEqual(tf_lock, child_lock)
        for workflow in (terraform, reconcile, destroy):
            self.assertIs(workflow["concurrency"]["cancel-in-progress"], False)

    def test_collision_inventory_rejects_existing_unknown_denied_and_adoption(self):
        key = "/pawlocal/development/config/auth/client-id"
        create = {
            "type": "aws_ssm_parameter",
            "change": {"actions": ["create"], "before": None, "after": {"name": key}},
        }
        plan = {"resource_changes": [create]}
        collision.check(plan, FakeSSM(), {key})
        for client, allowed in (
            (FakeSSM({key: {"Type": "String", "Value": SENTINEL}}), {key}),
            (FakeSSM(), set()),
            (FakeSSM({key: RuntimeError(SENTINEL)}), {key}),
        ):
            with self.assertRaises(module.ReconciliationError):
                collision.check(plan, client, allowed)
        create["change"]["importing"] = {"id": key}
        with self.assertRaises(module.ReconciliationError):
            collision.check(plan, FakeSSM(), {key})
        create["change"]["actions"] = ["no-op"]
        with self.assertRaises(module.ReconciliationError):
            collision.check(plan, FakeSSM(), {key})

    def test_pipeline_dependency_and_lock_order_prevents_failure_publication(self):
        load = lambda name: yaml.safe_load(
            (ROOT / ".github/workflows" / name).read_text()
        )
        tf = load("terraform-environment.yml")
        self.assertIn("reconcile-preflight", tf["jobs"]["plan"]["needs"])
        self.assertIn(
            "needs.reconcile-preflight.result == 'success'", tf["jobs"]["plan"]["if"]
        )
        self.assertIn("!cancelled()", tf["jobs"]["reconcile-after-apply"]["if"])
        self.assertIn(
            "needs.apply.result == 'success'", tf["jobs"]["reconcile-after-apply"]["if"]
        )
        self.assertIn(
            "'audit' || 'enforce'", tf["jobs"]["reconcile-after-apply"]["with"]["mode"]
        )
        for workflow, verify in (
            ("fullstack-release.yml", "verify-development"),
            ("deploy-production.yml", "verify-production"),
        ):
            source = (ROOT / ".github/workflows" / workflow).read_text()
            self.assertNotIn("vars.VITE_COGNITO_CLIENT_ID", source)
            self.assertIn("outputs.frontend_config", source)
            self.assertIn("terraform-", str(load(workflow)["jobs"][verify]["needs"]))
            terraform_call = next(
                job
                for job in load(workflow)["jobs"].values()
                if job.get("uses") == "./.github/workflows/terraform-environment.yml"
            )
            self.assertEqual(
                terraform_call["secrets"]["PAWLOCAL_CONFIG_GITHUB_TOKEN"],
                "${{ secrets.PAWLOCAL_CONFIG_GITHUB_TOKEN }}",
            )
        reconcile = load("reconcile-environment.yml")
        reader = next(
            step
            for step in reconcile["jobs"]["reconcile"]["steps"]
            if "configure-aws-credentials" in step.get("uses", "")
        )
        self.assertFalse(reader["with"]["mask-aws-account-id"])
        self.assertNotIn("CI manual full suite", reconcile["concurrency"]["group"])
        self.assertIn("pawlocal-lifecycle-", reconcile["concurrency"]["group"])
        self.assertNotEqual(
            reconcile["concurrency"]["group"],
            reconcile["jobs"]["reconcile"]["concurrency"]["group"],
        )
        destroy = load("terraform-environment-destroy.yml")
        self.assertEqual(
            destroy["concurrency"]["group"], "pawlocal-lifecycle-production"
        )
        self.assertIn(
            "needs.destroy-apply.result == 'success'",
            destroy["jobs"]["cleanup-generated-targets"]["if"],
        )


if __name__ == "__main__":
    unittest.main()
