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
    def test_pinned_provider_final_source_deletes_only_the_unused_certificate(self):
        """Mock seed applies, then plan final source with real AWS 6.69.1 offline.

        Attached original/partial projections remain negative readiness controls:
        their service needs an update, so cleanup must wait for actual detachment.
        These isolated plans do not establish live usage or full-module ordering.
        """
        providers = MODULE / ".terraform/providers"
        if not providers.exists():
            self.skipTest("Initialize the environment module providers first")
        source = (MODULE / "main.tf").read_text(encoding="utf-8")
        self.assertNotIn('resource "aws_lightsail_certificate"', source)
        self.assertNotIn('resource "aws_route53_record" "api_certificate_validation"', source)
        block = source.split('resource "aws_lightsail_container_service" "api" {', 1)[1].split("\n}\n", 1)[0]
        block = re.sub(r"^\s*depends_on\s*=.*$", "", block, flags=re.MULTILINE)
        service = 'resource "aws_lightsail_container_service" "api" {' + block + "\n}\n"
        prefix = '''terraform {
 required_version = "= 1.14.3"
 required_providers { aws = { source = "hashicorp/aws", version = "= 6.69.1" } }
}
variable "environment" { type = string }
variable "container_power" { default = "micro" }
variable "container_scale" { default = 1 }
locals {
 resource_names = { container_service = "pawlocal-${var.environment}-api" }
 common_tags = { project = "pawlocal", environment = var.environment }
}
'''
        seed = prefix + '''variable "detached" { default = false }
resource "aws_lightsail_certificate" "api" {
 name = "pawlocal-${var.environment}-api-cert"
 domain_name = "${var.environment == "development" ? "api-dev" : "api"}.example.test"
 tags = local.common_tags
}
''' + service
        seed = seed.replace("  tags        = local.common_tags", '''  tags        = local.common_tags
 dynamic "public_domain_names" {
  for_each = var.detached ? [] : [true]
  content {
   certificate {
   certificate_name = aws_lightsail_certificate.api.name
   domain_names = [aws_lightsail_certificate.api.domain_name]
   }
  }
 }''')
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
                expected[f"cleanup_{key}"] = "no-op" if snapshot == "detached" else "update"
                tests += f'''
run "seed_{key}" {{
 command = apply
 state_key = "{key}"
 module {{ source = "./seed" }}
 providers = {{ aws = aws.seed }}
 variables {{
 environment = "{environment}"
 detached = {str(snapshot == "detached").lower()}
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
run "cleanup_{key}" {{
 command = plan
 state_key = "{key}"
 module {{ source = "./final" }}
 providers = {{ aws = aws.offline }}
 plan_options {{ refresh = false }}
 variables {{ environment = "{environment}" }}
}}
'''
            key = f"fresh_{environment}"
            expected[key] = "create"
            tests += f'''
run "{key}" {{
 command = plan
 state_key = "{key}"
 module {{ source = "./final" }}
 providers = {{ aws = aws.offline }}
 plan_options {{ refresh = false }}
 variables {{ environment = "{environment}" }}
}}
'''
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("seed", "final", "tests"):
                (directory / name).mkdir()
            (directory / "main.tf").write_text(prefix.split('variable "environment"', 1)[0], encoding="utf-8")
            (directory / "seed/main.tf").write_text(seed, encoding="utf-8")
            (directory / "final/main.tf").write_text(prefix + service, encoding="utf-8")
            (directory / "tests/cleanup.tftest.hcl").write_text(tests, encoding="utf-8")
            env = {**os.environ, "AWS_EC2_METADATA_DISABLED": "true"}
            arguments = ["terraform", "init", "-backend=false", "-input=false"]
            if (providers / "registry.terraform.io/hashicorp/aws/6.69.1").exists():
                arguments.append(f"-plugin-dir={providers}")
            init = subprocess.run(arguments, cwd=directory, env=env, capture_output=True, text=True, timeout=180)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            result = subprocess.run(["terraform", "test", "-json", "-verbose"], cwd=directory, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            plans = {}
            for line in result.stdout.splitlines():
                event = json.loads(line)
                if event.get("type") == "test_plan":
                    plans[event["@testrun"]] = event["test_plan"]
            self.assertEqual(set(plans), set(expected))
            for run, action in expected.items():
                changes = {r["address"]: r["change"] for r in plans[run]["resource_changes"]}
                service_change = changes["aws_lightsail_container_service.api"]
                self.assertEqual(service_change["actions"], [action], run)
                self.assertEqual(service_change["after"]["public_domain_names"], [], run)
                if action == "create":
                    self.assertNotIn("aws_lightsail_certificate.api", changes, run)
                else:
                    self.assertEqual(changes["aws_lightsail_certificate.api"]["actions"], ["delete"], run)
                    self.assertEqual(service_change["before"]["arn"], service_change["after"]["arn"], run)
                self.assertFalse(any("create" in item["actions"] for address, item in changes.items() if address != "aws_lightsail_container_service.api"), run)

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
