"""Fresh, credential-free regression checks with trusted test entry points."""

import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from candidate import BACKEND, FRONTEND, bind_candidate, digest, git, load, materialize
from deadline import arm, run
from job import archive, context, download, quiesce, remaining, uid
from quota import Denied


def execute(command, cwd, metadata, environment):
    remaining(metadata)
    # No repository/query/App/API credentials or Actions runtime capabilities.
    values = {
        "PATH": environment["PATH"],
        "HOME": "/home/oncall",
        "LANG": "C.UTF-8",
        "CI": "true",
        "PYTHONPATH": str(cwd / "backend"),
        "PAWLOCAL_TELEMETRY_ENABLED": "false",
        "VITE_TELEMETRY_ENABLED": "false",
    }
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
    code = execute(command, cwd, metadata, environment)
    if layer == "backend":
        document = ET.parse(output).getroot()
        suites = list(document.iter("testsuite"))
        count = sum(int(suite.get("tests", "0")) for suite in suites)
        failures = sum(int(suite.get("failures", "0")) for suite in suites)
        errors = sum(int(suite.get("errors", "0")) for suite in suites)
        if count < 1 or errors:
            raise Denied("regression did not collect cleanly")
    else:
        document = json.loads(output.read_text())
        count = document.get("numTotalTests", 0)
        failures = document.get("numFailedTests", 0)
        if count < 1 or document.get("numRuntimeErrorTestSuites", 0):
            raise Denied("frontend regression did not collect cleanly")
    if code == 0 and failures == 0:
        return not expect_failure
    if code == 1 and failures > 0:
        return expect_failure
    raise Denied("regression uncertainty")


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
        for name, paths in (("backend", BACKEND), ("frontend", FRONTEND))
        if set(content) & paths
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
            ".[test]",
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
        run(
            [
                "sudo",
                "chown",
                "-R",
                f"{identity.pw_uid}:{identity.pw_gid}",
                str(destination),
            ],
            check=True,
        )
        sources[name] = destination
    try:
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
        if "backend" in layers and execute(
            [
                str(dependencies / "venv/bin/python"),
                "-m",
                "pytest",
                "backend/tests",
                "-m",
                "not integration",
            ],
            sources["candidate"],
            metadata,
            environment,
        ):
            raise Denied("backend checks failed")
        if "frontend" in layers:
            for command in (
                ["npm", "run", "check"],
                ["npm", "test", "--", "--run"],
                ["npm", "run", "build"],
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
