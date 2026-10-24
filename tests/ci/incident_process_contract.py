"""Reviewed dynamic runner launches; never a filename-level scanner exemption.

Only four direct launch expressions are removed after validating their complete
containing functions and the command-producing wrapper functions. Normalized AST
fingerprints deliberately require renewed review when executable semantics change;
formatting and comments do not change them. The generic AWS/state scanner still
examines every other node. No fingerprint is generated during a test run.
"""

import ast
import hashlib
from pathlib import Path

DIRECT = {
    "capture-cli-request.py": ("main", 1),
    "deadline.py": ("run", 1),
    "job.py": ("prepare", 2),
}
# The readable source is the review artifact. These fingerprints bind complete
# argv producers, local variable assignments, credentials/env and wrapper logic,
# rather than just a Popen(command) sink or a fixed launcher count.
FUNCTIONS = {
    "candidate.py": {
        "bind_candidate": "866e6c6baf9a41127f9c7b13a069110a869efad12072803f66b8f263ac6ddb36",
        "git": "19681485986ec04139147187aeb482eb348dd1a1fdd911765e33798bbe5f547a",
    },
    "capture-cli-request.py": {
        "main": "9990bee5b4b2ccc14b97e7e9c6cc94efb1dec01279cec30a288eb7c7a3dcfc66"
    },
    "checks.py": {
        "execute": "e5cb7583af203b43e282dfd0e11ca065c3fab0cdc660ef7b8f078392fcea7892",
        "main": "a1ea2c1ac7c01fd62eff4c9ebfb25a3b93a4c2e70c6b4ae973ff223bb26c7f56",
        "regression": "21e5c4ff5578578c907cf25e5c0c6fe104f6b5b018cc043241a62b2fd9f372c1",
    },
    "deadline.py": {
        "run": "5093d4f55b56dccd98c7f017e8e000daa73d49a3453f62558710406925796b3b"
    },
    "job.py": {
        "review_seal": "194299317a3f964f900310879adb3b0d8281cec6d16bb87d29241800a9a3dd2f",
        "seal": "072a7a25c9f40c39b1cd745fe3620446819686898610a611ca57a581404bfbeb",
        "reclaim_model_output": "0b20bc8c567b5138892d7e577a7fe467dc6b8300ab79e9e9e8f992cbdefa563a",
        "archive": "4cb6d3e3ec09d85929d60fe9dd8a687898bcc1780fadcbf41807a2feb7a0bd29",
        "download": "e5f20c0dd06f004baf551352c8f5ea5216331d77415a69aa44a1a93e58df7ad3",
        "main": "61930aba768d1763b49c2f1ddcbeae651c59b3474a6749ed9b10451e7d0821c2",
        "prepare": "19361878a0f29a1342ba7683ce5fe2222386a41d747ebdc70b1f1368af7c3d06",
        "quiesce": "340951b162cef3a91b8baf1bb8f0e0342ae27bdae8ae8d5cfc7844d6775f5efa",
        "uid": "70fa3cbd5291221adea58c1be77e48794dbf3d45e3181c0a21734ab4a3fbeacc",
        "writable_tool_caches": "88c28e4bc71d939be736c2f410c7fe38f5df71b9757f6cfd94b8feefb968e53c",
    },
    "process_policy.py": {
        "approved": "404d29e92f92de6609f832661c62720862af8230569b8f6f72623d13499ea789",
        "path": "4d97180285e9f90428b934131176143d46328dd68c11ecb8760724243dfa059b",
        "unprivileged": "586a994c027c4d0e933d62637ccd6f9ba9715b4a366b75d4683a90345bc44bb3",
        "validate": "78232d88029fe84081de700e21f284344d39553e0d01e5a9e82a63b1532f9612",
    },
}


def fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


GLOBALS = {
    "candidate.py": "75ef4d8c0e19a4d222ea5b3b892e437d76130b605ce45d64426934527cf137de",
    "capture-cli-request.py": "b92a34dd110c8d3ae05f6af18988e3d23a411bc3812ad5e77f83ffeaeb60a79c",
    "checks.py": "ab7574af46865e05c77075e394d74cf01d507c2cffd7222fe3c5cafac09ed6f5",
    "deadline.py": "f3d0c3f4d9ea7f5f98d8b0f611a1c3ef98ab00620ecec4f9cd5ae24e0be4f89f",
    "job.py": "afdc26e3b673d22b0f680ea5d2705297c6a466c8ea7f9625998f1c7c7279022b",
    "process_policy.py": "fe451a62948669ded19f3cfc61d8233129fc2496fe984ed3881c63c85149be62",
}
DYNAMIC_READERS = {
    "ops/configuration/tests/test_integration.py": "a2d921d98b186ddf53f6ed705e52b2a476d0fcdba1902237594114cbe2d6b06d",
    "ops/configuration/tests/test_job_summary.py": "bdbac3edd26f3b5dc889ff3aacee998bcd39e68669949fa2541185825a0f96e5",
    "ops/configuration/tests/test_reconcile.py": "98dcf2e0764a561fc641b90f4763e1d052201f5a2d0bf71a5b4af30c19612c9a",
    "ops/incident-response/settings.py": "aa1b6fcff93ed7b23112b56a51de2a88bf7079e406c2e693cfd2353593dac208",
    "ops/tests/test_validate_seeded_places.py": "8a4e16668d014e543e4e73ce7f903a33316d39eb9aed1f7b39a444b2135b3f71",
}


def direct_launch(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in {"Popen", "run"}
    )


def literal_json_import(node, tree):
    # Existing release-config tests use this exact stdlib import as an expression.
    # It cannot acquire deadline or escape the import callable as an alias.
    return (
        isinstance(node, ast.Name)
        and node.id == "__import__"
        and any(
            isinstance(parent, ast.Call)
            and parent.func is node
            and len(parent.args) == 1
            and not parent.keywords
            and isinstance(parent.args[0], ast.Constant)
            and parent.args[0].value == "json"
            for parent in ast.walk(tree)
        )
    )


def validate_inventory(root, overrides=None):
    """Reject new/changed wrappers and aliases before trusting a launch node."""
    overrides = overrides or {}
    directory = Path(root) / "ops/incident-response"
    for name, expected in FUNCTIONS.items():
        source = overrides.get(name, (directory / name).read_text(encoding="utf-8"))
        tree = ast.parse(source)
        definitions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        globals_tree = ast.Module(
            body=[
                node
                for node in tree.body
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                )
            ],
            type_ignores=[],
        )
        if fingerprint(globals_tree) != GLOBALS[name]:
            raise AssertionError(f"Launcher import/global provenance changed: {name}")
        for function, digest in expected.items():
            if (
                function not in definitions
                or fingerprint(definitions[function]) != digest
            ):
                raise AssertionError(
                    f"Renew independent process-contract review: {name}:{function}"
                )
    # Only these reviewed modules may import/use the dynamic deadline.run wrapper.
    approved = {"candidate.py", "checks.py", "job.py"}
    for path in (Path(root) / "ops").rglob("*.py"):
        source = overrides.get(path.name, path.read_text(encoding="utf-8"))
        tree = ast.parse(source)
        relative = path.relative_to(root).as_posix()
        dynamic = any(
            isinstance(node, (ast.Import, ast.ImportFrom))
            and (
                isinstance(node, ast.Import)
                and any(item.name.startswith("importlib") for item in node.names)
                or isinstance(node, ast.ImportFrom)
                and str(node.module).startswith("importlib")
            )
            or isinstance(node, ast.Attribute)
            and node.attr == "modules"
            for node in ast.walk(tree)
        )
        if dynamic and (
            relative not in DYNAMIC_READERS
            or fingerprint(tree) != DYNAMIC_READERS[relative]
        ):
            raise AssertionError(
                "New/changed dynamic loader or module namespace access requires review"
            )
        if any(
            isinstance(node, ast.Name)
            and not literal_json_import(node, tree)
            and node.id
            in {"__import__", "__builtins__", "eval", "exec", "globals", "locals"}
            or isinstance(node, ast.Attribute)
            and node.attr in {"__import__", "import_module", "__globals__", "__code__"}
            or isinstance(node, ast.Constant)
            and node.value in ("__import__", "import_module")
            or isinstance(node, ast.Import)
            and any(item.name == "builtins" for item in node.names)
            or isinstance(node, ast.ImportFrom)
            and node.module == "builtins"
            or isinstance(node, ast.Global)
            and set(node.names) & {"subprocess", "sys", "shutil", "run", "validate"}
            for node in ast.walk(tree)
        ):
            raise AssertionError(
                "Dynamic wrapper/launcher rebinding requires review: " + relative
            )
        aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                item.name == "deadline" for item in node.names
            ):
                raise AssertionError(
                    "Qualified deadline wrapper imports require review"
                )
            if isinstance(node, ast.ImportFrom) and node.module == "deadline":
                for item in node.names:
                    if item.name in {"run", "*"}:
                        if (
                            path.parent != directory
                            or path.name not in approved
                            or item.name != "run"
                            or item.asname
                        ):
                            raise AssertionError(
                                "New deadline wrapper caller/alias requires review"
                            )
                        aliases.add(item.name)
        parents = {
            child: node
            for node in ast.walk(tree)
            for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in aliases
            ):
                parent = parents.get(node)
                containing = node
                while containing in parents and not isinstance(
                    containing, ast.FunctionDef
                ):
                    containing = parents[containing]
                # A reviewed local workflow-run ID shadows the imported function.
                if (
                    path.name == "job.py"
                    and isinstance(containing, ast.FunctionDef)
                    and containing.name == "download"
                ):
                    continue
                if not isinstance(parent, ast.Call) or parent.func is not node:
                    raise AssertionError(
                        f"Deadline wrapper cannot escape as a callable: {path.name}:{node.lineno}"
                    )
                if (
                    not isinstance(containing, ast.FunctionDef)
                    or containing.name not in FUNCTIONS[path.name]
                ):
                    raise AssertionError(
                        "New deadline wrapper callsite requires review"
                    )
                if any(
                    keyword.arg in {None, "shell", "executable"}
                    for keyword in parent.keywords
                ):
                    raise AssertionError(
                        "Wrapper cannot use shell/executable/dynamic kwargs"
                    )


def residual_source(root, path, source):
    validate_inventory(root, {path.name: source})
    tree = ast.parse(source)
    function, count = DIRECT[path.name]
    definition = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function
    )
    launches = [node for node in ast.walk(tree) if direct_launch(node)]
    if len(launches) != count or any(
        node not in set(ast.walk(definition)) for node in launches
    ):
        raise AssertionError("Unexpected direct runner launch inventory")
    for node in launches:
        if any(keyword.arg in {"shell", "executable"} for keyword in node.keywords):
            raise AssertionError("Direct launcher cannot select shell/executable")

    class RemoveProvenLaunches(ast.NodeTransformer):
        def visit_Call(self, node):
            if node in launches:
                return ast.copy_location(ast.Constant(None), node)
            return self.generic_visit(node)

    return ast.unparse(RemoveProvenLaunches().visit(tree))
