import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import deadline
import process_policy


class ProcessDeadlineTests(unittest.TestCase):
    def test_git_loader_environment_must_equal_trusted_parent(self):
        command = [
            "git",
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "core.fsmonitor=false",
            "-C",
            "/tmp/fixture",
            "rev-parse",
            "HEAD",
        ]
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/trusted/toolcache/lib"}):
            process_policy.validate(
                command, None, {"env": {"LD_LIBRARY_PATH": "/trusted/toolcache/lib"}}
            )
            with self.assertRaises(deadline.Denied):
                process_policy.validate(
                    command, None, {"env": {"LD_LIBRARY_PATH": "/tmp/untrusted"}}
                )

    def test_reflected_wrapper_cannot_execute_infrastructure_or_root_shell(self):
        wrapper = importlib.import_module("deadline")
        for command in (
            ["aws", "ec2", "terminate-instances", "--instance-ids", "fixture"],
            ["terraform", "apply"],
            ["sudo", "aws", "iam", "create-role"],
            ["sudo", "bash", "-c", "echo fixture"],
            [sys.executable, "-c", "print('fixture')"],
            ["npm", "exec", "arbitrary-package"],
            ["git", "-c", "alias.fixture=!aws", "fixture"],
        ):
            with (
                self.subTest(command=command),
                patch.object(wrapper.subprocess, "Popen") as launch,
            ):
                with self.assertRaises(deadline.Denied):
                    wrapper.run(command)
                launch.assert_not_called()

    def test_trusted_dependency_and_unprivileged_test_families_are_supported(self):
        for command in (
            ["npm", "ci", "--ignore-scripts"],
            [sys.executable, "-m", "venv", process_policy.DEPENDENCIES + "/venv"],
            ["sudo", "-u", "oncall", "env", "-i", "CI=true", "npm", "run", "build"],
            ["sudo", "pkill", "-KILL", "-u", "oncall"],
            [
                "sudo",
                "-u",
                "oncall",
                "env",
                "-i",
                "PATH=/usr/bin:/bin",
                process_policy.DEPENDENCIES + "/venv/bin/python",
                "-m",
                "pytest",
                "--version",
            ],
        ):
            with self.subTest(command=command):
                process_policy.validate(
                    command,
                    None,
                    {"cwd": process_policy.DEPENDENCIES + "/frontend"}
                    if command[0] == "npm"
                    else {},
                )

    def test_shell_alternate_executable_or_untyped_vector_never_launches(self):
        for command, options in (
            ("echo fixture", {}),
            ([], {}),
            (["echo", 1], {}),
            (["echo", "fixture"], {"shell": True}),
            (["echo", "fixture"], {"shell": False}),
            (["echo", "fixture"], {"executable": "terraform"}),
            (["npm", "ci", "--ignore-scripts"], {"preexec_fn": lambda: None}),
            (["npm", "ci", "--ignore-scripts"], {"pass_fds": (3,)}),
            (["npm", "ci", "--ignore-scripts"], {"start_new_session": False}),
            (["npm", "ci", "--ignore-scripts"], {"user": 0}),
            (["npm", "ci", "--ignore-scripts"], {"stdin": None}),
            (["npm", "ci", "--ignore-scripts"], {"stderr": None}),
            (["npm", "ci", "--ignore-scripts"], {"cwd": "/tmp/untrusted-candidate"}),
            (
                ["npm", "ci", "--ignore-scripts"],
                {"env": {"LD_PRELOAD": "/tmp/fixture"}},
            ),
        ):
            with (
                self.subTest(command=command, options=options),
                patch.object(deadline.subprocess, "Popen") as launch,
            ):
                with self.assertRaises(deadline.Denied):
                    deadline.run(command, **options)
                launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
