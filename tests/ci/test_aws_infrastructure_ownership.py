from __future__ import annotations

import ast
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
AWS_CLI_START = re.compile(
    r"(?<![\w.-])(?:aws|\"aws\"|'aws'|\"[^\"\r\n]*[/\\]aws\"|'[^'\r\n]*[/\\]aws')(?=[ \t])"
)
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
TERRAFORM_CLI = r"(?<![\w.-])(?:terraform|\"terraform\"|'terraform'|\"[^\"\r\n]*[/\\]terraform\"|'[^'\r\n]*[/\\]terraform')"
TERRAFORM_STATE_MUTATION = re.compile(
    TERRAFORM_CLI + TERRAFORM_GLOBAL_OPTIONS +
    r"[ \t]+state[ \t]+(?:push|import|mv|rm|replace-provider)\b"
)
TERRAFORM_WORKSPACE_STATE_MUTATION = re.compile(
    TERRAFORM_CLI + TERRAFORM_GLOBAL_OPTIONS + r"[ \t]+workspace[ \t]+(?:new|delete)\b"
)
TERRAFORM_TOP_LEVEL_STATE_MUTATION = re.compile(
    TERRAFORM_CLI + TERRAFORM_GLOBAL_OPTIONS + r"[ \t]+(?:import|taint|untaint|refresh|force-unlock)\b"
)
TERRAFORM_INIT_STATE_MIGRATION = re.compile(
    TERRAFORM_CLI + TERRAFORM_GLOBAL_OPTIONS + r"[ \t]+init\b"
    r"[^\n;|)]*[ \t]+(?:-migrate-state|-force-copy)(?:[ \t]|$)"
)
UNRESOLVED_SUBPROCESS_COMMAND = "<unresolved-subprocess-command>"


def contains_forbidden_terraform_state_change(source: str) -> bool:
    normalized = normalize_shell_continuations(source)
    return (
        TERRAFORM_STATE_MUTATION.search(normalized) is not None
        or TERRAFORM_WORKSPACE_STATE_MUTATION.search(normalized) is not None
        or TERRAFORM_TOP_LEVEL_STATE_MUTATION.search(normalized) is not None
        or TERRAFORM_INIT_STATE_MIGRATION.search(normalized) is not None
        or any(
            command == UNRESOLVED_SUBPROCESS_COMMAND
            or TERRAFORM_STATE_MUTATION.search(command)
            or TERRAFORM_WORKSPACE_STATE_MUTATION.search(command)
            or TERRAFORM_TOP_LEVEL_STATE_MUTATION.search(command)
            or TERRAFORM_INIT_STATE_MIGRATION.search(command)
            for command in python_subprocess_commands(source)
        )
        or any(
            TERRAFORM_STATE_MUTATION.search(script)
            or TERRAFORM_WORKSPACE_STATE_MUTATION.search(script)
            or TERRAFORM_TOP_LEVEL_STATE_MUTATION.search(script)
            or TERRAFORM_INIT_STATE_MIGRATION.search(script)
            for script in workflow_run_scripts(source)
        )
    )


def normalize_shell_continuations(source: str) -> str:
    return re.sub(r"\\\r?\n[ \t]*", " ", source)


def python_subprocess_commands(source: str) -> list[str]:
    """Extract subprocess commands from Python source, failing closed on dynamic argv."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    subprocess_modules = {"subprocess"}
    subprocess_functions = {"run", "Popen", "call", "check_call", "check_output"}
    aliases: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    subprocess_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in subprocess_functions:
                    aliases[alias.asname or alias.name] = [alias.name]

    assigned_argv: dict[str, list[str] | str | None] = {}
    alias_groups: dict[str, set[str]] = {}

    def root_name(node: ast.AST) -> str | None:
        while isinstance(node, (ast.Attribute, ast.Subscript)):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    def detach_alias(name: str) -> None:
        group = alias_groups.get(name)
        if group is not None:
            group.discard(name)
            for member in group:
                alias_groups[member] = group
        alias_groups[name] = {name}

    def set_argv(name: str, value: list[str] | str | None) -> None:
        group = alias_groups.setdefault(name, {name})
        for member in group:
            assigned_argv[member] = value

    def link_alias(name: str, source_name: str) -> None:
        source_group = alias_groups.setdefault(source_name, {source_name})
        target_group = alias_groups.get(name, {name})
        merged = source_group | target_group
        for member in merged:
            alias_groups[member] = merged
            assigned_argv[member] = assigned_argv.get(source_name)

    def invalidate_target(target: ast.AST) -> None:
        name = root_name(target)
        if name is not None and name in alias_groups:
            set_argv(name, None)

    def invalidate_all_argv() -> None:
        for group in {id(group): group for group in alias_groups.values()}.values():
            if group:
                set_argv(next(iter(group)), None)

    def argv_values(node: ast.AST) -> list[str] | str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            values: list[object] = []
            for item in node.elts:
                try:
                    value = ast.literal_eval(item)
                except (ValueError, TypeError):
                    return None
                if not isinstance(value, str):
                    return None
                values.append(value)
            return values
        if isinstance(node, ast.Name):
            return assigned_argv.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = argv_values(node.left)
            right = argv_values(node.right)
            if isinstance(left, list) and isinstance(right, list):
                return left + right
        return None

    commands: list[str] = []

    class CommandVisitor(ast.NodeVisitor):
        def visit_Module(self, node: ast.Module) -> None:
            for statement in node.body:
                self.visit(statement)

        def visit_Assign(self, node: ast.Assign) -> None:
            value = argv_values(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if isinstance(node.value, ast.Name) and node.value.id in alias_groups:
                        link_alias(target.id, node.value.id)
                    else:
                        detach_alias(target.id)
                        set_argv(target.id, value)
                else:
                    invalidate_target(target)
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            value = argv_values(node.value) if node.value is not None else None
            if isinstance(node.target, ast.Name):
                if isinstance(node.value, ast.Name) and node.value.id in alias_groups:
                    link_alias(node.target.id, node.value.id)
                else:
                    detach_alias(node.target.id)
                    set_argv(node.target.id, value)
            else:
                invalidate_target(node.target)
            if node.value is not None:
                self.visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            if isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
                left = assigned_argv.get(node.target.id)
                right = argv_values(node.value)
                set_argv(node.target.id, left + right if isinstance(left, list) and isinstance(right, list) else None)
            else:
                invalidate_target(node.target)
            self.visit(node.value)

        def visit_Expr(self, node: ast.Expr) -> None:
            self.visit(node.value)

        def visit_control_flow(self, node: ast.AST) -> None:
            invalidate_all_argv()
            self.generic_visit(node)
            invalidate_all_argv()

        def visit_If(self, node: ast.If) -> None:
            self.visit_control_flow(node)

        def visit_For(self, node: ast.For) -> None:
            self.visit_control_flow(node)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
            self.visit_control_flow(node)

        def visit_While(self, node: ast.While) -> None:
            self.visit_control_flow(node)

        def visit_Try(self, node: ast.Try) -> None:
            self.visit_control_flow(node)

        def visit_With(self, node: ast.With) -> None:
            self.visit_control_flow(node)

        def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
            self.visit_control_flow(node)

        def visit_Match(self, node: ast.Match) -> None:
            self.visit_control_flow(node)

        def visit_Call(self, call: ast.Call) -> None:
            function = call.func
            if isinstance(function, ast.Attribute):
                target_name = root_name(function.value)
                if target_name is not None and target_name in alias_groups:
                    current = assigned_argv.get(target_name)
                    incoming = argv_values(call.args[0]) if call.args else None
                    if function.attr == "extend":
                        set_argv(target_name, current + incoming if isinstance(current, list) and isinstance(incoming, list) else None)
                    elif function.attr == "__iadd__":
                        set_argv(target_name, current + incoming if isinstance(current, list) and isinstance(incoming, list) else None)
                    elif function.attr == "append":
                        set_argv(target_name, current + incoming if isinstance(current, list) and isinstance(incoming, str) else None)
                    elif function.attr in {"insert", "pop", "remove", "clear", "reverse", "sort", "__imul__", "__setitem__", "__delitem__"}:
                        set_argv(target_name, None)
            recognized = False
            if isinstance(function, ast.Attribute) and function.attr in subprocess_functions:
                recognized = isinstance(function.value, ast.Name) and function.value.id in subprocess_modules
            elif isinstance(function, ast.Name) and function.id in aliases:
                recognized = True
            if recognized:
                argument = call.args[0] if call.args else next(
                    (keyword.value for keyword in call.keywords if keyword.arg == "args"), None
                )
                value = argv_values(argument) if argument is not None else None
                if isinstance(value, str):
                    commands.append(value)
                elif isinstance(value, list) and value:
                    commands.append(shlex.join(value))
                else:
                    commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                return
            for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
                for child in ast.walk(argument):
                    if isinstance(child, ast.Name) and child.id in alias_groups:
                        set_argv(child.id, None)
            self.generic_visit(call)

        def visit_Delete(self, node: ast.Delete) -> None:
            for target in node.targets:
                invalidate_target(target)

    CommandVisitor().visit(tree)
    return commands


def workflow_run_scripts(source: str) -> list[str]:
    """Read YAML block scalars under `run:` and apply folded/literal semantics."""
    lines = source.splitlines()
    scripts: list[str] = []
    run_block = re.compile(r"^(?P<indent>[ \t]*)run:[ \t]*(?P<style>[>|])(?:[+-]?[1-9]?|[1-9]?[+-]?)[ \t]*(?:#.*)?$")
    index = 0
    while index < len(lines):
        match = run_block.match(lines[index])
        if not match:
            index += 1
            continue
        parent_indent = len(match.group("indent").expandtabs(8))
        index += 1
        body: list[str] = []
        content_indent: int | None = None
        while index < len(lines):
            line = lines[index]
            if line.strip() == "":
                body.append("")
                index += 1
                continue
            indent = len(line) - len(line.lstrip(" \t"))
            if indent <= parent_indent:
                break
            if content_indent is None:
                content_indent = indent
            body.append(line[content_indent:] if len(line) >= content_indent else "")
            index += 1
        scalar = "\n".join(body)
        if match.group("style") == ">":
            scalar = re.sub(r"(?<!\n)\n(?!\n)", " ", scalar)
        if scalar.strip():
            scripts.append(scalar)
    return scripts


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
    for command in python_subprocess_commands(source):
        if command == UNRESOLVED_SUBPROCESS_COMMAND:
            commands.append(("<unresolved-subprocess>", "<unresolved-subprocess>"))
        else:
            commands.extend(aws_cli_commands(command))
    for script in workflow_run_scripts(source):
        commands.extend(aws_cli_commands(script))
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
            'aws --endpoint-url "$AWS_ENDPOINT" s3api put-bucket-policy',
            'aws lightsail --region "$AWS_REGION" get-container-services',
        )
        expected = (
            ("ec2", "terminate-instances"),
            ("s3api", "put-bucket-policy"),
            ("s3api", "put-bucket-policy"),
            ("lightsail", "get-container-services"),
        )
        for command, pair in zip(commands, expected, strict=True):
            with self.subTest(command=command):
                self.assertEqual(aws_cli_commands(command), [pair])

    def test_aws_cli_scanner_handles_quoted_executable(self) -> None:
        commands = (
            '"aws" ec2 terminate-instances --instance-ids i-123',
            '"/usr/local/bin/aws" ec2 terminate-instances --instance-ids i-123',
            "'/opt/aws cli/bin/aws' ec2 terminate-instances --instance-ids i-123",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(aws_cli_commands(command), [("ec2", "terminate-instances")])

    def test_aws_cli_scanner_reads_python_subprocess_argv(self) -> None:
        source = '''
import subprocess
subprocess.run(["aws", "ec2", "terminate-instances", "--instance-ids", "i-123"])
'''
        self.assertEqual(aws_cli_commands(source), [("ec2", "terminate-instances")])

    def test_terraform_guard_reads_python_subprocess_argv(self) -> None:
        source = '''
import subprocess
subprocess.run(["terraform", "state", "rm", "module.example"])
'''
        self.assertTrue(contains_forbidden_terraform_state_change(source))

    def test_python_subprocess_static_argv_mutations_are_resolved(self) -> None:
        terraform_examples = (
            '''
import subprocess
argv = ["terraform"]
argv.extend(["state", "rm", "module.example"])
subprocess.run(argv)
''',
            '''
import subprocess
argv = ["terraform"]
argv += ["state", "rm", "module.example"]
subprocess.run(argv)
''',
        )
        for source in terraform_examples:
            with self.subTest(source=source):
                self.assertTrue(contains_forbidden_terraform_state_change(source))
        aws_examples = (
            '''
import subprocess
argv = ["aws"]
argv.extend(["ec2", "terminate-instances", "--instance-ids", "i-123"])
subprocess.run(argv)
''',
            '''
import subprocess
argv = ["aws"]
argv += ["ec2", "terminate-instances", "--instance-ids", "i-123"]
subprocess.run(argv)
''',
        )
        for source in aws_examples:
            with self.subTest(source=source):
                self.assertEqual(aws_cli_commands(source), [("ec2", "terminate-instances")])

    def test_unresolved_python_subprocess_argv_fails_closed(self) -> None:
        source = "import subprocess\nsubprocess.run(build_command())\n"
        self.assertTrue(contains_forbidden_terraform_state_change(source))
        self.assertEqual(
            aws_cli_commands(source),
            [("<unresolved-subprocess>", "<unresolved-subprocess>")],
        )

    def test_python_subprocess_mutable_argv_writes_fail_closed(self) -> None:
        examples = (
            '''
import subprocess
argv = ["terraform", "plan"]
argv[1:] = ["state", "rm", "module.example"]
subprocess.run(argv)
''',
            '''
import subprocess
argv = ["terraform", "plan"]
alias = argv
alias[1:] = ["state", "rm", "module.example"]
subprocess.run(argv)
''',
            '''
import subprocess
argv = ["terraform", "plan"]
alias = argv
alias.command = "state rm module.example"
subprocess.run(argv)
''',
        )
        for source in examples:
            with self.subTest(source=source):
                self.assertTrue(contains_forbidden_terraform_state_change(source))

    def test_python_subprocess_control_flow_and_nested_mutation_fail_closed(self) -> None:
        conditional = '''
import subprocess
argv = ["terraform", "plan"]
if condition:
    argv[1:] = ["state", "rm", "module.example"]
else:
    argv = ["terraform", "plan"]
subprocess.run(argv)
'''
        nested_mutator = '''
import subprocess
argv = ["terraform"]
result = argv.extend(["state", "rm", "module.example"])
subprocess.run(argv)
'''
        self.assertTrue(contains_forbidden_terraform_state_change(conditional))
        self.assertTrue(contains_forbidden_terraform_state_change(nested_mutator))

    def test_python_subprocess_unknown_helper_mutation_fails_closed(self) -> None:
        source = '''
import subprocess
def mutate(argv):
    argv[1:] = ["state", "rm", "module.example"]
argv = ["terraform", "plan"]
mutate(argv)
subprocess.run(argv)
'''
        self.assertTrue(contains_forbidden_terraform_state_change(source))

    def test_python_subprocess_dunder_inplace_add_is_tracked(self) -> None:
        source = '''
import subprocess
argv = ["terraform"]
argv.__iadd__(["state", "rm", "module.example"])
subprocess.run(argv)
'''
        self.assertTrue(contains_forbidden_terraform_state_change(source))

    def test_workflow_scanner_folds_yaml_run_blocks(self) -> None:
        source = '''
jobs:
  deploy:
    steps:
      - name: AWS
        run: >-
          aws
          ec2 terminate-instances --instance-ids i-123
      - name: Terraform
        run: >
          terraform state
          rm module.example
'''
        scripts = workflow_run_scripts(source)
        self.assertEqual(len(scripts), 2)
        self.assertIn(("ec2", "terminate-instances"), aws_cli_commands(source))
        self.assertTrue(contains_forbidden_terraform_state_change(source))

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
            "terraform workspace new preview",
            "terraform workspace delete preview",
            "terraform import module.example id",
            "terraform taint module.example",
            "terraform untaint module.example",
            "terraform refresh",
            "terraform force-unlock abc123",
            '"terraform" state rm module.example',
            '"/usr/local/bin/terraform" state rm module.example',
            "'/opt/terraform bin/terraform' state rm module.example",
            'terraform -chdir="$root" import module.example id',
            'terraform -chdir="$root" taint module.example',
            'terraform -chdir "$root" untaint module.example',
            'terraform -chdir="$root" force-unlock abc123',
            "terraform -chdir=infra/terraform refresh",
            "terraform init -migrate-state",
            'terraform -chdir="$root" init -force-copy',
            'terraform -chdir="$root" state rm module.example',
            'terraform -chdir="$root" workspace new preview',
            'terraform -chdir "$root" workspace delete preview',
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
