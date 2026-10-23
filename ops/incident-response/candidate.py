"""Deterministic candidate transport; never execute git in agent-owned metadata."""

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath

from deadline import run
from quota import Denied, strict_json

MAX_FILES = 20
MAX_BYTES = 512 * 1024
BACKEND_REGRESSION = "backend/tests/test_incident_regression.py"
FRONTEND_REGRESSION = "frontend/src/incident-regression.test.tsx"

DISALLOWED_NAMES = {
    "uv.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package.json",
    "pyproject.toml",
    "alembic.ini",
    "Dockerfile",
    "vite.config.ts",
    "tsconfig.json",
    "tsconfig.node.json",
    "dsql_post_apply_setup.py",
    "dsql_role_bootstrap.py",
}

DISALLOWED_EXTENSIONS = {
    ".lock",
    ".pyc",
    ".tsbuildinfo",
    ".sql",
    ".env",
}


def is_allowed_path(name):
    if not isinstance(name, str) or not name:
        return False
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts:
        return False
    if len(pure.parts) < 2:
        return False
    if any(part in IGNORED for part in pure.parts):
        return False
    # Only allow regular application code and tests under backend and frontend
    valid_prefix = (
        name.startswith(("backend/pawlocal/", "backend/tests/"))
        or name.startswith(("frontend/src/", "frontend/public/"))
    )
    if not valid_prefix:
        return False
    # Exclude workflow/IAM/auth/security/secrets/infrastructure/data repair per AGENTS.md
    if any(part in ("auth", "security", "infra", "iam", "migrations", "data", "scripts") for part in pure.parts):
        return False
    if (
        pure.stem in ("auth", "security", "dsql_post_apply_setup", "dsql_role_bootstrap")
        or pure.name.startswith(("auth.", "auth_", ".env"))
    ):
        return False
    if pure.name in DISALLOWED_NAMES or pure.suffix in DISALLOWED_EXTENSIONS:
        return False
    return True


class _AllowedContainer:
    """Dynamic allowlist covering all regular application files under backend/ and frontend/."""

    def __contains__(self, item):
        return is_allowed_path(item)


class _LayerContainer:
    def __init__(self, prefix):
        self.prefix = prefix

    def __contains__(self, item):
        return is_allowed_path(item) and item.startswith(self.prefix)


ALLOWED = _AllowedContainer()
BACKEND = _LayerContainer("backend/")
FRONTEND = _LayerContainer("frontend/")
IGNORED = {
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_bytes(root, relative, maximum):
    """Open every component relative to pinned directory FDs, never symlinks."""
    if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
        raise Denied("relative contained path required")
    if os.name != "posix":
        # Offline Windows fixtures only; model/export runtime requires Ubuntu.
        path = root / relative
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise Denied("symlink forbidden")
        if path.stat().st_size > maximum:
            raise Denied("file bound")
        return path.read_bytes()
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            next_descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = next_descriptor
        file_descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor
        )
        try:
            info = os.fstat(file_descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise Denied("bounded regular file required")
            with os.fdopen(file_descriptor, "rb", closefd=False) as stream:
                raw = stream.read(maximum + 1)
            if len(raw) > maximum:
                raise Denied("file grew beyond bound")
            return raw
        finally:
            os.close(file_descriptor)
    except OSError as error:
        raise Denied("unsafe or changing candidate path") from error
    finally:
        os.close(descriptor)


def files(root):
    result = {}
    total = 0
    for directory, directories, names in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name not in IGNORED]
        for name in directories:
            if (Path(directory) / name).is_symlink():
                raise Denied("candidate symlink directory forbidden")
        for name in names:
            path = Path(directory) / name
            if name.endswith((".pyc", ".tsbuildinfo")):
                continue
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise Denied("candidate symlink/special file forbidden")
            total += info.st_size
            if (
                info.st_size > 8 * 1024 * 1024
                or total > 64 * 1024 * 1024
                or len(result) >= 10000
            ):
                raise Denied("working tree inspection bound")
            result[relative] = digest(safe_bytes(root, relative, 8 * 1024 * 1024))
    return result


def export(base, candidate, metadata):
    original, updated = files(base), files(candidate)
    changed = sorted(
        name
        for name in original.keys() | updated.keys()
        if original.get(name) != updated.get(name)
    )
    if not changed or len(changed) > MAX_FILES or any(name not in ALLOWED for name in changed):
        raise Denied("candidate empty, excessive or outside approved paths")
    if any(name not in updated for name in changed):
        raise Denied("source deletion forbidden")
    layers = {"backend" if name.startswith("backend/") else "frontend" for name in changed}
    for layer, regression in (
        ("backend", BACKEND_REGRESSION),
        ("frontend", FRONTEND_REGRESSION),
    ):
        if layer in layers and regression not in changed:
            raise Denied("changed layer requires its fixed regression test")
    content = {}
    for name in changed:
        raw_file = safe_bytes(candidate, name, MAX_BYTES)
        if b"\0" in raw_file:
            raise Denied("binary candidate forbidden")
        try:
            raw_file.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Denied("UTF-8 source required") from error
        content[name] = base64.b64encode(raw_file).decode()
    if sum(len(base64.b64decode(raw)) for raw in content.values()) > MAX_BYTES:
        raise Denied("total candidate bound")
    value = {
        "schema": 1,
        "base_sha": metadata["base_sha"],
        "incident_key": metadata["alert"]["incident_key"],
        "files": content,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return raw


def load(raw, metadata):
    if len(raw) > MAX_BYTES * 2:
        raise Denied("candidate transport bound")
    value = strict_json(raw)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "base_sha", "incident_key", "files"}
        or value["schema"] != 1
        or value["base_sha"] != metadata["base_sha"]
        or value["incident_key"] != metadata["alert"]["incident_key"]
    ):
        raise Denied("candidate provenance differs")
    content = value["files"]
    if (
        not isinstance(content, dict)
        or not 1 <= len(content) <= MAX_FILES
        or any(name not in ALLOWED for name in content)
    ):
        raise Denied("candidate paths forbidden")
    for layer_prefix, regression in (
        ("backend/", BACKEND_REGRESSION),
        ("frontend/", FRONTEND_REGRESSION),
    ):
        if any(name.startswith(layer_prefix) for name in content) and regression not in content:
            raise Denied("fixed regression test required")
    result = {}
    for name, encoded in content.items():
        if not isinstance(encoded, str) or len(encoded) > MAX_BYTES * 2:
            raise Denied("candidate file bound")
        try:
            decoded = base64.b64decode(encoded, validate=True)
            decoded.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise Denied("invalid candidate encoding") from error
        if b"\0" in decoded:
            raise Denied("binary candidate forbidden")
        result[name] = decoded
    if sum(map(len, result.values())) > MAX_BYTES:
        raise Denied("total candidate bound")
    return result


def materialize(content, root):
    for name, raw in content.items():
        # ALLOWED contains only literal names, no user-controlled path joins.
        if name not in ALLOWED or PurePosixPath(name).is_absolute():
            raise Denied("unapproved path")
        target = root / name
        for ancestor in target.parents:
            if ancestor == root.parent:
                break
            if ancestor.is_symlink():
                raise Denied("symlink parent forbidden")
        if target.is_symlink():
            raise Denied("symlink target forbidden")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def git(trusted, *args, input_data=None, extra_env=None):
    # trusted is a fresh, runner-owned repository. Never point at agent .git.
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    environment.update(extra_env or {})
    return (
        run(
            [
                "git",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(trusted),
                *args,
            ],
            input=input_data,
            stdout=subprocess.PIPE,
            check=True,
            env=environment,
        )
        .stdout.decode()
        .strip()
    )


def bind_candidate(trusted, content, metadata, patch_sha):
    # The checked-out source/config here comes from pinned trusted main; allowed
    # changes cannot modify attributes, git config, hooks or external filters.
    if git(trusted, "rev-parse", "HEAD") != metadata["base_sha"]:
        raise Denied("trusted base differs")
    materialize(content, trusted)
    git(trusted, "add", "--", *sorted(content))
    tree = git(trusted, "write-tree")
    timestamp = str(metadata["deadline"] - 1200)
    identity = {
        "GIT_AUTHOR_NAME": "PawLocal Incident Responder",
        "GIT_AUTHOR_EMAIL": "oncall@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "PawLocal Incident Responder",
        "GIT_COMMITTER_EMAIL": "oncall@users.noreply.github.com",
        "GIT_AUTHOR_DATE": timestamp + " +0000",
        "GIT_COMMITTER_DATE": timestamp + " +0000",
    }
    message = f"fix: incident {metadata['alert']['incident_key']}\n\nPatch-SHA256: {patch_sha}\n"
    commit = git(
        trusted,
        "commit-tree",
        tree,
        "-p",
        metadata["base_sha"],
        input_data=message.encode(),
        extra_env=identity,
    )
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise Denied("candidate commit missing")
    return {
        "base_sha": metadata["base_sha"],
        "candidate_sha": commit,
        "tree_sha": tree,
        "patch_sha256": patch_sha,
        "message": message,
        "timestamp": int(timestamp),
    }
