"""Finite trusted runner command families, independent of caller discovery."""

import os
import re
import sys
from pathlib import Path, PurePath

from quota import Denied

DEPENDENCIES = "/tmp/pawlocal-oncall-dependencies"
CHECK_REPORTS = {
    f"/tmp/pawlocal-oncall-check-work/{source}/{report}"
    for source in ("affected", "main", "candidate")
    for report in (
        "backend-regression.xml",
        "frontend-regression.json",
    )
}
CHECK_REPORTS |= {
    "/tmp/pawlocal-oncall-check-work/candidate/backend-quality.xml",
    "/tmp/pawlocal-oncall-check-work/candidate/backend-search.sql",
}
TEST_DATABASE_URL = (
    "postgresql+psycopg://pawlocal:pawlocal-ci-password@127.0.0.1:5432/pawlocal_test"
)
HOME_FILES = {
    "/home/oncall/" + name
    for name in ("candidate.diff", "review-schema.json", "incident-prompt.md")
}
SUDOERS = "/etc/sudoers.d/pawlocal-codex-home"


def path(value, roots):
    return (
        PurePath(value).is_absolute()
        and ".." not in PurePath(value).parts
        and any(value == root or value.startswith(root + "/") for root in roots)
    )


def unprivileged(command):
    if command in (
        [DEPENDENCIES + "/venv/bin/python", "-m", "pytest", "--version"],
        [
            DEPENDENCIES + "/venv/bin/python",
            DEPENDENCIES + "/backend-test-launcher.py",
            "--version",
        ],
    ):
        return True
    if command in (
        [DEPENDENCIES + "/venv/bin/ruff", "check", "."],
        [DEPENDENCIES + "/venv/bin/python", DEPENDENCIES + "/render-check-sql.py"],
        [DEPENDENCIES + "/venv/bin/alembic", "-c", "alembic.ini", "upgrade", "head"],
        [
            DEPENDENCIES + "/venv/bin/python",
            "-m",
            "pytest",
            "--junitxml=../backend-quality.xml",
        ],
        [DEPENDENCIES + "/venv/bin/dsql-lint", DEPENDENCIES + "/rendered-search.sql"],
    ):
        return True
    if command[0] == DEPENDENCIES + "/venv/bin/dsql-lint":
        return len(command) > 1 and all(
            re.fullmatch(r"migrations/dsql/0001_initial/[a-zA-Z0-9_-]+\.sql", name)
            for name in command[1:]
        )
    if command[0] == "npm":
        return command in (
            ["npm", "run", "check"],
            ["npm", "test", "--", "--run"],
            ["npm", "run", "build"],
            ["npm", "run", "build:check"],
        )
    if command[:3] == [DEPENDENCIES + "/venv/bin/python", "-m", "pytest"]:
        return len(command) >= 4 and command[3] in {
            "backend/tests",
            "backend/tests/test_incident_regression.py",
        }
    return command[:3] == [
        DEPENDENCIES + "/frontend/node_modules/.bin/vitest",
        "run",
        "src/incident-regression.test.tsx",
    ]


def approved(command, input_data):
    executable, args = command[0], command[1:]
    if executable == "npm":
        return args == ["ci", "--ignore-scripts"]
    if executable == sys.executable:
        return args == ["-m", "venv", DEPENDENCIES + "/venv"]
    if executable == DEPENDENCIES + "/venv/bin/pip":
        return args == [
            "install",
            "--disable-pip-version-check",
            ".[test,dsql-prototype]",
        ]
    if executable == "git":
        if args[:4] == ["clone", "--no-hardlinks", "--shared", "--no-checkout"]:
            return len(args) == 6 and all(
                PurePath(value).is_absolute() for value in args[4:]
            )
        if args[:1] == ["-C"]:
            return (
                len(args) == 5
                and args[2:4] == ["archive", "--format=tar"]
                and bool(re.fullmatch(r"[0-9a-f]{40}", args[4]))
            )
        if (
            args[:5]
            != [
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "core.fsmonitor=false",
                "-C",
            ]
            or len(args) < 7
        ):
            return False
        operation = args[6:]
        if operation[:1] == ["fetch"]:
            return (
                len(operation) == 5
                and operation[1:4]
                == [
                    "--no-tags",
                    "--depth=1",
                    "https://github.com/alanlima/pawlocal.git",
                ]
                and bool(re.fullmatch(r"[0-9a-f]{40}", operation[4]))
            )
        return operation[:1] in (
            ["checkout"],
            ["rev-parse"],
            ["add"],
            ["write-tree"],
            ["commit-tree"],
        )
    if executable != "sudo":
        return False
    if args in (
        ["useradd", "--create-home", "--shell", "/bin/bash", "oncall"],
        ["-u", "oncall", "sudo", "-n", "true"],
        ["pkill", "-KILL", "-u", "oncall"],
    ):
        return True
    if args[:4] == ["-u", "oncall", "env", "-i"]:
        child = args[4:]
        allowed = {
            "PATH",
            "HOME",
            "LANG",
            "CI",
            "PYTHONPATH",
            "PAWLOCAL_TELEMETRY_ENABLED",
            "VITE_TELEMETRY_ENABLED",
        }
        while child and "=" in child[0]:
            key, value = child.pop(0).split("=", 1)
            if key in {"PAWLOCAL_DATABASE_URL", "PAWLOCAL_TEST_DATABASE_URL"}:
                if value != TEST_DATABASE_URL:
                    return False
            elif key not in allowed or not value or "\n" in value:
                return False
        return bool(child) and unprivileged(child)
    if args[:1] == ["tee"] and len(args) == 2:
        return (
            args[1] in HOME_FILES
            or args[1] == SUDOERS
            and input_data == b'Defaults env_keep += "CODEX_HOME"\n'
        )
    if args[:1] == ["chmod"] and len(args) == 3:
        return (
            (args[1] == "644" and args[2] in HOME_FILES)
            or args == ["chmod", "755", "/home/oncall"]
            or args == ["chmod", "440", SUDOERS]
        )
    if args[:2] == ["chown", "--no-dereference"]:
        return (
            len(args) == 4
            and args[2] == f"{os.getuid()}:{os.getgid()}"
            and args[3]
            in CHECK_REPORTS
            | {
                "/tmp/pawlocal-oncall-candidate",
                "/tmp/pawlocal-oncall-review.json",
            }
        )
    if args[:1] == ["chown"]:
        return (
            args == ["chown", "root:root", "/home/oncall"]
            or len(args) == 4
            and args[1] == "-R"
            and bool(re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", args[2]))
            and path(
                args[3],
                ("/tmp/pawlocal-oncall-candidate", "/tmp/pawlocal-oncall-check-work"),
            )
        )
    if args[:2] == ["install", "-d"] and len(args) == 9:
        shape = (
            args[2] == "-o"
            and args[4] == "-g"
            and args[6] == "-m"
            and args[7] in {"700", "1777"}
            and all(
                value == "oncall" or value.isdecimal() for value in (args[3], args[5])
            )
            and path(
                args[8],
                (
                    "/home/oncall/.codex",
                    DEPENDENCIES + "/frontend/node_modules/.vite",
                    DEPENDENCIES + "/frontend/node_modules/.vite-temp",
                ),
            )
        )
        if not shape:
            return False
        if args[8] == "/home/oncall/.codex":
            return os.name == "posix" and (args[3], args[5], args[7]) == (
                str(os.getuid()),
                str(os.getgid()),
                "1777",
            )
        return (args[3], args[5], args[7]) == ("oncall", "oncall", "700")
    return False


def validate(command, input_data, options=None):
    options = options or {}
    if input_data is not None and type(input_data) is not bytes:
        raise Denied("trusted bytes input required")
    environment = options.get("env")
    if environment is not None:
        if command[0] != "git" or type(environment) is not dict:
            raise Denied("only trusted git environment projection is supported")
        fixed = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
        identity = {
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_AUTHOR_DATE",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
            "GIT_COMMITTER_DATE",
        }
        for key, value in environment.items():
            if type(key) is not str or type(value) is not str:
                raise Denied("untrusted process environment")
            if key in fixed:
                allowed = value == fixed[key]
            elif key in identity:
                allowed = (
                    0 < len(value) <= 300 and "\n" not in value and "\r" not in value
                )
            else:
                allowed = not key.startswith("GIT_") and os.environ.get(key) == value
            if not allowed:
                raise Denied("process environment differs from trusted projection")
    cwd = options.get("cwd")
    if cwd is not None and not isinstance(cwd, (str, PurePath)):
        raise Denied("trusted directory path required")
    if command[:5] == ["sudo", "-u", "oncall", "env", "-i"]:
        child = command[5:]
        while child and "=" in child[0]:
            child = child[1:]
        quality = child and (
            child[0]
            in {
                DEPENDENCIES + "/venv/bin/ruff",
                DEPENDENCIES + "/venv/bin/dsql-lint",
                DEPENDENCIES + "/venv/bin/alembic",
            }
            or child
            == [
                DEPENDENCIES + "/venv/bin/python",
                DEPENDENCIES + "/render-check-sql.py",
            ]
            or child
            == [
                DEPENDENCIES + "/venv/bin/python",
                "-m",
                "pytest",
                "--junitxml=../backend-quality.xml",
            ]
        )
        if quality and str(cwd) != "/tmp/pawlocal-oncall-check-work/candidate/backend":
            raise Denied(
                "quality commands require the fixed candidate backend directory"
            )
    if command[0] == DEPENDENCIES + "/venv/bin/pip":
        temporary = os.environ.get("RUNNER_TEMP", "")
        allowed_cwd = {
            DEPENDENCIES + "/backend-source",
            str(Path(temporary) / "oncall-checks/dependency-source/backend"),
        }
        if not temporary or str(cwd) not in allowed_cwd:
            raise Denied("dependency metadata must come from trusted build source")
    if command[0] == "npm" and str(cwd) != DEPENDENCIES + "/frontend":
        raise Denied("npm install must use immutable dependency directory")
    if not approved(command, input_data):
        raise Denied("runner command family is outside the trusted finite policy")
