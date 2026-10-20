from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "ops/validate-lightsail-container-plan.py"
SPEC = importlib.util.spec_from_file_location("container_plan_validator", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class TerraformLightsailContainerTests(unittest.TestCase):
    image = "ghcr.io/alanlima/pawlocal-api@sha256:" + "a" * 64
    account_id = "097922957316"

    def test_development_dsql_connection_uses_identity_policy_not_cluster_grant(self) -> None:
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        cluster_policy = terraform.split('resource "aws_dsql_cluster_policy" "api_connect" {', 1)[1].split('\n}', 1)[0]
        identity = (ROOT / "infra/terraform/identity/main.tf").read_text(encoding="utf-8")
        identity_output = (ROOT / "infra/terraform/identity/outputs.tf").read_text(encoding="utf-8")

        self.assertIn('Action    = "dsql:DbConnectAdmin"', cluster_policy)
        self.assertIn('each.key == "production" ?', cluster_policy)
        self.assertNotIn('Sid       = "AllowDevelopmentDsqlRuntimeRole"', cluster_policy)
        self.assertIn('Principal = { AWS = var.dsql_runtime_role_arn }', cluster_policy)
        self.assertIn('Condition = { StringEquals = { "dsql:DbUser" = each.value.database_role } }', cluster_policy)
        self.assertIn('development_runtime  = "pawlocal-development-dsql-runtime"', identity)
        self.assertIn('development_dsql_runtime = data.aws_iam_role.app["development_runtime"].arn', identity_output)
        self.assertNotIn('resource "aws_iam_role"', identity)
        self.assertNotIn('resource "aws_iam_role_policy"', identity)
        self.assertIn('resource "aws_iam_role_policy_attachment" "app"', identity)

    def test_production_dsql_cluster_connection_grant_remains_explicit(self) -> None:
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        cluster_policy = terraform.split('resource "aws_dsql_cluster_policy" "api_connect" {', 1)[1].split('\n}', 1)[0]

        self.assertIn('each.key == "production" ? [', cluster_policy)
        self.assertIn('Sid       = "AllowLightsailServiceIdentity"', cluster_policy)
        self.assertIn('Action    = "dsql:DbConnect"', cluster_policy)
        self.assertIn(': []', cluster_policy)

    def test_seed_workflow_oidc_trust_is_limited_to_development_environment(self) -> None:
        identity = (ROOT / "infra/terraform/identity/main.tf").read_text(encoding="utf-8")
        seed_workflow = (ROOT / ".github/workflows/development-dsql-seed.yml").read_text(encoding="utf-8")
        self.assertIn('development_runtime  = "pawlocal-development-dsql-runtime"', identity)
        self.assertIn("environment: development-seed", seed_workflow)
        self.assertNotIn('resource "aws_iam_role"', identity)
        self.assertNotIn("assume_role_policy", identity)

    @staticmethod
    def plan(address: str, actions: list[str], image: str) -> dict:
        environment = "development" if '["development"]' in address else "production"
        env = {
            "PAWLOCAL_RELEASE_ENVIRONMENT": environment,
            "PAWLOCAL_RELEASE_IMAGE_DIGEST": image.rsplit("@", maxsplit=1)[-1],
        }
        if environment == "development":
            env["PAWLOCAL_DSQL_ASSUME_ROLE_ARN"] = (
                "arn:aws:iam::097922957316:role/pawlocal-development-dsql-runtime"
            )
        return {"resource_changes": [{"address": address, "change": {
            "actions": actions, "after": {"container": [{"container_name": "pawlocal-api", "image": image, "environment": env}]}
        }}]}

    def test_accepts_only_selected_environment_container_deployment(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        VALIDATOR.validate(self.plan(address, ["update"], self.image), "development", self.image, self.account_id)

    def test_accepts_selected_immutable_container_deployment_replacement(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        VALIDATOR.validate(self.plan(address, ["delete", "create"], self.image), "development", self.image, self.account_id)

    def test_rejects_unrelated_infrastructure_changes(self) -> None:
        plan = self.plan('module.fullstack.aws_lightsail_container_service.api["development"]', ["update"], self.image)
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            VALIDATOR.validate(plan, "development", self.image, self.account_id)

    def test_rejects_changes_to_both_environments(self) -> None:
        plan = self.plan('module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]', ["update"], self.image)
        plan["resource_changes"].append(self.plan('module.fullstack.aws_lightsail_container_service_deployment_version.api["production"]', ["update"], self.image)["resource_changes"][0])
        with self.assertRaisesRegex(ValueError, "outside the selected"):
            VALIDATOR.validate(plan, "development", self.image, self.account_id)

    def test_rejects_any_control_plane_change_from_release_role(self) -> None:
        container_address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["development"]'
        plan = self.plan(container_address, ["update"], self.image)
        for address in (
            'module.fullstack.aws_iam_role.dsql_runtime["development"]',
            'module.fullstack.aws_iam_role_policy.dsql_runtime["development"]',
            'module.fullstack.aws_dsql_cluster_policy.api_connect["development"]',
            'module.fullstack.aws_iam_role_policy.github_terraform_deploy["development"]',
            'module.fullstack.aws_iam_role.dsql_runtime["production"]',
            'module.fullstack.aws_iam_role_policy.github_terraform_deploy["production"]',
        ):
            with self.subTest(address=address):
                changed = copy.deepcopy(plan)
                changed["resource_changes"].append({
                    "address": address,
                    "change": {"actions": ["update"], "after": {"policy": '{"Statement":[{"Action":"*","Resource":"*"}]}'}}
                })
                with self.assertRaisesRegex(ValueError, "outside the selected"):
                    VALIDATOR.validate(changed, "development", self.image, self.account_id)
        retargeted = self.plan(container_address, ["update"], self.image)
        retargeted["resource_changes"][0]["change"]["after"]["container"][0]["environment"][
            "PAWLOCAL_DSQL_ASSUME_ROLE_ARN"
        ] = "arn:aws:iam::097922957316:role/pawlocal-production-dsql-runtime"
        with self.assertRaisesRegex(ValueError, "development DSQL runtime role"):
            VALIDATOR.validate(retargeted, "development", self.image, self.account_id)
    def test_rejects_wrong_image_and_destroy(self) -> None:
        address = 'module.fullstack.aws_lightsail_container_service_deployment_version.api["production"]'
        with self.assertRaisesRegex(ValueError, "image digest"):
            VALIDATOR.validate(self.plan(address, ["update"], "other"), "production", self.image, self.account_id)
        with self.assertRaisesRegex(ValueError, "create, update, or replacement"):
            VALIDATOR.validate(self.plan(address, ["delete"], self.image), "production", self.image, self.account_id)

    def test_release_workflows_do_not_use_ssh_or_manual_ingress(self) -> None:
        for filename in ("fullstack-release.yml", "deploy-production.yml", "rollback-development.yml"):
            workflow = (ROOT / ".github/workflows" / filename).read_text(encoding="utf-8")
            self.assertIn("terraform-lightsail-container-deploy.sh", workflow)
            self.assertNotIn("terraform-lightsail-ingress.sh", workflow)
            self.assertNotIn("PAWLOCAL_DEPLOY_SSH_PRIVATE_KEY", workflow)
            self.assertNotIn("PAWLOCAL_DSQL_ACCESS_KEY_ID", workflow)

    def test_container_release_records_running_image_digest(self) -> None:
        deploy = (ROOT / "ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        adapter = (ROOT / "ops/deployment-adapters/lightsail-dsql.sh").read_text(encoding="utf-8")
        self.assertIn('root="$script_dir/../infra/terraform/environments/$environment"', deploy)
        self.assertIn('"key=pawlocal/$environment/terraform.tfstate"', deploy)
        self.assertIn('verify-lightsail-container-deployment.py', deploy)
        self.assertIn("PAWLOCAL_RELEASE_IMAGE_DIGEST", (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8"))
        self.assertIn("running_image_digest", adapter)

    def test_frontend_publisher_uses_reviewed_data_plane_operations_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            archive_path = temp / "frontend.tar.gz"
            from io import BytesIO
            with tarfile.open(archive_path, "w:gz") as archive:
                content = b"<html>pawlocal</html>"
                item = tarfile.TarInfo("index.html")
                item.size = len(content)
                archive.addfile(item, BytesIO(content))
            fake_sdk = temp / "boto3.py"
            fake_sdk.write_text(
                '''import json, os
class Paginator:
    def paginate(self, **kwargs): return [{"Contents": [{"Key": "stale.js"}]}]
class Client:
    def __init__(self, service): self.service = service
    def get_paginator(self, name): return Paginator()
    def delete_objects(self, **kwargs): log("delete_objects", kwargs)
    def put_object(self, **kwargs): log("put_object", {**kwargs, "Body": "<body>"})
    def create_invalidation(self, **kwargs): log("create_invalidation", kwargs)
def log(operation, value):
    with open(os.environ["FAKE_AWS_LOG"], "a") as output: output.write(json.dumps([operation, value], default=str) + "\\n")
def client(service, **kwargs): return Client(service)
''',
                encoding="utf-8",
            )
            commit = "a" * 40
            digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
            environment = os.environ.copy()
            environment.update({"PYTHONPATH": str(temp), "FAKE_AWS_LOG": str(temp / "aws.jsonl")})
            result = subprocess.run(
                [sys.executable, str(ROOT / "ops/publish-frontend-artifact.py"), "--archive", str(archive_path),
                 "--bucket", "pawlocal-dev-test", "--distribution-id", "E123ABC", "--commit", commit, "--digest", digest],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Published verified frontend artifact", result.stdout)
            calls = [json.loads(line)[0] for line in (temp / "aws.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(calls, ["delete_objects", "put_object", "put_object", "create_invalidation"])
            self.assertTrue({"frontend.tar.gz", "boto3.py", "aws.jsonl"}.issubset({path.name for path in temp.iterdir()}))
            self.assertFalse(any(path.name.startswith("pawlocal-") for path in temp.iterdir()))

    def test_verify_adapter_reports_query_500_without_cleanup_error(self) -> None:
        if os.name == "nt":
            self.skipTest("Adapter subprocess paths are exercised by the Ubuntu CI runner")
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("Bash is required to exercise the deployment adapter")

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            test_repo = temp / "repo"
            for relative_path in (
                "ops/run-deployment-adapter.sh",
                "ops/deployment-adapters/lightsail-dsql.sh",
                "ops/validate-release-metadata.py",
                "ops/api_smoke_url.py",
            ):
                source_path = ROOT / relative_path
                target_path = test_repo / relative_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source_path.read_bytes().replace(b"\r\n", b"\n"))
                if target_path.suffix == ".sh":
                    target_path.chmod(0o755)

            digest = "sha256:" + "b" * 64
            manifest = {
                "schema_version": 2,
                "commit": "a" * 40,
                "backend_image": f"ghcr.io/alanlima/pawlocal-api@{digest}",
                "backend_image_digest": digest,
                "migration_chains": {
                    "postgresql": {"runner": "alembic", "migration_id": "0007_normalize_place_facilities"},
                    "aurora_dsql": {"runner": "dsql_baseline", "migration_id": "dsql_0001_initial"},
                },
                "telemetry_enabled": False,
                "frontend": {
                    "environment": "development",
                    "artifact_digest": "sha256:" + "c" * 64,
                },
            }
            manifest_path = temp / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            health_path = temp / "health.json"
            health_path.write_text(json.dumps({
                "status": "ok",
                "environment": "development",
                "image_digest": digest,
            }), encoding="utf-8")

            fake_bin = temp / "bin"
            fake_bin.mkdir()
            curl_log = temp / "curl.log"
            curl = fake_bin / "curl"
            curl.write_text(
                "#!/usr/bin/env bash\n"
                "set -Eeuo pipefail\n"
                "calls=0\n"
                "if [[ -f \"$CURL_CALL_LOG\" ]]; then calls=\"$(cat \"$CURL_CALL_LOG\")\"; fi\n"
                "calls=$((calls + 1))\n"
                "printf '%s' \"$calls\" > \"$CURL_CALL_LOG\"\n"
                "output=''\n"
                "while [[ $# -gt 0 ]]; do\n"
                "  if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi\n"
                "done\n"
                "if [[ $calls == 1 ]]; then cp \"$FAKE_HEALTH_RESPONSE\" \"$output\"; exit 0; fi\n"
                "printf '%s\\n' 'curl: (22) The requested URL returned error: 500' >&2\n"
                "exit 22\n",
                encoding="utf-8",
            )
            curl.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                "PATH": str(fake_bin) + os.pathsep + environment.get("PATH", ""),
                "CURL_CALL_LOG": str(curl_log),
                "FAKE_HEALTH_RESPONSE": str(health_path),
                "RUNNER_TEMP": directory,
                "PAWLOCAL_DEPLOY_ADAPTER_PATH": "ops/deployment-adapters/lightsail-dsql.sh",
                "PAWLOCAL_API_HEALTH_URL": "https://api.example.test/health",
                "PAWLOCAL_PUBLIC_BASE_URL": "https://app.example.test",
            })
            evidence_path = temp / "evidence.json"
            result = subprocess.run(
                [bash, "ops/run-deployment-adapter.sh", "verify", "--environment", "development",
                 "--manifest", str(manifest_path), "--evidence", str(evidence_path)],
                cwd=test_repo,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("curl: (22) The requested URL returned error: 500", result.stderr)
            self.assertNotIn("response: unbound variable", result.stderr)
            self.assertNotIn("health_response: unbound variable", result.stderr)
            self.assertEqual(curl_log.read_text(encoding="utf-8"), "2")
            self.assertEqual(list(temp.glob("pawlocal-health.*")), [])
            self.assertEqual(list(temp.glob("pawlocal-api-smoke.*")), [])
            self.assertFalse(evidence_path.exists())

    def test_development_rollback_requires_prior_verified_release(self) -> None:
        workflow = (ROOT / ".github/workflows/rollback-development.yml").read_text(encoding="utf-8")
        restore_step = workflow.split("      - name: Restore the selected frontend artifact\n", 1)[1].split("      - name:", 1)[0]
        verify_step = workflow.split("      - name: Verify restored development release\n", 1)[1].split("      - name:", 1)[0]
        adapter_variable = "PAWLOCAL_DEPLOY_ADAPTER_PATH: ${{ vars.PAWLOCAL_DEPLOY_ADAPTER_PATH }}"
        self.assertIn(adapter_variable, restore_step)
        self.assertIn(adapter_variable, verify_step)
        self.assertIn("No successful main-branch full-stack release", workflow)
        self.assertIn("no successful verified development deployment", workflow)
        self.assertIn("terraform-lightsail-container-deploy.sh development", workflow)
        self.assertIn("validate-release-metadata.py", workflow)

    def test_nullable_dsql_retention_validation_is_null_safe(self) -> None:
        for filename in ("infra/terraform/variables.tf", "infra/terraform/fullstack/variables.tf"):
            text = (ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(
                "var.dsql_auth_retention_days == null ? true : (var.dsql_auth_retention_days > 0 && floor(var.dsql_auth_retention_days) == var.dsql_auth_retention_days)",
                text,
            )

    def test_environment_terraform_owns_app_resources_and_identity_stage_only_attaches_fixed_policies(self) -> None:
        fullstack = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        identity = (ROOT / "infra/terraform/identity/main.tf").read_text(encoding="utf-8")
        for resource in ('resource "aws_iam_role"', 'resource "aws_iam_role_policy"'):
            self.assertNotIn(resource, fullstack)
            self.assertNotIn(resource, identity)
        self.assertIn('resource "aws_iam_role_policy_attachment" "app"', identity)
        self.assertIn('data "aws_iam_role" "app"', identity)
        self.assertIn('local.bootstrap.identity_managed_policy_arns', identity)
        self.assertIn('local.bootstrap.identity_app_role_arns[each.key]', identity)
        self.assertNotIn("assume_role_policy", identity)
        self.assertNotIn('resource "aws_iam_policy"', identity)

    def test_dsql_bootstrap_is_operator_run_and_release_role_stays_limited(self) -> None:
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        self.assertNotIn('resource "aws_iam_role"', terraform)
        self.assertNotIn('resource "aws_iam_role_policy"', terraform)
        marker = re.search(
            r'resource "terraform_data" "app_dsql_role" \{(.*?)(?=\nresource|\Z)',
            terraform,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        self.assertNotIn("provisioner", marker.group(1))
        deploy = (ROOT / "ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        self.assertNotIn("dsql_bootstrap_python", deploy)
        identity = (ROOT / "infra/terraform/identity/main.tf").read_text(encoding="utf-8")
        self.assertIn('development_runtime  = "pawlocal-development-dsql-runtime"', identity)
        self.assertIn('resource "aws_iam_role_policy_attachment" "app"', identity)

    def test_cloudfront_function_code_preserves_live_crlf_bytes(self) -> None:
        expected = "\r\n".join([
            "function handler(event) {",
            "  var request = event.request;",
            "  if (request.uri === '/' || request.uri.indexOf('.') !== -1) return request;",
            "  request.uri = '/index.html';",
            "  return request;",
            "}",
            "",
        ])
        resources = (
            ("infra/terraform/main.tf", "site_spa"),
            ("infra/terraform/fullstack/main.tf", "spa"),
        )
        for filename, name in resources:
            with self.subTest(resource=name, filename=filename):
                text = (ROOT / filename).read_text(encoding="utf-8")
                resource = re.search(
                    rf'resource\s+"aws_cloudfront_function"\s+"{name}"\s*\{{(.*?)(?=\nresource|\Z)',
                    text,
                    re.DOTALL,
                )
                self.assertIsNotNone(resource)
                code = re.search(r'code\s*=\s*join\("\\r\\n",\s*\[(.*?)\]\s*\)', resource.group(1), re.DOTALL)
                self.assertIsNotNone(code)
                encoded_lines = re.findall(r'^\s*("(?:\\.|[^"\\])*")\s*,?\s*$', code.group(1), re.MULTILINE)
                rendered = "\r\n".join(json.loads(line) for line in encoded_lines)
                self.assertEqual(rendered, expected)
                self.assertEqual(rendered.count("\r\n"), 6)


if __name__ == "__main__":
    unittest.main()
