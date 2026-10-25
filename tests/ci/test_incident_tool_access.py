import os
from unittest.mock import patch
"""Credential-free hosted setup-python ancestor proof using a distinct real UID."""

import json
import shutil
import subprocess
import tempfile
import unittest
import venv
from pathlib import Path


@unittest.skipUnless(os.name == "posix", "actual Ubuntu UID/traversal contract")
@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class HostedInterpreterAccessTests(unittest.TestCase):
    def test_actual_setup_python_venv_is_readable_and_private_ancestor_denies(self):
        import pwd

        identity = pwd.getpwnam("nobody")
        self.assertNotEqual(identity.pw_uid, os.getuid())
        prefix = []
        if os.getuid() != 0:
            if not shutil.which("sudo"):
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    self.fail(
                        "hosted runner must provide distinct-UID fixture capability"
                    )
                self.skipTest("local runner has no distinct-UID capability")
            prefix = ["sudo", "-n", "-u", "nobody", "--"]
            capability = subprocess.run(
                prefix + ["/usr/bin/true"], capture_output=True, timeout=10, check=False
            )
            if capability.returncode:
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    self.fail(
                        "hosted runner cannot execute the required distinct-UID fixture"
                    )
                self.skipTest("local noninteractive distinct-UID privilege unavailable")

        def drop_uid():
            os.setgroups([])
            os.setgid(identity.pw_gid)
            os.setuid(identity.pw_uid)

        with tempfile.TemporaryDirectory(
            prefix="pawlocal-python-access-", dir="/var/tmp"
        ) as directory:
            root = Path(directory)
            root.chmod(0o755)
            environment = root / "venv"
            # sys.executable is the actual actions/setup-python interpreter in CI.
            # No pip/download/API/model invocation is needed to prove traversal.
            venv.EnvBuilder(with_pip=False).create(environment)
            interpreter = environment / "bin/python"
            command = prefix + [
                str(interpreter),
                "-c",
                "import json,os,sys; print(json.dumps([os.getuid(),sys.prefix]))",
            ]

            def execute():
                return subprocess.run(
                    command,
                    cwd="/var/tmp",
                    env={"PATH": "/usr/bin:/bin"},
                    preexec_fn=drop_uid if os.getuid() == 0 else None,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

            healthy = execute()
            self.assertEqual(
                healthy.returncode,
                0,
                "actual setup-python interpreter/ancestors are not accessible to model UID: "
                + healthy.stderr,
            )
            self.assertEqual(
                json.loads(healthy.stdout), [identity.pw_uid, str(environment)]
            )
            root.chmod(0o700)
            try:
                try:
                    denied = execute()
                except PermissionError:
                    denied = None
                if denied is not None:
                    self.assertNotEqual(denied.returncode, 0)
            finally:
                root.chmod(0o755)
            self.assertEqual(execute().returncode, 0)


if __name__ == "__main__":
    unittest.main()
