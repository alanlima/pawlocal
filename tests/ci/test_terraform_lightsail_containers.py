from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
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

    def test_dsql_cluster_policy_restores_lightsail_principal_and_db_user_condition(self) -> None:
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        cluster_policy = terraform.split('resource "aws_dsql_cluster_policy" "api_connect" {', 1)[1].split('\n}', 1)[0]
        runtime_policy = terraform.split('resource "aws_iam_role_policy" "dsql_runtime" {', 1)[1].split('\n}', 1)[0]

        self.assertIn('Action    = "dsql:DbConnectAdmin"', cluster_policy)
        self.assertIn('Principal = { AWS = aws_lightsail_container_service.api[each.key].principal_arn }', cluster_policy)
        self.assertIn('Condition = { StringEquals = { "dsql:DbUser" = each.value.database_role } }', cluster_policy)
        self.assertIn('Action   = "dsql:DbConnect"', runtime_policy)
        self.assertIn('Resource = aws_dsql_cluster.app[each.key].arn', runtime_policy)

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
        self.assertIn("get-container-services", deploy)
        self.assertIn("currentDeployment", deploy)
        self.assertIn("PAWLOCAL_RELEASE_IMAGE_DIGEST", (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8"))
        self.assertIn("running_image_digest", adapter)

    def test_deploy_adapter_cleans_frontend_temp_dir_after_publication(self) -> None:
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
            ):
                source_path = ROOT / relative_path
                target_path = test_repo / relative_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(source_path.read_bytes().replace(b"\r\n", b"\n"))
                if target_path.suffix == ".sh":
                    target_path.chmod(0o755)
            manifest = {
                "schema_version": 2,
                "commit": "a" * 40,
                "backend_image": f"ghcr.io/alanlima/pawlocal-api@sha256:{'b' * 64}",
                "backend_image_digest": f"sha256:{'b' * 64}",
                "migration_chains": {
                    "postgresql": {"runner": "alembic", "migration_id": "0007_normalize_place_facilities"},
                    "aurora_dsql": {"runner": "dsql_baseline", "migration_id": "dsql_0001_initial"},
                },
                "telemetry_enabled": False,
                "frontend": {
                    "environment": "development",
                    "artifact_digest": "sha256:" + "0" * 64,
                },
            }
            manifest_path = temp / "manifest.json"
            archive_path = temp / "frontend.tar.gz"
            source = temp / "dist"
            source.mkdir()
            (source / "index.html").write_text("<html></html>", encoding="utf-8")
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(source / "index.html", arcname="index.html")
            manifest["frontend"]["artifact_digest"] = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            fake_bin = temp / "bin"
            fake_bin.mkdir()
            aws_log = temp / "aws.log"
            aws = fake_bin / "aws"
            aws.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$AWS_CALL_LOG\"\n",
                encoding="utf-8",
            )
            aws.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                "PATH": str(fake_bin) + os.pathsep + environment.get("PATH", ""),
                "AWS_CALL_LOG": str(aws_log),
                "RUNNER_TEMP": directory,
                "PAWLOCAL_DEPLOY_ADAPTER_PATH": "ops/deployment-adapters/lightsail-dsql.sh",
                "PAWLOCAL_FRONTEND_BUCKET": "test-frontend-bucket",
                "PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID": "test-distribution",
            })
            result = subprocess.run(
                [bash, "ops/run-deployment-adapter.sh", "deploy", "--environment", "development",
                 "--manifest", str(manifest_path), "--frontend-archive", str(archive_path)],
                cwd=test_repo,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Published development frontend artifact", result.stdout)
            self.assertNotIn("app_dir: unbound variable", result.stderr)
            calls = aws_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 3)
            self.assertTrue(calls[0].startswith("s3 sync "))
            self.assertTrue(calls[1].startswith("s3 cp "))
            self.assertTrue(calls[2].startswith("cloudfront create-invalidation "))
            self.assertEqual(list(temp.glob("pawlocal-frontend.*")), [])

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

    def test_terraform_release_role_scopes_cloudfront_and_cognito_refresh_reads(self) -> None:
        text = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        frontend_publish = re.search(
            r'sid\s*=\s*"ListFrontendBucket"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(frontend_publish)
        self.assertIn('"s3:ListBucket"', frontend_publish.group(1))
        self.assertIn("aws_s3_bucket.frontend[each.key].arn", frontend_publish.group(1))
        self.assertNotIn('resources = ["*"]', frontend_publish.group(1))

        terraform_bucket_read = re.search(
            r'sid\s*=\s*"ListPawLocalFrontendBucketsForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(terraform_bucket_read)
        self.assertIn('"s3:ListBucket"', terraform_bucket_read.group(1))
        self.assertIn('aws_s3_bucket.frontend["development"].arn', terraform_bucket_read.group(1))
        self.assertIn("var.additional_frontend_bucket_arns", terraform_bucket_read.group(1))
        self.assertNotIn('resources = ["*"]', terraform_bucket_read.group(1))

        acceleration_read = re.search(
            r'sid\s*=\s*"ReadPawLocalFrontendBucketAccelerationForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(acceleration_read)
        self.assertIn('"s3:GetAccelerateConfiguration"', acceleration_read.group(1))
        self.assertIn('aws_s3_bucket.frontend["development"].arn', acceleration_read.group(1))
        self.assertIn("var.additional_frontend_bucket_arns", acceleration_read.group(1))
        self.assertNotIn('resources = ["*"]', acceleration_read.group(1))

        replication_read = re.search(
            r'dynamic\s+"statement"\s*\{(.*?ReadPawLocalFrontendBucketReplicationForTerraformRefresh.*?)\n  \}',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(replication_read)
        self.assertIn('for_each = each.key == "development" ? [true] : []', replication_read.group(1))
        self.assertIn('actions   = ["s3:GetReplicationConfiguration"]', replication_read.group(1))
        self.assertIn('aws_s3_bucket.frontend["development"].arn', replication_read.group(1))
        self.assertIn("var.additional_frontend_bucket_arns", replication_read.group(1))
        self.assertNotIn('resources = ["*"]', replication_read.group(1))
        root_module = (ROOT / "infra/terraform/main.tf").read_text(encoding="utf-8")
        self.assertIn("additional_frontend_bucket_arns = [aws_s3_bucket.site.arn]", root_module)

        cloudfront = re.search(
            r'sid\s*=\s*"DescribePawLocalSpaFunctionsForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        cognito = re.search(
            r'sid\s*=\s*"ReadPawLocalUserPoolMfaForTerraformRefresh"(.*?)(?=\n  statement|\n})',
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(cloudfront)
        self.assertIn('"cloudfront:DescribeFunction"', cloudfront.group(1))
        self.assertIn("function.arn", cloudfront.group(1))
        self.assertIn("pawlocal-production-spa-routing", cloudfront.group(1))
        self.assertNotIn('resources = ["*"]', cloudfront.group(1))
        self.assertIsNotNone(cognito)
        self.assertIn('"cognito-idp:GetUserPoolMfaConfig"', cognito.group(1))
        self.assertIn("user_pool.arn", cognito.group(1))
        self.assertNotIn('resources = ["*"]', cognito.group(1))

    def test_dsql_bootstrap_is_operator_run_and_release_role_stays_limited(self) -> None:
        terraform = (ROOT / "infra/terraform/fullstack/main.tf").read_text(encoding="utf-8")
        release = re.search(
            r'data "aws_iam_policy_document" "github_terraform_deploy" \{(.*?)(?=\nresource "aws_iam_role_policy")',
            terraform,
            re.DOTALL,
        )
        self.assertIsNotNone(release)
        self.assertNotIn("dsql:DbConnectAdmin", release.group(1))
        marker = re.search(
            r'resource "terraform_data" "app_dsql_role" \{(.*?)(?=\nresource|\Z)',
            terraform,
            re.DOTALL,
        )
        self.assertIsNotNone(marker)
        self.assertNotIn("provisioner", marker.group(1))
        deploy = (ROOT / "ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        self.assertNotIn("dsql_bootstrap_python", deploy)
        bootstrap = (ROOT / "ops/bootstrap-development-dsql-role.ps1").read_text(encoding="utf-8")
        self.assertIn("pawlocal.dsql_role_bootstrap", bootstrap)
        self.assertIn("dsql_app_iam_principal_arn", bootstrap)

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
