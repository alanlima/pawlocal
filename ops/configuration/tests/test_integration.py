from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
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
    api = "pawlocal-dev.example.test" if environment == "development" else "pawlocal.example.test"
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
        "PAWLOCAL_API_HEALTH_URL": f"https://{api}/api/health",
        "PAWLOCAL_FRONTEND_BUCKET": f"pawlocal-{environment}-frontend-example",
        "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID": "E123EXAMPLE",
        "VITE_API_BASE_URL": f"https://{api}/api/v1",
        "VITE_COGNITO_DOMAIN": f"https://pawlocal-{environment}-example.auth.ap-southeast-2.amazoncognito.com",
        "VITE_COGNITO_CLIENT_ID": "exampleclient123",
        "VITE_COGNITO_REDIRECT_URI": f"https://{frontend}/auth/callback",
        "VITE_COGNITO_LOGOUT_URI": f"https://{frontend}/",
        "VITE_COGNITO_SCOPES": "openid email profile",
        "PAWLOCAL_TELEMETRY_ENABLED": "false",
        "VITE_TELEMETRY_ENABLED": "false",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.grafana.net/otlp",
        "PAWLOCAL_GRAFANA_OTLP_INSTANCE_ID": "12345",
        "VITE_FARO_COLLECTOR_URL": "https://faro.grafana.net/collect/public-key",
        "PAWLOCAL_GRAFANA_URL": "https://stack.grafana.net",
        "PAWLOCAL_GRAFANA_WEBHOOK_URL": "https://abc.lambda-url.ap-southeast-2.on.aws/",
    }


def selected_mappings(rows, selection):
    # Fixture-only consumer projection; the synchronizer always reads one YAML.
    if selection == "preflight":
        return [
            m
            for m in rows
            if m.env_name in module.PREFLIGHT_FIELDS
            and m.github_environment.endswith(("-plan", "-apply"))
        ]
    return rows


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

    def test_missing_source_skips_copy_but_build_consumer_rejects_incomplete_snapshot(
        self,
    ):
        for environment in ("development", "production"):
            data = values(environment)
            data.pop("VITE_COGNITO_SCOPES")
            selected = mappings(environment)
            api = FakeAPI()
            result = module.reconcile(
                selected,
                store_for(selected, data),
                self.github(api),
                lambda _: None,
                mode="enforce",
                environment=environment,
            )
            self.assertTrue(api.variables)
            with self.assertRaises(ValueError):
                build.load_public(
                    json.dumps(module.configuration_outputs(result)["frontend_config"])
                )

    def test_empty_same_run_snapshot_rejects_stale_environment_before_publisher_setup(
        self,
    ):
        for environment in ("development", "production"):
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "github-env"
                output.write_text("prior-step-marker\n", encoding="utf-8")
                with (
                    patch.dict(
                        os.environ,
                        {
                            **values(environment),
                            "RECONCILED_FRONTEND_CONFIG": "{}",
                            "GITHUB_ENV": str(output),
                        },
                    ),
                    self.assertRaisesRegex(
                        SystemExit, "Cannot load verified public build configuration"
                    ),
                ):
                    build.main()
                self.assertEqual(output.read_text(encoding="utf-8"), "prior-step-marker\n")
        for filename in ("fullstack-release.yml", "deploy-production.yml"):
            source = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
            self.assertLess(
                source.index("build-config.py"),
                source.index("role-to-assume: ${{ env.PAWLOCAL_DEPLOY_ROLE_ARN }}"),
            )

    def test_preflight_does_not_require_future_api_or_browser_outputs(self):
        for environment in ("development", "production"):
            selected = selected_mappings(mappings(environment), "preflight")
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
            )
            self.assertEqual(set(result), module.PREFLIGHT_FIELDS)
            self.assertEqual(
                module.configuration_outputs(result)["frontend_config"], {}
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

    def test_yaml_optional_missing_synchronizes_but_consumer_blocks_incomplete_snapshot(
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
        result = module.reconcile(
            selected,
            store_for(selected, data),
            self.github(api),
            lambda _: None,
            mode="enforce",
        )
        self.assertTrue(api.variables)
        snapshot = module.configuration_outputs(result)["frontend_config"]
        with self.assertRaises(ValueError):
            build.load_public(json.dumps(snapshot))
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
            "VITE_API_BASE_URL": "https://pawlocal.example.test/api/v1",
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
                )
            self.assertTrue(all(r.method == "GET" for r in api.calls))

    def test_snapshot_rejects_secret_unknown_and_injected_build_settings(self):
        self.assertEqual(build.FIELDS, module.FRONTEND_FIELDS)
        public = {
            name: value
            for name, value in values("development").items()
            if name in module.FRONTEND_FIELDS
        }
        public.update(PAWLOCAL_TELEMETRY_ENABLED="false", VITE_TELEMETRY_ENABLED="false")
        self.assertEqual(build.load_public(json.dumps(public)), public)
        for bad in (
            dict(public, PAWLOCAL_CONFIG_GITHUB_TOKEN=SENTINEL),
            dict(
                public,
                VITE_API_BASE_URL="https://pawlocal-dev.example.test/api/v1\nINJECTED=yes",
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
        )
        self.assertNotIn(SENTINEL, json.dumps(module.configuration_outputs(result)))

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
            (ROOT / ".github/workflows/terraform-environment-destroy.yml").read_text(encoding="utf-8")
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
            return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))

        terraform = load("terraform-environment.yml")
        reconcile = load("reconcile-environment.yml")
        destroy = load("terraform-environment-destroy.yml")
        group = terraform["concurrency"]["group"]
        parents = json.loads(re.search(r"fromJSON\('([^']+)'\)", group)[1])
        self.assertEqual(
            parents,
            [
                "Release · Publish and verify development",
                "Release · Promote verified release to production",
                "Release · Roll back production",
            ],
        )
        self.assertEqual(
            group,
            "${{ contains(fromJSON('"
            + json.dumps(parents, separators=(",", ":"), ensure_ascii=False)
            + "'), github.workflow) && format('pawlocal-terraform-{0}', inputs.environment)"
            + " || format('pawlocal-lifecycle-{0}', inputs.environment) }}",
        )
        self.assertEqual(
            reconcile["concurrency"]["group"],
            "${{ inputs.caller_holds_lifecycle_lock && format('pawlocal-reconcile-call-{0}', github.run_id) || format('pawlocal-lifecycle-{0}', inputs.environment) }}",
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
        self.assertEqual(
            destroy["jobs"]["cleanup-generated-targets"]["uses"],
            "./.github/workflows/cleanup-destroyed-configuration.yml",
        )
        self.assertNotIn("reconciliation-smoke", load("ci.yml")["jobs"])
        # Pin the expression above, then exercise its caller cases. GitHub keeps
        # the original caller name in nested calls, including generic callers.
        for caller in (
            "Infrastructure · Plan and apply environment",
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

    def test_collision_inventory_checks_any_key_and_rejects_existing_denied_and_adoption(
        self,
    ):
        key = "/pawlocal/development/config/auth/client-id"
        create = {
            "type": "aws_ssm_parameter",
            "change": {"actions": ["create"], "before": None, "after": {"name": key}},
        }
        plan = {"resource_changes": [create]}
        collision.check(plan, FakeSSM())
        for client in (
            FakeSSM({key: {"Type": "String", "Value": SENTINEL}}),
            FakeSSM({key: RuntimeError(SENTINEL)}),
        ):
            with self.assertRaises(module.ReconciliationError):
                collision.check(plan, client)
        with self.assertRaisesRegex(
            module.ReconciliationError,
            "ssm:GetParameter returned AccessDeniedException",
        ) as caught:
            detail = "Access denied by explicit deny in a permissions boundary"
            denied = RuntimeError(detail)
            denied.response = {"Error": {"Code": "AccessDeniedException"}}
            collision.check(
                plan,
                FakeSSM({key: denied}),
            )
        self.assertIn(detail, str(caught.exception))
        self.assertIn(key, str(caught.exception))
        for arbitrary_key in (
            "/unrelated/service/setting",
            "/pawlocal/development/config/oncall/webhook-url",
        ):
            create["change"]["after"]["name"] = arbitrary_key
            source = FakeSSM()
            collision.check(plan, source)
            self.assertEqual(
                source.calls, [{"Name": arbitrary_key, "WithDecryption": False}]
            )
        create["change"]["after"]["name"] = None
        with self.assertRaisesRegex(module.ReconciliationError, "name must be known"):
            collision.check(plan, FakeSSM())
        create["change"]["after"]["name"] = key
        create["change"]["importing"] = {"id": key}
        with self.assertRaises(module.ReconciliationError):
            collision.check(plan, FakeSSM())
        create["change"]["actions"] = ["no-op"]
        with self.assertRaises(module.ReconciliationError):
            collision.check(plan, FakeSSM())

    def test_warning_only_workflow_keeps_setup_failures_from_running_sync(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/reconcile-environment.yml").read_text(encoding="utf-8")
        )
        events = workflow.get("on", workflow.get(True))
        self.assertIs(
            events["workflow_call"]["inputs"]["fail_on_error"]["default"], False
        )
        self.assertIs(
            events["workflow_dispatch"]["inputs"]["fail_on_error"]["default"], True
        )
        steps = {
            step.get("id"): step for step in workflow["jobs"]["reconcile"]["steps"]
        }
        for current, previous in (
            ("entry", "checkout"),
            ("python", "entry"),
            ("dependencies", "python"),
            ("credentials", "dependencies"),
            ("sync", "credentials"),
        ):
            self.assertEqual(
                steps[current]["if"], f"steps.{previous}.outcome == 'success'"
            )
            self.assertEqual(
                steps[current]["continue-on-error"], "${{ !inputs.fail_on_error }}"
            )
        self.assertIn("--fail-on-error", steps["sync"]["run"])
        outputs = workflow["jobs"]["reconcile"]["outputs"]
        for expression in outputs.values():
            self.assertIn("steps.sync.outputs.reconciled == 'true'", expression)
        self.assertIn(
            "steps.sync.outputs.reconciled == 'true'", steps["consumer"]["if"]
        )
        terraform = yaml.safe_load(
            (ROOT / ".github/workflows/terraform-environment.yml").read_text(encoding="utf-8")
        )
        for job in ("reconcile-preflight", "reconcile-after-apply"):
            self.assertIs(terraform["jobs"][job]["with"]["fail_on_error"], False)
        for job in ("plan", "apply"):
            for expression in terraform["jobs"][job]["env"].values():
                if "fromJSON(needs.reconcile-preflight.outputs.configuration" in str(
                    expression
                ):
                    self.assertRegex(expression, r"\.[A-Z_]+ \|\| vars\.[A-Z_]+ ")
        validator = next(
            step["run"]
            for step in terraform["jobs"]["plan"]["steps"]
            if step["name"] == "Validate selection and required configuration"
        )
        self.assertIn("Missing required runtime configuration", validator)

    def test_collision_diagnostics_precede_lookup_and_exclude_values(self):
        key = "/pawlocal/development/config/observability/enabled"
        plan = {
            "resource_changes": [
                {
                    "type": "aws_ssm_parameter",
                    "change": {"actions": ["create"], "after": {"name": key}},
                }
            ]
        }
        lookup_error = "Could not connect to the endpoint URL: https://ssm.example.test"
        for stored in ({"Value": SENTINEL}, RuntimeError(lookup_error), None):
            client = FakeSSM({key: stored})
            lookup = client.get_parameter
            with patch("builtins.print") as log:

                def checked_lookup(lookup=lookup, **kwargs):
                    log.assert_called_once_with(
                        f"Checking Parameter Store key: {key!r}", flush=True
                    )
                    return lookup(**kwargs)

                client.get_parameter = checked_lookup
                if stored is None:
                    collision.check(plan, client)
                    self.assertIn("1 key(s) checked", log.call_args.args[0])
                else:
                    with self.assertRaises(module.ReconciliationError) as caught:
                        collision.check(plan, client)
                    self.assertIn(key, str(caught.exception))
                    self.assertNotIn(SENTINEL, str(caught.exception))
                    if isinstance(stored, Exception):
                        self.assertIn(lookup_error, str(caught.exception))
                self.assertNotIn(SENTINEL, str(log.call_args_list))

    def test_pipeline_dependency_and_lock_order_prevents_failure_publication(self):
        load = lambda name: yaml.safe_load(
            (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
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
            source = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
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
        self.assertNotIn("Quality · Run complete validation suite", reconcile["concurrency"]["group"])
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
