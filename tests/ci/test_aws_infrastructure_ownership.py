from __future__ import annotations

import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_FILES = [
    *Path(ROOT / "ops").rglob("*.sh"),
    *Path(ROOT / "ops").rglob("*.py"),
    *Path(ROOT / ".github/workflows").glob("*.yml"),
]
ALLOWED_AWS_COMMANDS = {
    ("lightsail", "get-container-services"),
    ("s3", "sync"),
    ("s3", "cp"),
    ("cloudfront", "create-invalidation"),
}


class AwsInfrastructureOwnershipTests(unittest.TestCase):
    def test_executable_automation_does_not_mutate_infrastructure_outside_terraform(self) -> None:
        forbidden_state = re.compile(r"\bterraform\s+state\s+(?:push|import|mv|rm|replace-provider)\b")
        aws_commands = re.compile(r"\baws\s+([a-z0-9-]+)\s+([a-z0-9-]+)\b")
        aws_sdk = re.compile(r"\bboto3\b|(?:require\s*\(|from\s+)[\"']?aws-sdk|@aws-sdk/")
        for path in EXECUTION_FILES:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNone(forbidden_state.search(source), "manual Terraform state mutation is prohibited")
                self.assertIsNone(aws_sdk.search(source), "AWS SDK infrastructure mutation is not permitted in deployment scripts")
                for service, operation in aws_commands.findall(source):
                    self.assertIn(
                        (service, operation),
                        ALLOWED_AWS_COMMANDS,
                        f"unapproved AWS CLI command: aws {service} {operation}",
                    )

    def test_frontend_destinations_come_from_the_authoritative_terraform_outputs(self) -> None:
        deploy_script = (ROOT / "ops/terraform-lightsail-container-deploy.sh").read_text(encoding="utf-8")
        self.assertIn('terraform -chdir="$root" output -json environment_targets', deploy_script)
        self.assertIn("PAWLOCAL_FRONTEND_BUCKET={bucket}", deploy_script)
        self.assertIn("PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID={distribution}", deploy_script)

        for workflow in (
            "fullstack-release.yml",
            "deploy-production.yml",
            "rollback-development.yml",
        ):
            source = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
            self.assertNotIn("vars.PAWLOCAL_FRONTEND_BUCKET", source)
            self.assertNotIn("vars.PAWLOCAL_CLOUDFRONT_DISTRIBUTION_ID", source)
            terraform_step = source.index("terraform-lightsail-container-deploy.sh")
            publish_step = source.index("run-deployment-adapter.sh deploy")
            self.assertLess(terraform_step, publish_step)


if __name__ == "__main__":
    unittest.main()
