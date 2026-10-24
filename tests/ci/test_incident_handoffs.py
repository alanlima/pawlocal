"""Real credential-free incident handoffs; full hosted fixture is explicit opt-in."""

import difflib
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops/incident-response"))
import candidate
import checks
import deadline
import job
import process_policy

WORK = Path("/tmp/pawlocal-oncall-candidate")
REPORT = Path("/tmp/pawlocal-oncall-review.json")
CHECK_WORK = Path("/tmp/pawlocal-oncall-check-work")
DEPS = Path(process_policy.DEPENDENCIES)
FIXTURES = Path(__file__).parent / "fixtures/incident-handoff"


class HandoffTests(unittest.TestCase):
    def test_regression_quiesces_before_private_report_read_and_on_exceptions(self):
        metadata = {"deadline": time.time() + 100}
        events = []
        xml = b'<testsuites><testsuite tests="1" failures="1" errors="0"/></testsuites>'
        with (
            patch.object(
                checks, "execute", side_effect=lambda *a: events.append("execute") or 1
            ),
            patch.object(
                checks, "quiesce", side_effect=lambda: events.append("quiesce")
            ),
            patch.object(
                checks,
                "reclaim_model_output",
                side_effect=lambda *a: events.append("reclaim"),
            ),
            patch.object(
                checks,
                "safe_bytes",
                side_effect=lambda *a: events.append("read") or xml,
            ),
        ):
            self.assertTrue(
                checks.regression(
                    CHECK_WORK / "affected", "backend", metadata, DEPS, True
                )
            )
        self.assertEqual(events, ["execute", "quiesce", "reclaim", "read"])
        with (
            patch.object(checks, "execute", side_effect=TimeoutError),
            patch.object(checks, "quiesce") as stop,
            patch.object(checks, "reclaim_model_output") as reclaim,
            self.assertRaises(TimeoutError),
        ):
            checks.regression(CHECK_WORK / "affected", "backend", metadata, DEPS, True)
        stop.assert_called_once()
        reclaim.assert_not_called()

    def test_all_fixed_report_commands_validate_but_arbitrary_targets_do_not(self):
        with (
            patch.multiple(os, getuid=lambda: 123, getgid=lambda: 456, create=True),
            patch.object(deadline.subprocess, "Popen") as launch,
        ):
            launch.return_value.communicate.return_value = (None, None)
            launch.return_value.returncode = 0
            for path in sorted(process_policy.CHECK_REPORTS):
                deadline.run(["sudo", "chown", "--no-dereference", "123:456", path])
            self.assertEqual(launch.call_count, 6)
            launch.reset_mock()
            for recipient, path in (
                ("999:456", min(process_policy.CHECK_REPORTS)),
                (
                    "123:456",
                    "/tmp/pawlocal-oncall-check-work/other/backend-regression.xml",
                ),
                (
                    "123:456",
                    "/tmp/pawlocal-oncall-check-work/affected/../backend-regression.xml",
                ),
            ):
                with self.subTest(path=path), self.assertRaises(candidate.Denied):
                    deadline.run(["sudo", "chown", "--no-dereference", recipient, path])
            launch.assert_not_called()

    def test_report_ancestors_links_bounds_and_recipients_fail_before_chown(self):
        path = CHECK_WORK / "affected/backend-regression.xml"
        directory = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o750, st_uid=123, st_gid=456
        )
        container = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o755, st_uid=123, st_gid=456
        )
        leaf = types.SimpleNamespace(
            st_mode=stat.S_IFREG | 0o600,
            st_uid=789,
            st_gid=789,
            st_size=100,
            st_nlink=1,
        )
        baseline = {path: leaf, path.parent: directory, path.parent.parent: container}
        changes = (
            (path, vars(leaf) | {"st_mode": stat.S_IFLNK | 0o777}),
            (path, vars(leaf) | {"st_mode": stat.S_IFIFO | 0o600}),
            (path, vars(leaf) | {"st_size": 1024 * 1024 + 1}),
            (path, vars(leaf) | {"st_nlink": 2}),
            (path.parent, vars(directory) | {"st_mode": stat.S_IFLNK | 0o777}),
            (path.parent.parent, vars(container) | {"st_mode": stat.S_IFLNK | 0o777}),
            (path.parent.parent, vars(container) | {"st_uid": 789}),
            (path.parent.parent, vars(container) | {"st_mode": stat.S_IFDIR | 0o777}),
        )
        with (
            patch.multiple(os, getuid=lambda: 123, getgid=lambda: 456, create=True),
            patch.object(job, "run") as launch,
        ):
            for changed, values in changes:
                entries = baseline | {changed: types.SimpleNamespace(**values)}
                with (
                    patch.object(
                        Path, "lstat", new=lambda name, entries=entries: entries[name]
                    ),
                    self.subTest(changed=changed, values=values),
                    self.assertRaises(candidate.Denied),
                ):
                    job.reclaim_model_output(path)
            with (
                patch.object(Path, "lstat", side_effect=FileNotFoundError),
                self.assertRaises(candidate.Denied),
            ):
                job.reclaim_model_output(path)
            launch.assert_not_called()

    def test_cache_install_maps_distinct_numeric_user_and_group(self):
        model = types.SimpleNamespace(pw_uid=12001, pw_gid=12002)
        with patch.object(subprocess, "Popen") as process:
            adapter = FixtureLaunches(Path("trusted"), "a" * 40, Path("home"), model)
            command = [
                "sudo",
                "install",
                "-d",
                "-o",
                "oncall",
                "-g",
                "oncall",
                "-m",
                "700",
                str(DEPS / "frontend/node_modules/.vite"),
            ]
            adapter(command, start_new_session=True)
            process.assert_called_once_with(
                [
                    "sudo",
                    "install",
                    "-d",
                    "-o",
                    "12001",
                    "-g",
                    "12002",
                    "-m",
                    "700",
                    command[-1],
                ],
                start_new_session=True,
            )
            self.assertEqual((command[4], command[6]), ("oncall", "oncall"))

    def test_private_report_umask_is_set_after_sudo_before_real_command(self):
        model = types.SimpleNamespace(pw_uid=12001, pw_gid=12002)
        with patch.object(subprocess, "Popen") as process:
            adapter = FixtureLaunches(Path("trusted"), "a" * 40, Path("home"), model)
            command = ["sudo", "-u", "oncall", "env", "-i", "PATH=/bin", "pytest"]
            adapter(command, start_new_session=True)
            actual = process.call_args.args[0]
            self.assertEqual(actual[:3], ["sudo", "-u", "nobody"])
            self.assertEqual(actual[3:5], [sys.executable, "-c"])
            self.assertIn("os.umask(0o077)", actual[5])
            self.assertIn("os.execvp(sys.argv[1],sys.argv[1:])", actual[5])
            self.assertEqual(actual[6:], command[3:])
            self.assertNotIn("preexec_fn", process.call_args.kwargs)
            self.assertEqual(command[2], "oncall")

    @unittest.skipUnless(
        sys.platform == "linux"
        and os.environ.get("PAWLOCAL_INCIDENT_HANDOFF_FIXTURE") == "1",
        "Complete fixture runs explicitly on hosted Linux after Node/Python tools",
    )
    def test_complete_real_pipeline(self):
        complete_fixture(self)


def command(argv, **kwargs):
    """Fixture setup only; production stages use the actual deadline wrapper."""
    return subprocess.run(argv, check=True, **kwargs)


def privileged_cleanup(path, expected):
    # Remove only the exact inode this fixture created, never a survivor/user path.
    if not path.exists() and not path.is_symlink():
        return
    subprocess.run(
        [
            "sudo",
            "-n",
            sys.executable,
            str(Path(__file__).resolve()),
            "--cleanup",
            str(path),
            str(expected.st_dev),
            str(expected.st_ino),
        ],
        check=True,
        env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
    )


class FixtureLaunches:
    """Adapters run AFTER real policy validation; no test/result modification.

    A local Git transport avoids network/auth for the synthetic pinned commit.
    oncall maps to the existing nobody UID, HOME has equivalent readonly modes,
    and quiesce kills only recorded fixture model process groups, never all nobody.
    Tests/compilers/reporters themselves execute unchanged and credential-free.
    """

    def __init__(self, trusted, base_sha, home, model):
        self.original = subprocess.Popen
        self.trusted, self.base_sha, self.home = trusted, base_sha, home
        self.model = model
        self.groups = []
        self.events = []

    def __call__(self, argv, **options):
        argv = list(argv)
        if argv == ["sudo", "pkill", "-KILL", "-u", "oncall"]:
            self.events.append("quiesce")
            groups = list(self.groups)
            self.groups.clear()
            # Only PIDs recorded from this fixture's new-session model launches.
            cleanup = (
                "import os,signal\nfor group in "
                + repr(groups)
                + ":\n try: os.killpg(group,signal.SIGKILL)\n except ProcessLookupError: pass\n"
            )
            return self.original(
                ["sudo", "-n", sys.executable, "-c", cleanup], **options
            )
        if argv[:3] == ["sudo", "install", "-d"]:
            # Ubuntu nobody's primary group is nogroup, not nobody. Preserve
            # ownership semantics using its actual separate numeric identities.
            for option, identity in (
                ("-o", self.model.pw_uid),
                ("-g", self.model.pw_gid),
            ):
                index = argv.index(option) + 1
                if argv[index] == "oncall":
                    argv[index] = str(identity)
        if argv[:3] == ["sudo", "chown", "--no-dereference"]:
            self.events.append("reclaim:" + argv[-1])
        if argv[:3] == ["sudo", "-u", "oncall"]:
            self.events.append("model:" + argv[-1])
            argv[2] = "nobody"
            argv = [
                "HOME=" + str(self.home) if value == "HOME=/home/oncall" else value
                for value in argv
            ]
            # sudo resets an inherited umask. Set it as the model user before
            # exec of the unchanged env-i command and real test/compiler.
            argv[3:3] = [
                sys.executable,
                "-c",
                "import os,sys; os.umask(0o077); os.execvp(sys.argv[1],sys.argv[1:])",
            ]
            process = self.original(argv, **options)
            self.groups.append(process.pid)
            return process
        if argv[0] == "git" and "fetch" in argv:
            return self.original(
                [
                    "git",
                    "-C",
                    str(self.trusted),
                    "rev-parse",
                    "--verify",
                    self.base_sha,
                ],
                **options,
            )
        return self.original(argv, **options)


def complete_fixture(test):
    import pwd

    test.assertNotEqual(os.getuid(), 0, "Fixture must exercise the real runner UID")
    command(["sudo", "-n", "true"])
    model = pwd.getpwnam("nobody")
    test.assertNotEqual(model.pw_uid, os.getuid())
    created = {}
    for path in (WORK, REPORT, CHECK_WORK, DEPS):
        test.assertFalse(
            path.exists() or path.is_symlink(),
            "Refusing existing fixed fixture path " + str(path),
        )
    with tempfile.TemporaryDirectory(prefix="pawlocal-full-handoff-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        trusted = root / "trusted"
        trusted.mkdir(mode=0o700)
        home = root / "model-home"
        home.mkdir(mode=0o755)
        runner_temp = root / "runner-temp"
        runner_temp.mkdir()
        output = root / "outputs.txt"
        output.touch()
        # Current repository code and lockfiles; freeze only the historical real
        # rating bug so this regression remains reproducible after its repair.
        archive = subprocess.run(
            ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(trusted, filter="data")
        before = (FIXTURES / "places-before.py").read_bytes()
        (trusted / "backend/pawlocal/application/places.py").write_bytes(before)
        frontend_test = (FIXTURES / "frontend-regression.test.tsx").read_bytes()
        (trusted / "frontend/src/incident-regression.test.tsx").write_bytes(
            frontend_test
        )
        command(
            ["git", "init", "--initial-branch=fixture", str(trusted)],
            stdout=subprocess.DEVNULL,
        )
        command(["git", "-C", str(trusted), "add", "."])
        command(
            [
                "git",
                "-C",
                str(trusted),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-m",
                "Historical rating regression fixture",
            ],
            stdout=subprocess.DEVNULL,
        )
        base_sha = subprocess.run(
            ["git", "-C", str(trusted), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        fixed = before.replace(
            b"key=lambda place: place.average_rating,",
            b"key=lambda place: place.average_rating if place.average_rating is not None else float('-inf'),",
        )
        test.assertNotEqual(before, fixed)
        regression = (FIXTURES / "backend-regression.py").read_bytes()
        edits = {
            "backend/pawlocal/application/places.py": fixed,
            "backend/tests/test_incident_regression.py": regression,
        }
        metadata = {
            "base_sha": base_sha,
            "affected_sha": base_sha,
            "run_id": "919191",
            "deadline": int(time.time()) + 1200,
            "alert": {"incident_key": "b" * 64},
        }
        trusted_root = runner_temp / "oncall-trusted"
        trusted_root.mkdir(mode=0o700)
        launches = FixtureLaunches(trusted, base_sha, home, model)
        values = {
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_WORKSPACE": str(trusted),
            "GITHUB_OUTPUT": str(output),
            "INCIDENT_DEADLINE": str(metadata["deadline"]),
            "ADMISSION_SHA256": "a" * 64,
        }
        previous_deadline = deadline.DEADLINE
        mkdir = Path.mkdir

        def record_created(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            if path in (CHECK_WORK, DEPS):
                created[path] = path.lstat()
            return result

        try:
            with (
                patch.object(Path, "mkdir", new=record_created),
                patch.dict(os.environ, values),
                patch.object(deadline.subprocess, "Popen", side_effect=launches),
            ):
                job.archive(trusted, base_sha, trusted_root / "baseline")
                (trusted_root / "metadata.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
                shutil.copytree(trusted_root / "baseline", WORK)
                candidate.materialize(edits, WORK)
                created[WORK] = WORK.lstat()
                job.run(
                    [
                        "sudo",
                        "chown",
                        "-R",
                        f"{model.pw_uid}:{model.pw_gid}",
                        str(WORK),
                    ],
                    check=True,
                )
                # Reproduce the original failure through the actual execute /
                # deadline / policy path: runner chdir fails before sudo/model.
                with test.assertRaises(PermissionError):
                    checks.execute(
                        [
                            str(DEPS / "venv/bin/python"),
                            "-m",
                            "pytest",
                            "backend/tests/test_incident_regression.py",
                        ],
                        WORK,
                        metadata,
                        {"PATH": os.environ["PATH"]},
                    )
                # This is the actual seal, not a transport/helper approximation.
                job.seal()
                raw = (trusted_root / "export/candidate.json").read_bytes()
                test.assertEqual(candidate.load(raw, metadata), edits)
                (trusted_root / "candidate.json").write_bytes(raw)
                # Separate jobs never retain the prior model workspace.
                privileged_cleanup(WORK, created.pop(WORK))
                with (
                    patch.dict(os.environ, {"CANDIDATE_SHA256": candidate.digest(raw)}),
                    patch.object(
                        checks,
                        "context",
                        return_value=(metadata, types.SimpleNamespace(digest="c" * 64)),
                    ),
                    patch.object(checks, "uid", return_value=model),
                    patch.object(
                        checks, "download", return_value={"candidate.json": raw}
                    ),
                ):
                    checks.main()
                for path in (CHECK_WORK, DEPS):
                    created[path] = path.lstat()
                receipt_raw = (
                    runner_temp / "oncall-checks/export/checks.json"
                ).read_bytes()
                receipt = json.loads(receipt_raw)
                test.assertTrue(
                    all(
                        receipt[key]
                        for key in (
                            "affected_reproduced",
                            "main_reproduced",
                            "candidate_passed",
                        )
                    )
                )
                test.assertEqual(receipt["layers"], ["backend"])
                for name in ("affected", "main", "candidate"):
                    tree = CHECK_WORK / name
                    info = tree.lstat()
                    test.assertEqual(
                        (stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid),
                        (0o750, model.pw_uid, os.getgid()),
                    )
                    test.assertFalse(os.access(tree, os.W_OK))
                    expected = fixed if name == "candidate" else before
                    test.assertEqual(
                        candidate.safe_bytes(
                            tree, "backend/pawlocal/application/places.py", 100000
                        ),
                        expected,
                    )
                    report = tree / "backend-regression.xml"
                    test.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
                    test.assertEqual(report.stat().st_uid, os.getuid())
                    # Exercise actual frontend Vitest JSON output on all roots.
                    test.assertTrue(
                        checks.regression(tree, "frontend", metadata, DEPS, False)
                    )
                    test.assertEqual(
                        stat.S_IMODE(
                            (tree / "frontend-regression.json").stat().st_mode
                        ),
                        0o600,
                    )
                environment = {
                    "PATH": str(DEPS / "venv/bin") + ":" + os.environ["PATH"]
                }
                for argv in (
                    ["npm", "run", "check"],
                    ["npm", "test", "--", "--run"],
                    ["npm", "run", "build:check"],
                ):
                    try:
                        test.assertEqual(
                            checks.execute(
                                argv,
                                CHECK_WORK / "candidate/frontend",
                                metadata,
                                environment,
                            ),
                            0,
                        )
                    finally:
                        job.quiesce()
                test.assertTrue(
                    (CHECK_WORK / "candidate/frontend/dist/index.html").is_file()
                )
                # Trusted archives/Git metadata remain private, dependency targets
                # are not model-owned through the node_modules symlink.
                for path in (
                    trusted_root / "baseline",
                    runner_temp / "oncall-checks",
                    runner_temp / "oncall-checks/dependency-source",
                ):
                    test.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                test.assertEqual(
                    (DEPS / "frontend/node_modules").stat().st_uid, os.getuid()
                )
                real_negative_handoffs(test, root, model, launches)
                patch_text = "".join(
                    difflib.unified_diff(
                        before.decode().splitlines(True),
                        fixed.decode().splitlines(True),
                        fromfile="a/backend/pawlocal/application/places.py",
                        tofile="b/backend/pawlocal/application/places.py",
                    )
                )
                (home / "candidate.diff").write_text(patch_text, encoding="utf-8")
                private = (
                    runner_temp
                    / "oncall-checks/dependency-source/backend/pyproject.toml"
                )
                probe = (
                    "import os,pathlib;assert os.getuid()=="
                    + str(model.pw_uid)
                    + ";assert os.getgid()=="
                    + str(model.pw_gid)
                    + ";assert not any('TOKEN' in k or 'API_KEY' in k for k in os.environ);assert pathlib.Path("
                    + repr(str(home / "candidate.diff"))
                    + ").read_text();\ntry:pathlib.Path("
                    + repr(str(private))
                    + ").read_bytes()\nexcept PermissionError:pass\nelse:raise AssertionError('private archive exposed')\n"
                )
                command(
                    [
                        "sudo",
                        "-u",
                        "nobody",
                        "env",
                        "-i",
                        "PATH=" + os.environ["PATH"],
                        sys.executable,
                        "-c",
                        probe,
                    ]
                )
                # Fresh reviewer workspace; identical immutable candidate bytes.
                shutil.copytree(trusted_root / "baseline", WORK)
                candidate.materialize(edits, WORK)
                created[WORK] = WORK.lstat()
                job.run(
                    [
                        "sudo",
                        "chown",
                        "-R",
                        f"{model.pw_uid}:{model.pw_gid}",
                        str(WORK),
                    ],
                    check=True,
                )
                review = {
                    "verdict": "pass",
                    "candidate_sha": receipt["candidate_sha"],
                    "findings": [],
                }
                REPORT.write_text(json.dumps(review), encoding="utf-8")
                REPORT.chmod(0o600)
                created[REPORT] = REPORT.lstat()
                command(
                    [
                        "sudo",
                        "chown",
                        "--no-dereference",
                        f"{model.pw_uid}:{model.pw_gid}",
                        str(REPORT),
                    ]
                )
                with patch.dict(
                    os.environ,
                    {
                        "PINNED_CANDIDATE_SHA": receipt["candidate_sha"],
                        "CANDIDATE_SHA256": candidate.digest(raw),
                        "CHECKS_SHA256": candidate.digest(receipt_raw),
                    },
                ):
                    job.review_seal()
                    binding = json.loads(
                        (trusted_root / "review-export/review.json").read_bytes()
                    )
                    test.assertEqual(binding["candidate_sha"], receipt["candidate_sha"])
                    test.assertEqual(
                        binding["checks_sha256"], candidate.digest(receipt_raw)
                    )
                    test.assertEqual(
                        candidate.files(WORK),
                        candidate.files(trusted_root / "baseline"),
                    )
                # A distinct negative case must reject reviewer source mutation;
                # it cannot change the previously produced valid receipt.
                job.run(
                    [
                        "sudo",
                        "chown",
                        "-R",
                        f"{model.pw_uid}:{model.pw_gid}",
                        str(WORK),
                    ],
                    check=True,
                )
                model_action(
                    "from pathlib import Path;p=Path("
                    + repr(str(WORK / "backend/pawlocal/application/places.py"))
                    + ");p.write_bytes(p.read_bytes()+"
                    + repr(b"\n# reviewer mutation\n")
                    + ")"
                )
                with (
                    patch.dict(
                        os.environ,
                        {
                            "PINNED_CANDIDATE_SHA": receipt["candidate_sha"],
                            "CANDIDATE_SHA256": candidate.digest(raw),
                            "CHECKS_SHA256": candidate.digest(receipt_raw),
                        },
                    ),
                    test.assertRaisesRegex(
                        candidate.Denied, "reviewer modified candidate"
                    ),
                ):
                    job.review_seal()
                test.assertTrue(any(event == "quiesce" for event in launches.events))
                print(
                    "Real seal -> affected/main fail -> candidate/full backend pass -> real Vitest/frontend compile -> fresh review binding verified"
                )
        finally:
            deadline.DEADLINE = previous_deadline
            signal.setitimer(signal.ITIMER_REAL, 0)
            if launches.groups:
                with patch.object(deadline.subprocess, "Popen", side_effect=launches):
                    job.quiesce()
            # Only inodes recorded at our own creation sites are eligible.
            for path, info in reversed(list(created.items())):
                privileged_cleanup(path, info)


def model_action(code):
    command(
        [
            "sudo",
            "-u",
            "nobody",
            "env",
            "-i",
            "PATH=" + os.environ["PATH"],
            sys.executable,
            "-c",
            code,
        ],
    )


def real_negative_handoffs(test, root, model, launches):
    source = CHECK_WORK / "affected"
    report = source / "backend-regression.xml"
    saved = source / "backend-regression.xml.saved"
    model_action(
        "from pathlib import Path;Path("
        + repr(str(report))
        + ").rename("
        + repr(str(saved))
        + ")"
    )
    target = source / "fixture-target"
    try:
        for kind in ("missing", "symlink", "hardlink", "oversized"):
            setup = (
                "from pathlib import Path;import os;p=Path("
                + repr(str(report))
                + ");t=Path("
                + repr(str(target))
                + ");"
            )
            if kind == "symlink":
                setup += "t.write_bytes(b'fixture');t.chmod(0o600);p.symlink_to(t)"
            elif kind == "hardlink":
                setup += "t.write_bytes(b'fixture');t.chmod(0o600);os.link(t,p)"
            elif kind == "oversized":
                setup += "p.write_bytes(b'x'*(1024*1024+1));p.chmod(0o600)"
            if kind != "missing":
                model_action(setup)
            before_events = len(launches.events)
            with test.assertRaises(candidate.Denied):
                job.reclaim_model_output(report)
            test.assertFalse(
                any(
                    event.startswith("reclaim:")
                    for event in launches.events[before_events:]
                )
            )
            if target.exists():
                test.assertEqual(target.lstat().st_uid, model.pw_uid)
                test.assertEqual(stat.S_IMODE(target.lstat().st_mode), 0o600)
            model_action(
                "from pathlib import Path;p=Path("
                + repr(str(report))
                + ");p.unlink(missing_ok=True);Path("
                + repr(str(target))
                + ").unlink(missing_ok=True)"
            )
    finally:
        model_action(
            "from pathlib import Path;Path("
            + repr(str(saved))
            + ").rename("
            + repr(str(report))
            + ")"
        )
    # A symlink in a fixed ancestor must not redirect privileged chown.
    moved = root / "saved-affected"
    source.rename(moved)
    outside = root / "outside-reports"
    outside.mkdir(mode=0o750)
    outside_report = outside / report.name
    outside_report.write_bytes(b"fixture")
    outside_report.chmod(0o600)
    command(["sudo", "chown", f"{model.pw_uid}:{model.pw_gid}", str(outside_report)])
    source.symlink_to(outside, target_is_directory=True)
    try:
        before = outside_report.lstat()
        before_events = len(launches.events)
        with test.assertRaisesRegex(candidate.Denied, "ancestors"):
            job.reclaim_model_output(report)
        after = outside_report.lstat()
        test.assertEqual((before.st_uid, before.st_mode), (after.st_uid, after.st_mode))
        test.assertFalse(
            any(
                event.startswith("reclaim:")
                for event in launches.events[before_events:]
            )
        )
    finally:
        source.unlink()
        moved.rename(source)
    private = source / "backend"
    model_action(
        "from pathlib import Path;Path(" + repr(str(private)) + ").chmod(0o700)"
    )
    try:
        with test.assertRaisesRegex(candidate.Denied, "traversal failed"):
            candidate.files(source)
    finally:
        model_action(
            "from pathlib import Path;Path(" + repr(str(private)) + ").chmod(0o755)"
        )


def cleanup_fixed(path, device, inode):
    if os.getuid() != 0 or path not in (WORK, REPORT, CHECK_WORK, DEPS):
        raise RuntimeError("fixed fixture cleanup only")
    info = path.lstat()
    if (info.st_dev, info.st_ino) != (device, inode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError("fixture inode changed; refusing cleanup")
    if stat.S_ISDIR(info.st_mode):
        shutil.rmtree(path)
    elif path == REPORT and stat.S_ISREG(info.st_mode):
        path.unlink()
    else:
        raise RuntimeError("unexpected fixture cleanup type")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--cleanup"]:
        cleanup_fixed(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
    else:
        unittest.main()
