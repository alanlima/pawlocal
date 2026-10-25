import os
from unittest.mock import patch
"""Trusted readback ownership boundary, including real distinct Linux UIDs."""

import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops/incident-response"))
import candidate
import deadline
import job

WORK = Path("/tmp/pawlocal-oncall-candidate")
REPORT = Path("/tmp/pawlocal-oncall-review.json")


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class ReadbackTests(unittest.TestCase):
    def identity(self):
        return patch.multiple(os, getuid=lambda: 123, getgid=lambda: 456, create=True)

    def test_finite_policy_requires_exact_recipient_paths_and_nonrecursive_option(self):
        command = ["sudo", "chown", "--no-dereference", "123:456", WORK.as_posix()]
        with self.identity(), patch.object(deadline.subprocess, "Popen") as launch:
            launch.return_value.communicate.return_value = (None, None)
            launch.return_value.returncode = 0
            for path in (WORK, REPORT):
                deadline.run(command[:-1] + [path.as_posix()])
            self.assertEqual(launch.call_count, 2)
            launch.reset_mock()
            for changed in (
                command[:3] + ["999:456", str(WORK)],
                command[:-1] + [str(WORK) + "/nested"],
                command[:-1] + [str(WORK) + "/../other"],
                ["sudo", "chown", "123:456", WORK.as_posix()],
                ["sudo", "chown", "-R", "--no-dereference", "123:456", WORK.as_posix()],
            ):
                with self.subTest(command=changed), self.assertRaises(candidate.Denied):
                    deadline.run(changed)
            launch.assert_not_called()

    def test_invalid_or_replaced_outputs_never_reclaim_other_inodes(self):
        info = types.SimpleNamespace(
            st_mode=stat.S_IFDIR | 0o700,
            st_dev=1,
            st_ino=2,
            st_uid=123,
            st_gid=456,
            st_size=0,
            st_nlink=1,
        )
        with self.identity(), patch.object(job, "run") as run:
            for mode in (stat.S_IFLNK | 0o777, stat.S_IFREG | 0o600):
                with (
                    patch.object(
                        Path,
                        "lstat",
                        return_value=types.SimpleNamespace(
                            **(vars(info) | {"st_mode": mode})
                        ),
                    ),
                    self.assertRaises(candidate.Denied),
                ):
                    job.reclaim_model_output(WORK)
            with (
                patch.object(Path, "lstat", side_effect=FileNotFoundError),
                self.assertRaises(candidate.Denied),
            ):
                job.reclaim_model_output(WORK)
            with self.assertRaises(candidate.Denied):
                job.reclaim_model_output(Path("/tmp/arbitrary"))
            with (
                patch.object(
                    Path,
                    "lstat",
                    return_value=types.SimpleNamespace(
                        **(
                            vars(info)
                            | {"st_mode": stat.S_IFREG | 0o600, "st_size": 16385}
                        )
                    ),
                ),
                self.assertRaises(candidate.Denied),
            ):
                job.reclaim_model_output(REPORT)
            run.assert_not_called()
            changed = types.SimpleNamespace(**(vars(info) | {"st_ino": 3}))
            with (
                patch.object(Path, "lstat", side_effect=[info, changed]),
                self.assertRaisesRegex(candidate.Denied, "identity changed"),
            ):
                job.reclaim_model_output(WORK)

    def test_both_seals_quiesce_before_reclaim_and_then_read_trusted_metadata(self):
        for function, expected in (
            (job.seal, [WORK]),
            (job.review_seal, [WORK, REPORT]),
        ):
            events = []
            with (
                patch.dict(os.environ, {"RUNNER_TEMP": "/tmp/readback-unit"}),
                patch.object(
                    job,
                    "quiesce",
                    side_effect=lambda events=events: events.append("quiesce"),
                ),
                patch.object(
                    job,
                    "reclaim_model_output",
                    side_effect=lambda path, events=events: events.append(path),
                ),
                patch.object(
                    Path,
                    "read_bytes",
                    side_effect=candidate.Denied("stop before metadata"),
                ),
                self.assertRaisesRegex(candidate.Denied, "stop before metadata"),
            ):
                function()
            self.assertEqual(events, ["quiesce", *expected])

    def test_inventory_missing_root_is_not_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                candidate.Denied, "inspection root unavailable"
            ):
                candidate.files(Path(directory) / "missing")
            regular = Path(directory) / "regular"
            regular.write_text("fixture", encoding="utf-8")
            with self.assertRaisesRegex(candidate.Denied, "real directory root"):
                candidate.files(regular)

    @unittest.skipUnless(
        sys.platform == "linux", "Real UID ownership fixture requires Linux"
    )
    def test_real_distinct_uid_readback_and_private_report(self):
        result = subprocess.run(
            [
                "sudo",
                "-n",
                sys.executable,
                str(Path(__file__).resolve()),
                "--uid-fixture",
                str(os.getuid()),
                str(os.getgid()),
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "distinct UID readback and private report verified", result.stdout
        )


def uid_fixture(runner_uid, runner_gid):
    import pwd

    assert os.getuid() == 0 and runner_uid != 0
    model = pwd.getpwnam("nobody")
    assert model.pw_uid != runner_uid
    # Never touch an existing workspace or report from another process/task.
    assert not WORK.exists() and not WORK.is_symlink()
    assert not REPORT.exists() and not REPORT.is_symlink()
    with tempfile.TemporaryDirectory(prefix="pawlocal-readback-") as directory:
        root = Path(directory)
        root.chmod(0o755)
        base = root / "base"
        base.mkdir(mode=0o700)
        original = {"backend/pawlocal/application/places.py": b"# original\n"}
        candidate.materialize(original, base)
        shutil.copytree(base, WORK)
        edits = {
            "backend/pawlocal/application/places.py": b"# fixed\n",
            "backend/tests/test_incident_regression.py": b"def test_regression(): pass\n",
        }
        candidate.materialize(edits, WORK)
        for tree, uid, gid in (
            (base, runner_uid, runner_gid),
            (WORK, model.pw_uid, model.pw_gid),
        ):
            for directory, _, names in os.walk(tree):
                os.chown(directory, uid, gid)
                for name in names:
                    os.chown(Path(directory) / name, uid, gid)
        content = b'{"verdict":"pass","candidate_sha":"fixture","findings":[]}'
        REPORT.write_bytes(content)
        REPORT.chmod(0o600)
        os.chown(REPORT, model.pw_uid, model.pw_gid)

        def as_runner(code):
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys;sys.path.insert(0,"
                    + repr(str(ROOT / "ops/incident-response"))
                    + ");"
                    + code,
                ],
                preexec_fn=lambda: (os.setgid(runner_gid), os.setuid(runner_uid)),
                capture_output=True,
                text=True,
                check=False,
                env={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
            )

        try:
            before = as_runner(
                "from pathlib import Path;import candidate;candidate.files(Path("
                + repr(str(WORK))
                + "))"
            )
            assert (
                before.returncode != 0 and "candidate traversal failed" in before.stderr
            )
            with patch.multiple(
                os, getuid=lambda: runner_uid, getgid=lambda: runner_gid
            ):
                # Real deadline.run -> finite policy -> sudo/chown, no mocked launch.
                job.reclaim_model_output(WORK)
                job.reclaim_model_output(REPORT)
            assert stat.S_IMODE(WORK.stat().st_mode) == 0o700
            assert stat.S_IMODE(REPORT.stat().st_mode) == 0o600
            assert (
                WORK / "backend/pawlocal/application/places.py"
            ).stat().st_uid == model.pw_uid
            probe = as_runner(
                "from pathlib import Path;import candidate;"
                + "base=Path("
                + repr(str(base))
                + ");work=Path("
                + repr(str(WORK))
                + ");"
                + "metadata={'base_sha':'a'*40,'alert':{'incident_key':'b'*64}};"
                + "value=candidate.load(candidate.export(base,work,metadata),metadata);"
                + "assert value=="
                + repr(edits)
                + ";"
                + "assert Path("
                + repr(str(REPORT))
                + ").read_bytes()=="
                + repr(content)
            )
            assert probe.returncode == 0, probe.stdout + probe.stderr
            private = WORK / "backend"
            private.chmod(0o700)
            blocked = as_runner(
                "from pathlib import Path;import candidate;candidate.files(Path("
                + repr(str(WORK))
                + "))"
            )
            assert (
                blocked.returncode != 0
                and "candidate traversal failed" in blocked.stderr
            )
            private.chmod(0o755)
            (WORK / "link").symlink_to(root, target_is_directory=True)
            linked = as_runner(
                "from pathlib import Path;import candidate;candidate.files(Path("
                + repr(str(WORK))
                + "))"
            )
            assert (
                linked.returncode != 0
                and "symlink directory forbidden" in linked.stderr
            )
            # Actual fixed-root/report symlinks must fail before privileged chown
            # and leave their outside target's identity and mode unchanged.
            for path in (WORK, REPORT):
                saved = root / ("saved-" + path.name)
                path.rename(saved)
                target = root / ("target-" + path.name)
                if path == WORK:
                    target.mkdir(mode=0o700)
                else:
                    target.write_bytes(content)
                    target.chmod(0o600)
                os.chown(target, model.pw_uid, model.pw_gid)
                before = target.stat()
                path.symlink_to(target, target_is_directory=path == WORK)
                with (
                    patch.multiple(
                        os, getuid=lambda: runner_uid, getgid=lambda: runner_gid
                    ),
                    patch.object(job, "run") as forbidden,
                ):
                    try:
                        job.reclaim_model_output(path)
                    except candidate.Denied:
                        pass
                    else:
                        raise AssertionError("fixed output symlink was accepted")
                    forbidden.assert_not_called()
                after = target.stat()
                assert (before.st_uid, before.st_gid, before.st_mode) == (
                    after.st_uid,
                    after.st_gid,
                    after.st_mode,
                )
                path.unlink()
                saved.rename(path)
            print("distinct UID readback and private report verified")
        finally:
            # These exact roots were created only after the no-survivor checks.
            if WORK.is_symlink():
                WORK.unlink()
            else:
                shutil.rmtree(WORK)
            REPORT.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--uid-fixture"]:
        uid_fixture(int(sys.argv[2]), int(sys.argv[3]))
    else:
        unittest.main()
