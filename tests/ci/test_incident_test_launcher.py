import errno
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "ops/incident-response/backend-test-launcher.py"
SPEC = importlib.util.spec_from_file_location("incident_test_launcher", LAUNCHER)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        unix = patch.object(
            socket, "AF_UNIX", getattr(socket, "AF_UNIX", 1), create=True
        )
        unix.start()
        self.addCleanup(unix.stop)

    def loop(self, family=1, kind=socket.SOCK_STREAM):
        return types.SimpleNamespace(
            _csock=types.SimpleNamespace(family=family, type=kind, fileno=lambda: 123),
            _debug=False,
        )

    def test_only_existing_unix_stream_descriptor_uses_write(self):
        loop = self.loop()
        with patch.object(launcher.os, "write") as write:
            launcher.write_to_self(loop)
            write.assert_called_once_with(123, b"\0")
        for family, kind in (
            (socket.AF_INET, socket.SOCK_STREAM),
            (socket.AF_UNIX, socket.SOCK_DGRAM),
        ):
            loop = self.loop(family, kind)
            with (
                patch.object(launcher, "_ORIGINAL_WRITE") as original,
                patch.object(launcher.os, "write") as write,
            ):
                launcher.write_to_self(loop)
                original.assert_called_once_with(loop)
                write.assert_not_called()

    def test_closed_loop_and_os_errors_preserve_original_noop_semantics(self):
        with patch.object(launcher.os, "write") as write:
            launcher.write_to_self(types.SimpleNamespace(_csock=None))
            write.assert_not_called()
        for code in (errno.EAGAIN, errno.EBADF):
            loop = self.loop()
            with (
                patch.object(
                    launcher.os, "write", side_effect=OSError(code, "fixture")
                ),
                patch.object(launcher._LOGGER, "debug") as log,
            ):
                launcher.write_to_self(loop)
                log.assert_not_called()
                loop._debug = True
                launcher.write_to_self(loop)
                log.assert_called_once()
        with self.assertRaises(AttributeError):
            launcher.write_to_self(types.SimpleNamespace())

    def test_pytest_arguments_and_nonzero_result_are_preserved(self):
        pytest = types.SimpleNamespace(main=Mock(return_value=5))
        with (
            patch.dict(sys.modules, {"pytest": pytest}),
            patch.object(
                sys,
                "argv",
                ["launcher", "backend/tests/test_incident_regression.py", "-vv"],
            ),
            patch.object(launcher, "install") as install,
        ):
            self.assertEqual(launcher.main(), 5)
            install.assert_called_once_with()
            pytest.main.assert_called_once_with(
                ["backend/tests/test_incident_regression.py", "-vv"]
            )

    def test_trusted_launcher_copy_and_runner_command_are_narrow(self):
        source = (ROOT / "ops/incident-response/job.py").read_text(encoding="utf-8")
        self.assertIn(
            'trusted / "ops/incident-response/backend-test-launcher.py"',
            source,
        )
        self.assertIn("launcher.chmod(0o444)", source)
        self.assertIn(
            '"/tmp/pawlocal-oncall-dependencies/backend-test-launcher.py "', source
        )
        sys.path.insert(0, str(ROOT / "ops/incident-response"))
        import process_policy

        dependency = process_policy.DEPENDENCIES
        command = [
            dependency + "/venv/bin/python",
            dependency + "/backend-test-launcher.py",
            "--version",
        ]
        self.assertTrue(process_policy.unprivileged(command))
        self.assertFalse(
            process_policy.unprivileged(command[:-1] + ["arbitrary-test.py"])
        )
        self.assertFalse(
            process_policy.unprivileged(
                [command[0], "/tmp/untrusted-launcher.py", "--version"]
            )
        )
        checks = (ROOT / "ops/incident-response/checks.py").read_text(encoding="utf-8")
        self.assertNotIn("backend-test-launcher", checks)

    @unittest.skipUnless(
        sys.platform == "linux" and os.environ.get("PAWLOCAL_SANDBOX_CODEX"),
        "explicit credential-free Linux sandbox fixture",
    )
    def test_pinned_sandbox_real_testclient_and_network_isolation(self):
        codex = os.environ["PAWLOCAL_SANDBOX_CODEX"]
        self.assertTrue(Path(codex).is_file())
        with tempfile.TemporaryDirectory(prefix="pawlocal-test-launcher-") as directory:
            root = Path(directory)
            environment = {
                "HOME": directory,
                "CODEX_HOME": directory,
                "PATH": os.environ["PATH"],
                "LANG": "C.UTF-8",
            }
            version = subprocess.run(
                [codex, "--version"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertIn("0.163.0", version.stdout)
            work = root / "workspace"
            work.mkdir()
            test = work / "test_roundtrip.py"
            test.write_text(
                """import socket
from fastapi import FastAPI
from fastapi.testclient import TestClient

def test_real_testclient_roundtrip():
    app = FastAPI()
    @app.get("/places")
    def places():
        return {"items": [{"name": "fixture"}]}
    with TestClient(app) as client:
        for _ in range(20):
            response = client.get("/places")
            assert response.status_code == 200
            assert response.json() == {"items": [{"name": "fixture"}]}

def test_external_socket_creation_remains_denied():
    try:
        external = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except PermissionError:
        return
    external.close()
    raise AssertionError("Sandbox allowed external socket creation")
""",
                encoding="utf-8",
            )
            # The same real TestClient exercise stalls without the adapter.
            baseline = work / "baseline.py"
            baseline.write_text(
                "import faulthandler\nfaulthandler.dump_traceback_later(3, exit=True)\nfrom test_roundtrip import test_real_testclient_roundtrip\ntest_real_testclient_roundtrip()\n",
                encoding="utf-8",
            )
            prefix = [
                codex,
                "sandbox",
                "-P",
                ":workspace",
                "-C",
                str(work),
                "--",
                sys.executable,
                "-u",
            ]
            blocked = subprocess.run(
                [*prefix, str(baseline)],
                cwd=work,
                env=environment,
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("Timeout", blocked.stderr)
            self.assertIn("testclient.py", blocked.stderr)
            # Copy trusted source outside the model workspace, matching runtime.
            trusted = root / "trusted"
            trusted.mkdir()
            copy = trusted / "backend-test-launcher.py"
            copy.write_bytes(LAUNCHER.read_bytes())
            copy.chmod(0o444)
            passed = subprocess.run(
                [*prefix, str(copy), str(test), "-q", "-p", "no:cacheprovider"],
                cwd=work,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertIn("2 passed", passed.stdout)
            self.assertNotIn("skipped", passed.stdout)


if __name__ == "__main__":
    unittest.main()
