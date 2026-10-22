from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import yaml
from nacl.public import PrivateKey, SealedBox

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "reconcile", ROOT / "ops/configuration/reconcile.py"
)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
SENTINEL = "do-not-disclose-test-secret"


def entry(**changes):
    result = {
        "store_key": "/pawlocal/{environment}/config/auth/client-id",
        "environment": ["development", "production"],
        "github_environment": "{environment}",
        "env_name": "VITE_COGNITO_CLIENT_ID",
    }
    result.update(changes)
    return result


class FakeSSM:
    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []

    def get_parameter(self, **kwargs):
        self.calls.append(kwargs)
        result = self.values.get(kwargs["Name"])
        if result is None:
            error = Exception(SENTINEL)
            error.response = {"Error": {"Code": "ParameterNotFound"}}
            raise error
        if isinstance(result, Exception):
            raise result
        return {"Parameter": result}


class Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps(self.value).encode() if self.value is not None else b""


class FakeAPI:
    def __init__(self):
        self.variables = {}
        self.calls = []
        self.private = PrivateKey.generate()
        self.secrets = {}
        self.fail_name = None
        self.mismatch = False

    def __call__(self, request, timeout):
        self.calls.append(request)
        self.assert_timeout = timeout
        path = request.full_url.split("/environments/", 1)[1]
        if "/" not in path:
            return Response({"name": path})
        payload = json.loads(request.data) if request.data else None
        target, kind, *tail = path.split("/")
        name = tail[0] if tail else (payload or {}).get("name")
        if name == self.fail_name:
            raise HTTPError(request.full_url, 403, SENTINEL, {}, None)
        key = (target, name)
        if kind == "secrets":
            if name == "public-key":
                return Response(
                    {
                        "key": base64.b64encode(
                            bytes(self.private.public_key)
                        ).decode(),
                        "key_id": "key-1",
                    }
                )
            self.secrets[key] = (
                SealedBox(self.private)
                .decrypt(base64.b64decode(payload["encrypted_value"]))
                .decode()
            )
            return Response(None)
        if request.method in ("POST", "PATCH"):
            self.variables[key] = payload["value"]
            return Response(None)
        if key not in self.variables:
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)
        return Response(
            {
                "name": name,
                "value": "bad-readback" if self.mismatch else self.variables[key],
            }
        )


class ReconcileTests(unittest.TestCase):
    def load(self, entries, environment="development"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.yaml"
            path.write_text(yaml.safe_dump({"mappings": entries}))
            return module.load_mappings(path, environment)

    def github(self, api):
        return module.GitHub("alanlima/pawlocal", SENTINEL, api)

    def test_environment_resolution_defaults_and_inventory_parity(self):
        for environment in ("development", "production"):
            mappings = module.load_mappings(
                ROOT / "ops/configuration/parameter-mapping.yaml", environment
            )
            self.assertEqual(len({m.store_key for m in mappings}), 18)
            self.assertEqual(len(mappings), 24 if environment == "development" else 30)
            self.assertTrue(
                all(
                    m.store_key.startswith(f"/pawlocal/{environment}/config/")
                    for m in mappings
                )
            )
            self.assertTrue(
                all(m.validations == ("required",) and not m.secret for m in mappings)
            )
        mapping = self.load([entry()])[0]
        self.assertFalse(mapping.secret)
        self.assertEqual(mapping.validations, ())

    def test_reject_invalid_mapping_selection_types_paths_targets(self):
        invalid = [
            entry(extra="forbidden"),
            entry(environment="development"),
            entry(environment=["shared"]),
            entry(environment=[{}]),
            entry(secret="false"),
            entry(validations=["unknown"]),
            entry(store_key="/pawlocal/production/config/auth/client-id"),
            entry(store_key="/pawlocal/{environment}/config/Auth/client-id"),
            entry(store_key="/pawlocal/{environment}/secrets/auth/client-id"),
            entry(store_key="/pawlocal/{other}/config/auth/client-id"),
            entry(github_environment="development-seed"),
            entry(github_environment="production"),
            entry(env_name="../bad"),
            entry(environment=["development", "development"]),
        ]
        for bad in invalid:
            with self.subTest(bad=bad), self.assertRaises(module.ReconciliationError):
                self.load([bad])
        with self.assertRaises(module.ReconciliationError):
            self.load([entry(), entry()])
        with self.assertRaises(module.ReconciliationError):
            self.load([entry()], "shared")

    def test_duplicate_yaml_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mapping.yaml"
            path.write_text("mappings: []\nmappings: []\n")
            with self.assertRaises(module.ReconciliationError):
                module.load_mappings(path, "development")

    def test_variable_create_update_noop_and_readback(self):
        api = FakeAPI()
        mapping = self.load([entry()])[0]
        github = self.github(api)
        self.assertEqual(github.variable(mapping, "one"), "created")
        self.assertEqual(github.variable(mapping, "two"), "updated")
        before = len(api.calls)
        self.assertEqual(github.variable(mapping, "two"), "unchanged")
        self.assertEqual([r.method for r in api.calls[before:]], ["GET", "GET"])
        api.mismatch = True
        with self.assertRaises(module.ReconciliationError):
            github.variable(mapping, "three")

    def test_missing_sources_warn_without_readiness_or_deletion(self):
        api = FakeAPI()
        reports = []
        module.reconcile(
            self.load([entry(validations=["required"])]),
            module.ParameterStore(FakeSSM()),
            self.github(api),
            reports.append,
        )
        self.assertIn("WARNING missing-source", reports[0])
        self.assertIn("does not establish release readiness", reports[-1])
        self.assertTrue(
            all(r.method == "GET" and "/variables" not in r.full_url for r in api.calls)
        )

    def test_malformed_variable_response_reports_partial_failure_without_payload(self):
        mapping = self.load([entry()])[0]
        store = module.ParameterStore(
            FakeSSM({mapping.store_key: {"Type": "String", "Value": SENTINEL}})
        )
        for malformed in (
            [SENTINEL],
            {"name": mapping.env_name},
            {"name": "WRONG_NAME", "value": SENTINEL},
        ):

            def transport(request, timeout, malformed=malformed):
                if "/variables/" in request.full_url:
                    return Response(malformed)
                return Response({"name": "development"})

            reports = []
            with self.assertRaises(module.ReconciliationError) as failure:
                module.reconcile(
                    [mapping], store, self.github(transport), reports.append
                )
            self.assertIn("FAILED development/VITE_COGNITO_CLIENT_ID", reports[-1])
            self.assertNotIn(SENTINEL, "\n".join(reports) + str(failure.exception))

    def test_parameter_type_and_access_errors_fail(self):
        mapping = self.load([entry()])[0]
        for value in (
            {"Type": "SecureString", "Value": SENTINEL},
            {"Type": "String", "Value": ""},
            Exception(SENTINEL),
        ):
            with (
                self.subTest(value=value),
                self.assertRaises(module.ReconciliationError) as failure,
            ):
                module.ParameterStore(FakeSSM({mapping.store_key: value})).read(mapping)
            self.assertNotIn(SENTINEL, str(failure.exception))

    def test_secret_encrypted_write_only_and_non_disclosure(self):
        mapping = self.load(
            [
                entry(
                    store_key="/pawlocal/{environment}/secrets/auth/credential",
                    secret=True,
                )
            ]
        )[0]
        api = FakeAPI()
        ssm = FakeSSM({mapping.store_key: {"Type": "SecureString", "Value": SENTINEL}})
        reports = []
        module.reconcile(
            [mapping], module.ParameterStore(ssm), self.github(api), reports.append
        )
        self.assertEqual(
            ssm.calls, [{"Name": mapping.store_key, "WithDecryption": True}]
        )
        self.assertEqual(api.secrets[("development", mapping.env_name)], SENTINEL)
        self.assertEqual([r.method for r in api.calls], ["GET", "GET", "PUT"])
        self.assertNotIn(SENTINEL, "\n".join(reports))
        self.assertNotIn(SENTINEL, api.calls[-1].data.decode())

    def test_partial_failure_reports_names_and_idempotent_rerun(self):
        mappings = self.load(
            [
                entry(),
                entry(
                    store_key="/pawlocal/{environment}/config/auth/domain",
                    env_name="VITE_COGNITO_DOMAIN",
                ),
            ]
        )
        store = module.ParameterStore(
            FakeSSM(
                {m.store_key: {"Type": "String", "Value": SENTINEL} for m in mappings}
            )
        )
        api = FakeAPI()
        api.fail_name = "VITE_COGNITO_DOMAIN"
        reports = []
        with self.assertRaises(module.ReconciliationError):
            module.reconcile(mappings, store, self.github(api), reports.append)
        self.assertIn("completed-targets=1", reports[-1])
        api.fail_name = None
        module.reconcile(mappings, store, self.github(api), reports.append)
        self.assertTrue(any(r.startswith("unchanged ") for r in reports))
        self.assertNotIn(SENTINEL, "\n".join(reports))

    def test_authentication_and_api_transport_errors_are_value_free(self):
        for repository, token in (("other/repo", SENTINEL), ("alanlima/pawlocal", "")):
            with self.assertRaises(module.ReconciliationError):
                module.GitHub(repository, token)
        for code in (401, 403, 429, 500):

            def denied(request, timeout, code=code):
                raise HTTPError(request.full_url, code, SENTINEL, {}, None)

            with self.assertRaises(module.ReconciliationError) as failure:
                self.github(denied).request(
                    "GET", "environments/development/variables/TEST", missing=True
                )
            self.assertNotIn(SENTINEL, str(failure.exception))

        def disconnected(request, timeout):
            raise URLError(SENTINEL)

        with self.assertRaises(module.ReconciliationError):
            self.github(disconnected).request("GET", "test")

    def test_recovery_targets_only_accept_exact_existing_sources(self):
        for suffix, name in (
            ("iam/terraform-apply-role-arn", "PAWLOCAL_TERRAFORM_APPLY_ROLE_ARN"),
            ("aws/account-id", "PAWLOCAL_AWS_ACCOUNT_ID"),
            ("terraform/plan-bucket", "PAWLOCAL_TERRAFORM_PLAN_BUCKET"),
        ):
            self.assertEqual(
                len(
                    self.load(
                        [
                            entry(
                                environment=["production"],
                                store_key=f"/pawlocal/production/config/{suffix}",
                                github_environment="production-destroy",
                                env_name=name,
                            )
                        ],
                        "production",
                    )
                ),
                1,
            )
        with self.assertRaises(module.ReconciliationError):
            self.load(
                [
                    entry(
                        environment=["production"],
                        github_environment="production-destroy",
                    )
                ],
                "production",
            )

    def test_absent_target_fails_before_source_read_or_mutation(self):
        ssm = FakeSSM()

        def absent(request, timeout):
            raise HTTPError(request.full_url, 404, "Not Found", {}, None)

        with self.assertRaises(module.ReconciliationError):
            module.reconcile(
                self.load([entry()]),
                module.ParameterStore(ssm),
                self.github(absent),
                lambda _: None,
            )
        self.assertEqual(ssm.calls, [])

    def test_manifest_iam_exact_source_parity(self):
        import re

        policy = (
            ROOT / "infra/terraform/iam-bootstrap/configuration_reader.tf"
        ).read_text()
        suffixes = set(
            re.findall(r'"((?:iam|aws|terraform|frontend|api|auth)/[a-z-]+)"', policy)
        )
        mappings = module.load_mappings(
            ROOT / "ops/configuration/parameter-mapping.yaml", "production"
        )
        self.assertEqual(
            suffixes,
            {
                m.store_key.removeprefix("/pawlocal/production/config/")
                for m in mappings
            },
        )

    def test_main_suppresses_unexpected_exception_and_has_no_enforce(self):
        captured = io.StringIO()
        with (
            patch.dict(
                "os.environ",
                {
                    "GITHUB_REPOSITORY": "alanlima/pawlocal",
                    "PAWLOCAL_CONFIG_GITHUB_TOKEN": SENTINEL,
                },
            ),
            patch.object(module, "reconcile", side_effect=RuntimeError(SENTINEL)),
            contextlib.redirect_stderr(captured),
        ):
            self.assertEqual(module.main(["--environment", "development"]), 1)
        self.assertNotIn(SENTINEL, captured.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            module.main(["--environment", "development", "--mode", "enforce"])

    def test_workflow_protection_serialization_and_feature_harness(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/reconcile-environment.yml").read_text()
        )
        job = workflow["jobs"]["reconcile"]
        self.assertEqual(
            job["environment"], "${{ format('{0}-apply', inputs.environment) }}"
        )
        self.assertEqual(
            job["concurrency"],
            {
                "group": "pawlocal-configuration-${{ inputs.environment }}",
                "cancel-in-progress": False,
            },
        )
        self.assertNotIn("concurrency", workflow)
        self.assertNotIn("PAWLOCAL_CONFIG_GITHUB_TOKEN", job["env"])
        harness = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertNotIn("concurrency", harness)
        self.assertEqual(
            harness["jobs"]["reconciliation-smoke"]["with"]["environment"],
            "development",
        )
        self.assertFalse(
            any("upload-artifact" in s.get("uses", "") for s in job["steps"])
        )


if __name__ == "__main__":
    unittest.main()
