from __future__ import annotations

import re
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def workflow_files(directory: Path) -> list[Path]:
    return sorted((*directory.glob("*.yml"), *directory.glob("*.yaml")))


EXECUTION_FILES = [
    *Path(ROOT / "ops").rglob("*.sh"),
    *Path(ROOT / "ops").rglob("*.py"),
    *workflow_files(Path(ROOT / ".github/workflows")),
]
ALLOWED_AWS_COMMANDS = {
    ("lightsail", "get-container-services"),
    ("s3", "sync"),
    ("s3", "cp"),
    ("cloudfront", "create-invalidation"),
}
AWS_CLI_COMMAND = re.compile(r"\baws\s+([a-z0-9-]+)\s+([a-z0-9-]+)\b")
TERRAFORM_GLOBAL_OPTIONS = (
    r"(?:[ \t]+-[A-Za-z0-9][A-Za-z0-9-]*"
    r"(?:=(?:\"[^\"]*\"|'[^']*'|[^\s]+))?"
    r"(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|[^\s-][^\s]*))?)*"
)
TERRAFORM_STATE_MUTATION = re.compile(
    r"\bterraform\b" + TERRAFORM_GLOBAL_OPTIONS +
    r"[ \t]+state[ \t]+(?:push|import|mv|rm|replace-provider)\b"
)
TERRAFORM_IMPORT = re.compile(r"\bterraform\b" + TERRAFORM_GLOBAL_OPTIONS + r"[ \t]+import\b")


def contains_forbidden_terraform_state_change(source: str) -> bool:
    normalized = normalize_shell_continuations(source)
    return (
        TERRAFORM_STATE_MUTATION.search(normalized) is not None
        or TERRAFORM_IMPORT.search(normalized) is not None
    )


def normalize_shell_continuations(source: str) -> str:
    return re.sub(r"\\\r?\n[ \t]*", " ", source)


def aws_cli_commands(source: str) -> list[tuple[str, str]]:
    return AWS_CLI_COMMAND.findall(normalize_shell_continuations(source))


class AwsInfrastructureOwnershipTests(unittest.TestCase):
    def test_executable_automation_does_not_mutate_infrastructure_outside_terraform(self) -> None:
        aws_sdk = re.compile(r"\bboto3\b|(?:require\s*\(|from\s+)[\"']?aws-sdk|@aws-sdk/")
        for path in EXECUTION_FILES:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertFalse(contains_forbidden_terraform_state_change(source), "manual Terraform state changes are prohibited")
                self.assertIsNone(aws_sdk.search(source), "AWS SDK infrastructure mutation is not permitted in deployment scripts")
                for service, operation in aws_cli_commands(source):
                    self.assertIn(
                        (service, operation),
                        ALLOWED_AWS_COMMANDS,
                        f"unapproved AWS CLI command: aws {service} {operation}",
                    )

    def test_aws_cli_scanner_handles_shell_continuations(self) -> None:
        command = "aws s3api " + "\\" + "\n  put-bucket-policy --bucket pawlocal-example"
        self.assertEqual(aws_cli_commands(command), [("s3api", "put-bucket-policy")])
        self.assertNotIn(aws_cli_commands(command)[0], ALLOWED_AWS_COMMANDS)
        split_service_and_operation = (
            "aws " + "\\" + "\n  ec2 " + "\\" + "\n  terminate-instances --instance-ids i-123"
        )
        self.assertEqual(aws_cli_commands(split_service_and_operation), [("ec2", "terminate-instances")])

    def test_workflow_discovery_includes_yml_and_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            (directory / "legacy.yml").touch()
            (directory / "current.yaml").touch()
            self.assertEqual(
                {path.name for path in workflow_files(directory)},
                {"legacy.yml", "current.yaml"},
            )

    def test_state_mutation_guard_handles_global_terraform_options(self) -> None:
        prohibited = (
            "terraform state rm module.example",
            "terraform import module.example id",
            'terraform -chdir="$root" import module.example id',
            'terraform -chdir="$root" state rm module.example',
            'terraform -chdir "$root" state import module.example id',
            "terraform -chdir=infra/terraform state mv a b",
        )
        for command in prohibited:
            with self.subTest(command=command):
                self.assertTrue(contains_forbidden_terraform_state_change(command))
        continued = "terraform " + "\\" + "\n  -chdir=infra/terraform " + "\\" + "\n  state rm module.example"
        self.assertTrue(contains_forbidden_terraform_state_change(continued))
        self.assertFalse(contains_forbidden_terraform_state_change('terraform -chdir="$root" plan -input=false'))

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
