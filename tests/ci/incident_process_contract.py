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
        "bind_candidate": "cdf4172987de1efe8f179bce997f149630be61fbd6a3284432dc6de532adc58d",
        "git": "19681485986ec04139147187aeb482eb348dd1a1fdd911765e33798bbe5f547a",
    },
    "capture-cli-request.py": {
        "main": "9990bee5b4b2ccc14b97e7e9c6cc94efb1dec01279cec30a288eb7c7a3dcfc66"
    },
    "checks.py": {
        "share_check_source": "420ab56b7609de0e9c7068b51ff81a5fc54f8972377ba46e5232c75eeb863978",
        "execute": "87ddc2ceaa331d58c81c9e20dc4d5175047fd92a11b20049815683c69438c857",
        "main": "e869b64b148fffb1b52eab38fa2d87a1585a64bc4e8197c865c9cfd4e4ff5ffa",
        "regression": "7195586699cff52a9d3b6c240ef10c2b537d95dbb4a0e117394de5c44b4f81e5",
        "backend_quality": "dbbb568181d9b5d62c45f820dcc16eaffc372fdac9864bb009772e3833b62479",
    },
    "deadline.py": {
        "run": "5093d4f55b56dccd98c7f017e8e000daa73d49a3453f62558710406925796b3b"
    },
    "job.py": {
        "review_seal": "b31d3b00fd53fbf92570c47d64c700a3afda09d08a2d68961c7c665198a7c17d",
        "seal": "072a7a25c9f40c39b1cd745fe3620446819686898610a611ca57a581404bfbeb",
        "reclaim_model_output": "1b9068c2da92898e38a6f6dac7359500be73664e1a8f43b3c2111a3f69964321",
        "archive": "4cb6d3e3ec09d85929d60fe9dd8a687898bcc1780fadcbf41807a2feb7a0bd29",
        "download": "e5f20c0dd06f004baf551352c8f5ea5216331d77415a69aa44a1a93e58df7ad3",
        "main": "61930aba768d1763b49c2f1ddcbeae651c59b3474a6749ed9b10451e7d0821c2",
        "prepare": "4f3fcd49e48ea1efe867bdf307b3442b7f6e2a37c1774504c8ce9b7ea0ccccce",
        "quiesce": "340951b162cef3a91b8baf1bb8f0e0342ae27bdae8ae8d5cfc7844d6775f5efa",
        "uid": "70fa3cbd5291221adea58c1be77e48794dbf3d45e3181c0a21734ab4a3fbeacc",
        "writable_tool_caches": "88c28e4bc71d939be736c2f410c7fe38f5df71b9757f6cfd94b8feefb968e53c",
    },
    "render-check-sql.py": {
        "main": "20a1fd019c5e189e0c01811c5a0e2236579f152e6039b404c1144d88ce8bd608"
    },
    "process_policy.py": {
        "approved": "0629af3301f087a753c6bfeb41159eba90cfa35896fb8584b394437f2b9c2e28",
        "path": "4d97180285e9f90428b934131176143d46328dd68c11ecb8760724243dfa059b",
        "unprivileged": "a27a9c75aa3f68f2ff5d5d8b94030497358de6c87d862fb0b970f869d1ed6cf6",
        "validate": "e7e2e826f3a1657f13e7830cc6b2bcefaa0ee15f014b5b2e250ab13afd8a7271",
    },
}


def fingerprint(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


GLOBALS = {
    "candidate.py": "1e4b34e724bf9e0a9c60b2b321fb35b20d7b4bddc981767efa19fb90986cf144",
    "capture-cli-request.py": "b92a34dd110c8d3ae05f6af18988e3d23a411bc3812ad5e77f83ffeaeb60a79c",
    "checks.py": "1a48b41cb9b165c7c75abbdc222d8daa4729b1b27a32fc649a81579e64eec154",
    "deadline.py": "ec75edbd5d348b21f1607603f616eb1b54320a672bf5b9428f159bd5078d69d7",
    "job.py": "84245d4b6cb62fb0f62a30eaa68dc6c07be0e75684186c421711a8278e968acf",
    "render-check-sql.py": "cae8479e6dcc93f558a44e8cbd5fb4f8040d5c256b996e869128fa131c37af1c",
    "process_policy.py": "55cf9a36a5254acd6a360ba4b95e2c73ad7fbc6aacaf711bb849efefe11c10f2",
}
DYNAMIC_READERS = {
    "ops/configuration/tests/test_integration.py": "a2d921d98b186ddf53f6ed705e52b2a476d0fcdba1902237594114cbe2d6b06d",
    "ops/configuration/tests/test_job_summary.py": "bdbac3edd26f3b5dc889ff3aacee998bcd39e68669949fa2541185825a0f96e5",
    "ops/configuration/tests/test_reconcile.py": "98dcf2e0764a561fc641b90f4763e1d052201f5a2d0bf71a5b4af30c19612c9a",
    "ops/incident-response/settings.py": "7fdb481adb4b1be232a2619a4960d7ee96538f57ba9f53b7a2b2d6cc72732399",
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
