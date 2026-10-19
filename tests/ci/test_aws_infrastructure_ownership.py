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
AWS_SDK_USAGE = re.compile(r"\bboto3\b|\bbotocore\b|(?:require\s*\(|from\s+)[\"']?aws-sdk|@aws-sdk/")


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
            for command in python_process_launch_commands(source)
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


def python_process_launch_commands(source: str) -> list[str]:
    """Extract Python process-launch commands, failing closed on dynamic inputs."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    subprocess_modules: set[str] = set()
    os_modules: set[str] = set()
    asyncio_modules: set[str] = set()
    subprocess_functions = {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"}
    os_functions = {"system", "popen", "startfile", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "spawnlp", "spawnlpe", "posix_spawn", "posix_spawnp"}
    asyncio_functions = {"create_subprocess_exec", "create_subprocess_shell", "subprocess_exec", "subprocess_shell"}
    aliases: dict[str, tuple[str, str] | None] = {}
    def launchable(node: ast.AST) -> tuple[str, str] | None:
        if isinstance(node, ast.Name):
            return aliases.get(node.id)
        if not isinstance(node, ast.Attribute):
            return None
        module_name = node.value.id if isinstance(node.value, ast.Name) else None
        if module_name in subprocess_modules and node.attr in subprocess_functions:
            return ("subprocess", node.attr)
        if module_name in os_modules and node.attr in os_functions:
            return ("os", node.attr)
        if module_name in asyncio_modules and node.attr in {"create_subprocess_exec", "create_subprocess_shell"}:
            return ("asyncio", node.attr)
        if node.attr in {"subprocess_exec", "subprocess_shell"}:
            return ("asyncio_loop", node.attr)
        return None

    def callable_reference(node: ast.AST) -> bool:
        """Detect launch callables used as values; only direct import aliases are modeled."""
        if isinstance(node, ast.Call):
            # The callable is invoked here, so only inspect its arguments for stored
            # launch callables; the call itself is handled by visit_Call.
            return any(callable_reference(arg) for arg in [*node.args, *(kw.value for kw in node.keywords)])
        if launchable(node) is not None:
            return True
        if isinstance(node, ast.Attribute) and node.attr in (subprocess_functions | os_functions | asyncio_functions):
            module = node.value.id if isinstance(node.value, ast.Name) else None
            return module in {"subprocess", "os", "asyncio"}
        return any(callable_reference(child) for child in ast.iter_child_nodes(node))

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

        def visit_Import(self, node: ast.Import) -> None:
            for item in node.names:
                binding = item.asname or item.name.split(".")[0]
                if item.name == "subprocess":
                    subprocess_modules.add(binding)
                elif item.name == "os":
                    os_modules.add(binding)
                elif item.name == "asyncio":
                    asyncio_modules.add(binding)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            for item in node.names:
                binding = item.asname or item.name
                family = None
                if node.module == "subprocess" and item.name in subprocess_functions:
                    family = ("subprocess", item.name)
                elif node.module == "os" and item.name in os_functions:
                    family = ("os", item.name)
                elif node.module == "asyncio" and item.name in {"create_subprocess_exec", "create_subprocess_shell"}:
                    family = ("asyncio", item.name)
                if family is not None:
                    aliases[binding] = family

        def visit_Assign(self, node: ast.Assign) -> None:
            value = argv_values(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    callable_alias = launchable(node.value)
                    if callable_alias is not None:
                        aliases[target.id] = None
                        commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                    else:
                        aliases.pop(target.id, None)
                        if callable_reference(node.value):
                            commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                    if isinstance(node.value, ast.Name) and node.value.id in alias_groups:
                        link_alias(target.id, node.value.id)
                    else:
                        detach_alias(target.id)
                        set_argv(target.id, value)
                else:
                    invalidate_target(target)
                    if callable_reference(node.value):
                        commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            value = argv_values(node.value) if node.value is not None else None
            if isinstance(node.target, ast.Name):
                callable_alias = launchable(node.value) if node.value is not None else None
                if callable_alias is not None:
                    aliases[node.target.id] = None
                    commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                else:
                    aliases.pop(node.target.id, None)
                    if node.value is not None and callable_reference(node.value):
                        commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                if isinstance(node.value, ast.Name) and node.value.id in alias_groups:
                    link_alias(node.target.id, node.value.id)
                else:
                    detach_alias(node.target.id)
                    set_argv(node.target.id, value)
            else:
                invalidate_target(node.target)
                if node.value is not None and callable_reference(node.value):
                    commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
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
            for name in list(aliases):
                aliases[name] = None
            self.generic_visit(node)
            invalidate_all_argv()
            for name in list(aliases):
                aliases[name] = None

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
            launch_family: str | None = None
            launch_name: str | None = None
            if isinstance(function, ast.Attribute):
                module_name = function.value.id if isinstance(function.value, ast.Name) else None
                if module_name in subprocess_modules and function.attr in subprocess_functions:
                    launch_family, launch_name, recognized = "subprocess", function.attr, True
                elif module_name in os_modules and function.attr in os_functions:
                    launch_family, launch_name, recognized = "os", function.attr, True
                elif module_name in asyncio_modules and function.attr in {"create_subprocess_exec", "create_subprocess_shell"}:
                    launch_family, launch_name, recognized = "asyncio", function.attr, True
                elif function.attr in {"subprocess_exec", "subprocess_shell"}:
                    launch_family, launch_name, recognized = "asyncio_loop", function.attr, True
            elif isinstance(function, ast.Name) and function.id in aliases:
                recognized = True
                callable_alias = aliases[function.id]
                if callable_alias is not None:
                    launch_family, launch_name = callable_alias
            if recognized:
                if launch_family is None or launch_name is None:
                    commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                    return
                argument = call.args[0] if call.args else next(
                    (keyword.value for keyword in call.keywords if keyword.arg == "args"), None
                )
                if launch_family == "os" and launch_name in {"execv", "execve", "execvp", "execvpe"}:
                    argument = call.args[1] if len(call.args) > 1 else None
                elif launch_family == "os" and launch_name in {"spawnv", "spawnve", "spawnvp", "spawnvpe"}:
                    argument = call.args[2] if len(call.args) > 2 else None
                elif launch_family == "os" and launch_name in {"posix_spawn", "posix_spawnp"}:
                    argument = call.args[1] if len(call.args) > 1 else None
                elif launch_family == "os" and launch_name in {"execl", "execle", "execlp", "execlpe"}:
                    argument = ast.List(elts=call.args[1:], ctx=ast.Load()) if len(call.args) > 1 else None
                elif launch_family == "os" and launch_name in {"spawnl", "spawnle", "spawnlp", "spawnlpe"}:
                    argument = ast.List(elts=call.args[2:], ctx=ast.Load()) if len(call.args) > 2 else None
                elif launch_family == "asyncio" and launch_name == "create_subprocess_exec":
                    argument = ast.List(elts=call.args, ctx=ast.Load()) if call.args else None
                elif launch_family == "asyncio_loop" and launch_name == "subprocess_exec":
                    argument = ast.List(elts=call.args[1:], ctx=ast.Load()) if len(call.args) > 1 else None
                elif launch_family == "asyncio_loop" and launch_name == "subprocess_shell":
                    argument = call.args[1] if len(call.args) > 1 else None
                value = argv_values(argument) if argument is not None else None
                if isinstance(value, str):
                    commands.append(value)
                elif isinstance(value, list) and value:
                    commands.append(shlex.join(value))
                else:
                    commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
                return
            for argument in [*call.args, *(keyword.value for keyword in call.keywords)]:
                if callable_reference(argument):
                    commands.append(UNRESOLVED_SUBPROCESS_COMMAND)
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
    for script in workflow_run_scripts(source):
        commands.extend(aws_cli_commands(script))
    return commands


def python_aws_cli_commands(source: str) -> list[tuple[str, str]]:
    commands: list[tuple[str, str]] = []
    for command in python_process_launch_commands(source):
        if command == UNRESOLVED_SUBPROCESS_COMMAND:
            commands.append(("<unresolved-subprocess>", "<unresolved-subprocess>"))
        else:
            commands.extend(aws_cli_commands(command))
    return commands


class AwsInfrastructureOwnershipTests(unittest.TestCase):
    def test_executable_automation_does_not_mutate_infrastructure_outside_terraform(self) -> None:
        for path in EXECUTION_FILES:
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertFalse(contains_forbidden_terraform_state_change(source), "manual Terraform state changes are prohibited")
                self.assertIsNone(AWS_SDK_USAGE.search(source), "AWS SDK infrastructure mutation is not permitted in deployment scripts")
                scanned_commands = python_aws_cli_commands(source) if path.suffix == ".py" else aws_cli_commands(source)
                for service, operation in scanned_commands:
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
        self.assertEqual(python_aws_cli_commands(source), [("ec2", "terminate-instances")])

    def test_python_process_launch_apis_are_scanned_and_fail_closed(self) -> None:
        source = '''
import os
import subprocess
prefix = "aw"
subprocess.getoutput(prefix + "s ec2 terminate-instances")
subprocess.getstatusoutput(build_command())
os.system("terraform state rm module.example")
os.popen(build_command())
'''
        self.assertTrue(contains_forbidden_terraform_state_change(source))
        self.assertIn(("<unresolved-subprocess>", "<unresolved-subprocess>"), python_aws_cli_commands(source))
        static_os_command = 'import os\nos.system("aws ec2 terminate-instances --instance-ids i-123")\n'
        self.assertEqual(python_aws_cli_commands(static_os_command), [("ec2", "terminate-instances")])

    def test_botocore_sdk_usage_is_rejected(self) -> None:
        source = '''
from botocore.session import Session
client = Session().create_client("ec2")
client.terminate_instances(InstanceIds=["i-123"])
'''
        self.assertIsNotNone(AWS_SDK_USAGE.search(source))

    def test_posix_spawn_and_asyncio_subprocess_apis_are_scanned(self) -> None:
        source = '''
import asyncio
import os
os.posix_spawn("/usr/bin/aws", ["aws", "ec2", "terminate-instances"], env)
os.posix_spawnp("terraform", ["terraform", "state", "rm", "module.example"], env)
asyncio.create_subprocess_exec("aws", "s3api", "put-bucket-policy")
asyncio.create_subprocess_shell(build_command())
loop.subprocess_exec(protocol_factory, "terraform", "state", "rm", "module.example")
loop.subprocess_shell(protocol_factory, build_command())
'''
        self.assertTrue(contains_forbidden_terraform_state_change(source))
        commands = python_aws_cli_commands(source)
        self.assertIn(("ec2", "terminate-instances"), commands)
        self.assertIn(("s3api", "put-bucket-policy"), commands)
        self.assertIn(("<unresolved-subprocess>", "<unresolved-subprocess>"), commands)

    def test_python_process_launch_callable_aliases_are_scanned(self) -> None:
        source = '''
import asyncio
import os
import subprocess
launch = os.posix_spawnp
launch("terraform", ["terraform", "state", "rm", "module.example"], env)
run = subprocess.run
run(["aws", "ec2", "terminate-instances"])
shell = asyncio.create_subprocess_shell
shell(build_command())
from os import system as run_shell
run_shell("terraform state rm module.example")
from asyncio import create_subprocess_exec as async_run
async_run("aws", "s3api", "put-bucket-policy")
'''
        self.assertTrue(contains_forbidden_terraform_state_change(source))
        commands = python_aws_cli_commands(source)
        self.assertNotIn(("ec2", "terminate-instances"), commands)
        # Direct from-import aliases remain supported; assigned callable aliases fail closed.
        self.assertIn(("s3api", "put-bucket-policy"), commands)
        self.assertIn(("<unresolved-subprocess>", "<unresolved-subprocess>"), commands)

    def test_launch_callable_value_aliases_fail_closed_in_source_order(self) -> None:
        examples = (
            "import subprocess\nif condition:\n    launch = subprocess.run\nlaunch(['aws', 'ec2', 'terminate-instances'])\n",
            "run = subprocess.run\nfrom subprocess import run\nrun(['aws', 'ec2', 'terminate-instances'])\n",
            "import subprocess\nlaunches = [subprocess.run]\n",
            "import subprocess\nholder.launch = subprocess.run\n",
            "import subprocess\nhelper(subprocess.run)\n",
        )
        for source in examples:
            with self.subTest(source=source):
                self.assertIn(("<unresolved-subprocess>", "<unresolved-subprocess>"), python_aws_cli_commands(source))

    def test_direct_imported_launch_alias_remains_supported(self) -> None:
        source = "from subprocess import run as launch\nlaunch(['aws', 'ec2', 'terminate-instances'])\n"
        self.assertEqual(python_aws_cli_commands(source), [("ec2", "terminate-instances")])

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
                self.assertEqual(python_aws_cli_commands(source), [("ec2", "terminate-instances")])

    def test_unresolved_python_subprocess_argv_fails_closed(self) -> None:
        source = "import subprocess\nsubprocess.run(build_command())\n"
        self.assertTrue(contains_forbidden_terraform_state_change(source))
        self.assertEqual(
            python_aws_cli_commands(source),
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
