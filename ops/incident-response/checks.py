"""Fresh, credential-free regression checks with trusted test entry points."""

import json
import os
import shutil
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from candidate import (
    bind_candidate,
    digest,
    git,
    load,
    materialize,
    safe_bytes,
)
from deadline import arm, run
from job import (
    archive,
    context,
    download,
    quiesce,
    reclaim_model_output,
    remaining,
    uid,
    writable_tool_caches,
)
from process_policy import TEST_DATABASE_URL
from quota import Denied


def execute(command, cwd, metadata, environment):
    remaining(metadata)
    # No repository/query/App/API credentials or Actions runtime capabilities.
    values = {
        "PATH": environment["PATH"],
        "HOME": "/home/oncall",
        "LANG": "C.UTF-8",
        "CI": "true",
        "PYTHONPATH": str(cwd if cwd.name == "backend" else cwd / "backend"),
        "PAWLOCAL_TELEMETRY_ENABLED": "false",
        "VITE_TELEMETRY_ENABLED": "false",
    }
    if environment.get("database"):
        values["PAWLOCAL_DATABASE_URL"] = TEST_DATABASE_URL
        values["PAWLOCAL_TEST_DATABASE_URL"] = TEST_DATABASE_URL
    return run(
        [
            "sudo",
            "-u",
            "oncall",
            "env",
            "-i",
            *[f"{key}={value}" for key, value in values.items()],
            *command,
        ],
        cwd=cwd,
        timeout=remaining(metadata),
        check=False,
    ).returncode


def share_check_source(destination, identity):
    allowed = {
        Path("/tmp/pawlocal-oncall-check-work") / name
        for name in ("affected", "main", "candidate")
    }
    info = destination.lstat()
    if (
        destination not in allowed
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
    ):
        raise Denied("trusted fixed check source required")
    # Tests keep their existing model UID privileges; only the runner group gains
    # traversal/read access. The source root is never world accessible.
    destination.chmod(0o750)
    run(
        ["sudo", "chown", "-R", f"{identity.pw_uid}:{os.getgid()}", str(destination)],
        check=True,
    )


def regression(root, layer, metadata, dependencies, expect_failure):
    output = root / (
        "backend-regression.xml" if layer == "backend" else "frontend-regression.json"
    )
    if layer == "backend":
        command = [
            str(dependencies / "venv/bin/python"),
            "-m",
            "pytest",
            "backend/tests/test_incident_regression.py",
            "--junitxml=" + str(output),
        ]
    else:
        command = [
            str(dependencies / "frontend/node_modules/.bin/vitest"),
            "run",
            "src/incident-regression.test.tsx",
            "--reporter=default",
            "--reporter=json",
            "--outputFile=" + str(output),
        ]
    cwd = root if layer == "backend" else root / "frontend"
    environment = {"PATH": str(dependencies / "venv/bin") + ":" + os.environ["PATH"]}
    try:
        code = execute(command, cwd, metadata, environment)
    finally:
        quiesce()
    reclaim_model_output(output)
    raw = safe_bytes(root, output.name, 1024 * 1024)
    if layer == "backend":
        document = ET.fromstring(raw)
        suites = list(document.iter("testsuite"))
        count = sum(int(suite.get("tests", "0")) for suite in suites)
        failures = sum(int(suite.get("failures", "0")) for suite in suites)
        errors = sum(int(suite.get("errors", "0")) for suite in suites)
        if count < 1 or errors:
            raise Denied("regression did not collect cleanly")
    else:
        document = json.loads(raw)
        count = document.get("numTotalTests", 0)
        failures = document.get("numFailedTests", 0)
        if count < 1 or document.get("numRuntimeErrorTestSuites", 0):
            raise Denied("frontend regression did not collect cleanly")
    if code == 0 and failures == 0:
        return not expect_failure
    if code == 1 and failures > 0:
        return expect_failure
    raise Denied("regression uncertainty")


def backend_quality(source, metadata, dependencies):
    """Required backend quality commands against candidate bytes, never runner credentials."""
    backend = source / "backend"
    environment = {
        "PATH": str(dependencies / "venv/bin") + ":" + os.environ["PATH"],
        "database": True,
    }

    def step(command):
        try:
            result = execute(command, backend, metadata, environment)
        finally:
            quiesce()
        if result:
            raise Denied(
                "required backend quality command failed: " + Path(command[0]).name
            )

    step([str(dependencies / "venv/bin/ruff"), "check", "."])
    sql = sorted(
        path.relative_to(backend).as_posix()
        for path in (backend / "migrations/dsql/0001_initial").glob("*.sql")
    )
    if not sql:
        raise Denied("immutable baseline SQL is missing")
    step([str(dependencies / "venv/bin/dsql-lint"), *sql])
    step(
        [
            str(dependencies / "venv/bin/python"),
            str(dependencies / "render-check-sql.py"),
        ]
    )
    rendered_path = source / "backend-search.sql"
    reclaim_model_output(rendered_path)
    rendered = safe_bytes(source, rendered_path.name, 1024 * 1024)
    if not rendered:
        raise Denied("rendered SQL is empty")
    output = dependencies / "rendered-search.sql"
    descriptor = os.open(
        output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(rendered)
    output.chmod(0o644)
    step([str(dependencies / "venv/bin/dsql-lint"), str(output)])
    step(
        [str(dependencies / "venv/bin/alembic"), "-c", "alembic.ini", "upgrade", "head"]
    )
    step(
        [
            str(dependencies / "venv/bin/python"),
            "-m",
            "pytest",
            "--junitxml=../backend-quality.xml",
        ]
    )
    report = source / "backend-quality.xml"
    reclaim_model_output(report)
    suite = ET.fromstring(safe_bytes(source, report.name, 1024 * 1024))
    cases = list(suite.iter("testcase"))
    integrations = {
        "test_postgres_repositories_constraints_and_records_survive_new_sessions",
        "test_0006_quarantines_legacy_rows_and_downgrade_restores_them",
        "test_0007_backfills_facilities_in_order_and_handles_empty_arrays",
    }
    actual = {
        case.get("name")
        for case in cases
        if not any(
            case.find(tag) is not None for tag in ("skipped", "failure", "error")
        )
    }
    if not integrations <= actual or any(list(case) for case in cases):
        raise Denied(
            "complete backend quality tests including PostgreSQL must pass without skips"
        )
    return {"tests": len(cases), "postgres_integration_tests": len(integrations)}


def main():
    arm(os.environ["INCIDENT_DEADLINE"])
    metadata, profile = context()
    identity = uid()
    trusted = Path(os.environ["GITHUB_WORKSPACE"])
    root = Path(os.environ["RUNNER_TEMP"]) / "oncall-checks"
    root.mkdir(mode=0o700)
    values = download("oncall-candidate-" + metadata["run_id"], {"candidate.json"})
    raw = values["candidate.json"]
    if digest(raw) != os.environ.get("CANDIDATE_SHA256"):
        raise Denied("candidate transport differs")
    content = load(raw, metadata)
    layers = [
        name
        for name in ("backend", "frontend")
        if any(path.startswith(f"{name}/") for path in content)
    ]
    # Clone only trusted metadata, with no agent-controlled .git/config/hooks.
    candidate = root / "git-candidate"
    git(
        trusted,
        "fetch",
        "--no-tags",
        "--depth=1",
        "https://github.com/alanlima/pawlocal.git",
        metadata["base_sha"],
    )
    run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            "--shared",
            "--no-checkout",
            str(trusted),
            str(candidate),
        ],
        check=True,
    )
    git(candidate, "checkout", "--detach", metadata["base_sha"])
    binding = bind_candidate(candidate, content, metadata, digest(raw))
    if (
        os.environ.get("PINNED_CANDIDATE_SHA")
        and binding["candidate_sha"] != os.environ["PINNED_CANDIDATE_SHA"]
    ):
        raise Denied("fresh review candidate differs")
    dependencies = Path("/tmp/pawlocal-oncall-dependencies")
    if dependencies.exists():
        raise Denied("unexpected dependency survivor")
    dependencies.mkdir(mode=0o755)
    dependency_source = root / "dependency-source"
    archive(trusted, metadata["base_sha"], dependency_source)
    run(
        [sys.executable, "-m", "venv", str(dependencies / "venv")],
        check=True,
        timeout=remaining(metadata),
    )
    # Install from immutable main metadata, before running candidate code.
    run(
        [
            str(dependencies / "venv/bin/pip"),
            "install",
            "--disable-pip-version-check",
            ".[test,dsql-prototype]",
        ],
        cwd=dependency_source / "backend",
        check=True,
        timeout=remaining(metadata),
    )
    shutil.copytree(
        dependency_source / "frontend",
        dependencies / "frontend",
        ignore=shutil.ignore_patterns("node_modules", "dist"),
    )
    run(
        ["npm", "ci", "--ignore-scripts"],
        cwd=dependencies / "frontend",
        check=True,
        timeout=remaining(metadata),
    )
    renderer = dependencies / "render-check-sql.py"
    shutil.copyfile(trusted / "ops/incident-response/render-check-sql.py", renderer)
    renderer.chmod(0o444)
    writable_tool_caches(dependencies)
    work = Path("/tmp/pawlocal-oncall-check-work")
    work.mkdir(mode=0o755)
    sources = {}
    for name, sha in (
        ("affected", metadata["affected_sha"]),
        ("main", metadata["base_sha"]),
        ("candidate", metadata["base_sha"]),
    ):
        destination = work / name
        archive(trusted, sha, destination)
        if name == "candidate":
            materialize(content, destination)
        else:
            regression_files = {
                key: value
                for key, value in content.items()
                if key
                in {
                    "backend/tests/test_incident_regression.py",
                    "frontend/src/incident-regression.test.tsx",
                }
            }
            materialize(regression_files, destination)
        (destination / "frontend/node_modules").symlink_to(
            dependencies / "frontend/node_modules", target_is_directory=True
        )
        share_check_source(destination, identity)
        sources[name] = destination
    try:
        quality = (
            backend_quality(sources["candidate"], metadata, dependencies)
            if "backend" in layers
            else None
        )
        for layer in layers:
            if not regression(sources["affected"], layer, metadata, dependencies, True):
                raise Denied("affected release did not reproduce")
            if not regression(sources["main"], layer, metadata, dependencies, True):
                with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                    output.write("eligible=false\n")
                return
            if not regression(
                sources["candidate"], layer, metadata, dependencies, False
            ):
                raise Denied("candidate regression failed")
        environment = {
            "PATH": str(dependencies / "venv/bin") + ":" + os.environ["PATH"]
        }
        if "frontend" in layers:
            for command in (
                ["npm", "run", "check"],
                ["npm", "test", "--", "--run"],
                ["npm", "run", "build:check"],
            ):
                if execute(
                    command, sources["candidate"] / "frontend", metadata, environment
                ):
                    raise Denied("frontend checks failed")
    finally:
        quiesce()
    remaining(metadata)
    report = binding | {
        "run_id": metadata["run_id"],
        "admission_sha256": os.environ["ADMISSION_SHA256"],
        "layers": layers,
        "affected_reproduced": True,
        "main_reproduced": True,
        "candidate_passed": True,
        "backend_quality": quality,
        "profile": profile.digest,
    }
    output = root / "export"
    output.mkdir(mode=0o700)
    raw = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    (output / "checks.json").write_bytes(raw)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(
            f"eligible=true\ncandidate_sha={binding['candidate_sha']}\nchecks_sha256={digest(raw)}\n"
        )


if __name__ == "__main__":
    main()
