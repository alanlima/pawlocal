from __future__ import annotations

import re
from pathlib import Path
import shlex
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
AWS_CLI_START = re.compile(r"\baws(?=[ \t])")
AWS_OPTIONS_WITH_VALUES = {
    "--ca-bundle",
    "--cli-binary-format",
    "--cli-connect-timeout",
    "--cli-read-timeout",
    "--color",
    "--endpoint-url",
    "--output",
    "--profile",
    "--query",
    "--region",
}
AWS_BOOLEAN_OPTIONS = {
    "--cli-auto-prompt",
    "--debug",
    "--no-cli-auto-prompt",
    "--no-cli-pager",
    "--no-paginate",
    "--no-sign-request",
    "--no-verify-ssl",
    "--version",
}
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
    normalized = normalize_shell_continuations(source)
    commands: list[tuple[str, str]] = []
    for match in AWS_CLI_START.finditer(normalized):
        tail = normalized[match.end():]
        quote = None
        escaped = False
        end = len(tail)
        for index, char in enumerate(tail):
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char in "\n;|)" or (char == "&" and index + 1 < len(tail) and tail[index + 1] == "&"):
                end = index
                break
        try:
            tokens = shlex.split(tail[:end], posix=True)
        except ValueError:
            commands.append(("<unparsed>", "<unparsed>"))
            continue

        def skip_global_options(index: int) -> int | None:
            while index < len(tokens) and tokens[index].startswith("--"):
                option, separator, _ = tokens[index].partition("=")
                if option in AWS_BOOLEAN_OPTIONS:
                    index += 1
                elif option in AWS_OPTIONS_WITH_VALUES:
                    if separator:
                        index += 1
                    elif index + 1 < len(tokens):
                        index += 2
                    else:
                        return None
                else:
                    return None
            return index

        service_index = skip_global_options(0)
        if service_index is None or service_index >= len(tokens):
            commands.append(("<unsupported-option>", "<missing-command>"))
            continue
        service = tokens[service_index]
        operation_index = skip_global_options(service_index + 1)
        if operation_index is None or operation_index >= len(tokens):
            commands.append((service, "<unsupported-option-or-missing-command>"))
            continue
        commands.append((service, tokens[operation_index]))
    return commands


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

    def test_aws_cli_scanner_handles_global_options(self) -> None:
        commands = (
            'aws --region "$AWS_REGION" ec2 terminate-instances --instance-ids i-123',
            "aws --profile deploy --region=ap-southeast-2 s3api put-bucket-policy",
            'aws lightsail --region "$AWS_REGION" get-container-services',
        )
        expected = (
            ("ec2", "terminate-instances"),
            ("s3api", "put-bucket-policy"),
            ("lightsail", "get-container-services"),
        )
        for command, pair in zip(commands, expected, strict=True):
            with self.subTest(command=command):
                self.assertEqual(aws_cli_commands(command), [pair])

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
