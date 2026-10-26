"""Exercise detach scheduling and pinned AWS-provider plans without AWS calls."""
import os
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

FIXTURE = Path(__file__).parent / "fixtures/certificate-detach-ordering"
ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "infra/terraform/modules/pawlocal-environment"


@unittest.skipUnless(shutil.which("terraform"), "Terraform executable is required")
class CertificateDetachOrderingTests(unittest.TestCase):
    def test_pinned_provider_plans_the_actual_flag_without_certificate_destruction(self):
        """Mock only seed applies; migration plans use the actual pinned AWS provider.

        All identifiers and states are synthetic. Only the two affected resources
        are isolated from the application graph; their configuration is extracted
        verbatim, excluding external dependency barriers. No AWS reads or writes.
        """
        providers = MODULE / ".terraform/providers"
        if not providers.exists():
            self.skipTest("Initialize the environment module providers first")
        source = (MODULE / "main.tf").read_text(encoding="utf-8")
        blocks = []
        for kind in ("aws_lightsail_certificate", "aws_lightsail_container_service"):
            block = source.split(f'resource "{kind}" "api" {{', 1)[1].split("\n}\n", 1)[0]
            block = re.sub(r"^\s*depends_on\s*=.*$", "", block, flags=re.MULTILINE)
            blocks.append(f'resource "{kind}" "api" {{' + block + "\n}\n")
        prefix = '''terraform {
  required_version = "= 1.14.3"
  required_providers { aws = { source = "hashicorp/aws", version = "= 6.69.1" } }
}
variable "environment" { type = string }
variable "root_domain" { default = "example.test" }
variable "container_power" { default = "micro" }
variable "container_scale" { default = 1 }
variable "detach_lightsail_certificate" {
 type = bool
 default = false
}
locals {
  resource_names = { container_service = "pawlocal-${var.environment}-api" }
  legacy_certificate_domain = "${var.environment == "development" ? "api-dev" : "api"}.${var.root_domain}"
  common_tags = { project = "pawlocal", environment = var.environment }
}
'''
        tests = '''mock_provider "aws" { alias = "seed" }
provider "aws" {
 alias = "offline"
 region = "ap-southeast-2"
 access_key = "offline"
 secret_key = "offline"
 skip_credentials_validation = true
 skip_metadata_api_check = true
 skip_region_validation = true
 skip_requesting_account_id = true
 endpoints { lightsail = "http://127.0.0.1:1" }
}
'''
        expected = {}
        for environment in ("development", "production"):
            tags = {"project": "pawlocal", "environment": environment}
            domain = ("api-dev" if environment == "development" else "api") + ".example.test"
            for snapshot in ("original", "partial", "detached"):
                key = f"{environment}_{snapshot}"
                # Original and partially applied #346 states have identical
                # certificate/service bindings; only unrelated DNS differs.
                detached = snapshot == "detached"
                expected[f"plan_{key}"] = "no-op" if detached else "update"
                tests += f'''
run "seed_{key}" {{
 command = apply
 state_key = "{key}"
 module {{ source = "./subject" }}
 providers = {{ aws = aws.seed }}
 variables {{
  environment = "{environment}"
  detach_lightsail_certificate = {str(detached).lower()}
 }}
 override_resource {{
  target = aws_lightsail_certificate.api
  values = {{
   id = "pawlocal-{environment}-api-cert"
   region = "ap-southeast-2"
   arn = "arn:aws:lightsail:ap-southeast-2:111111111111:Certificate/fixture-{environment}"
   domain_name = "{domain}"
   subject_alternative_names = ["{domain}"]
   tags_all = {json.dumps(tags)}
  }}
 }}
 override_resource {{
  target = aws_lightsail_container_service.api
  values = {{
   id = "pawlocal-{environment}-api"
   region = "ap-southeast-2"
   arn = "arn:aws:lightsail:ap-southeast-2:111111111111:ContainerService/fixture-{environment}"
   tags_all = {json.dumps(tags)}
   private_registry_access = []
  }}
 }}
}}
run "plan_{key}" {{
 command = plan
 state_key = "{key}"
 module {{ source = "./subject" }}
 providers = {{ aws = aws.offline }}
 plan_options {{ refresh = false }}
 variables {{
  environment = "{environment}"
  detach_lightsail_certificate = true
 }}
}}
'''
            for detach in (False, True):
                key = f"fresh_{environment}_{str(detach).lower()}"
                expected[key] = "create"
                tests += f'''
run "{key}" {{
 command = plan
 state_key = "{key}"
 module {{ source = "./subject" }}
 providers = {{ aws = aws.offline }}
 plan_options {{ refresh = false }}
 variables {{
  environment = "{environment}"
  detach_lightsail_certificate = {str(detach).lower()}
 }}
}}
'''
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "subject").mkdir()
            (directory / "tests").mkdir()
            (directory / "main.tf").write_text(prefix.split('variable "environment"', 1)[0], encoding="utf-8")
            (directory / "subject/main.tf").write_text(prefix + "\n".join(blocks), encoding="utf-8")
            (directory / "tests/toggle.tftest.hcl").write_text(tests, encoding="utf-8")
            environment = {**os.environ, "AWS_EC2_METADATA_DISABLED": "true"}
            arguments = ["terraform", "init", "-backend=false", "-input=false"]
            # Reuse an installed pinned binary when available. A fresh CI module
            # may have a newer compatible AWS version, so download the exact
            # historical provider instead of silently testing that newer one.
            if (providers / "registry.terraform.io/hashicorp/aws/6.69.1").exists():
                arguments.append(f"-plugin-dir={providers}")
            init = subprocess.run(arguments, cwd=directory, env=environment, capture_output=True, text=True, timeout=180)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            result = subprocess.run(["terraform", "test", "-json", "-verbose"], cwd=directory, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plans = {}
            for line in result.stdout.splitlines():
                event = json.loads(line)
                if event.get("type") == "test_plan":
                    plans[event["@testrun"]] = event["test_plan"]
            self.assertEqual(set(plans), set(expected))
            for run, action in expected.items():
                changes = {r["address"]: r["change"] for r in plans[run]["resource_changes"]}
                certificate = changes["aws_lightsail_certificate.api"]
                service = changes["aws_lightsail_container_service.api"]
                self.assertEqual(certificate["actions"], ["create" if action == "create" else "no-op"], run)
                self.assertEqual(service["actions"], [action], run)
                self.assertNotIn("delete", certificate["actions"], run)
                self.assertNotIn("delete", service["actions"], run)
                if action != "create":
                    self.assertEqual(certificate["before"]["arn"], certificate["after"]["arn"], run)
                    self.assertEqual(service["before"]["arn"], service["after"]["arn"], run)
                    self.assertEqual(service["after"]["public_domain_names"], [], run)
                else:
                    self.assertTrue(certificate["after"]["domain_name"].endswith(".example.test"), run)
                    self.assertEqual(bool(service["after"]["public_domain_names"]), run.endswith("false"), run)

    def test_detach_before_destroy_requires_retaining_the_existing_certificate(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            shutil.copytree(FIXTURE, directory, dirs_exist_ok=True)
            trace = directory / "trace.log"
            environment = {**os.environ, "TF_LOG_CORE": "TRACE", "TF_LOG_PATH": str(trace)}
            for arguments in (("init", "-backend=false", "-input=false"), ("test", "-no-color")):
                result = subprocess.run(["terraform", *arguments], cwd=directory, env=environment, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            log = trace.read_text(encoding="utf-8")

            def applying(run):
                return log.split("TestFileRunner: starting apply for " + run, 1)[1].split("TestFileRunner: completed apply for " + run, 1)[0]

            direct = applying("unsafe_direct_removal")
            # Negative control reproduces the production failure's Terraform
            # behavior: the referenced certificate is destroyed before service
            # update. Attribute references alone do not establish safe teardown.
            certificate = direct.index('vertex "terraform_data.certificate (destroy)": starting visit')
            service = direct.index('vertex "terraform_data.service": starting visit (*terraform.NodeApplyableResourceInstance)')
            self.assertLess(certificate, service)
            detach = applying("retain_and_detach")
            self.assertIn("Starting apply for terraform_data.service", detach)
            self.assertNotIn('vertex "terraform_data.certificate (destroy)": starting visit', detach)
            cleanup = applying("delete_unused_certificate")
            self.assertIn('vertex "terraform_data.certificate (destroy)": starting visit', cleanup)
            self.assertNotIn("Starting apply for terraform_data.service", cleanup)


if __name__ == "__main__":
    unittest.main()
