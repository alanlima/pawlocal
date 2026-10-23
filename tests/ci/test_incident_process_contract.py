import pathlib
import shutil
import tempfile
import unittest

from incident_process_contract import (
    DIRECT,
    FUNCTIONS,
    residual_source,
    validate_inventory,
)
from test_aws_infrastructure_ownership import contains_forbidden_terraform_state_change

ROOT = pathlib.Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "ops/incident-response"


class IncidentProcessContractTests(unittest.TestCase):
    def test_only_proven_launches_removed_and_residual_scanner_still_runs(self):
        validate_inventory(ROOT)
        for name in DIRECT:
            path = DIRECTORY / name
            residual = residual_source(ROOT, path, path.read_text())
            self.assertFalse(contains_forbidden_terraform_state_change(residual))
            self.assertTrue(
                contains_forbidden_terraform_state_change(
                    residual
                    + '\nsubprocess.run(["terraform", "state", "rm", "fixture"])'
                )
            )

    def test_changed_argv_helper_path_shell_or_extra_launcher_denies(self):
        mutations = (
            (
                "capture-cli-request.py",
                "import subprocess",
                "from unreviewed_module import subprocess",
            ),
            ("capture-cli-request.py", '"codex",', '"terraform",'),
            ("job.py", '"ops/incident-response/quota_gateway.py"', '"unreviewed.py"'),
            ("job.py", "env=environment,", "shell=True, env=environment,"),
            ("deadline.py", "**kwargs,", 'executable="terraform", **kwargs,'),
            ("checks.py", '"ci", "--ignore-scripts"', '"ci", "--foreground-scripts"'),
        )
        for name, before, after in mutations:
            source = (DIRECTORY / name).read_text()
            self.assertIn(before, source)
            with (
                self.subTest(name=name, mutation=after),
                self.assertRaises(AssertionError),
            ):
                validate_inventory(ROOT, {name: source.replace(before, after, 1)})
        path = DIRECTORY / "job.py"
        for extra in (
            '\nsubprocess.run(["aws", "iam", "create-role"])',
            '\nlaunch = subprocess.Popen\nlaunch(["terraform", "apply"])',
        ):
            source = path.read_text() + extra
            with self.assertRaises(AssertionError):
                residual_source(ROOT, path, source)

    def test_new_wrapper_import_callsite_or_escaped_alias_denies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            destination = root / "ops/incident-response"
            destination.mkdir(parents=True)
            for name in FUNCTIONS:
                shutil.copyfile(DIRECTORY / name, destination / name)
            added = destination / "unreviewed.py"
            for source in (
                'from deadline import run\nrun(["terraform", "apply"])',
                'from deadline import run as launch\nlaunch(["echo", "fixture"])',
                'import deadline\ndeadline.run(["echo", "fixture"])',
                'from importlib import import_module\nimport_module("deadline").run(["aws", "ec2", "terminate-instances"])',
                'import importlib as loader\nloader.import_module("deadline").run(["aws", "iam", "create-role"])',
                '__import__("deadline").run(["terraform", "apply"])',
                'import sys\nsys.modules["deadline"].run(["terraform", "apply"])',
                'loader = __import__\nloader("deadline").run(["terraform", "apply"])',
            ):
                added.write_text(source)
                with self.subTest(source=source), self.assertRaises(AssertionError):
                    validate_inventory(root)
            added.unlink()
            added.write_text('__import__("json").loads("{}")')
            validate_inventory(root)
            added.unlink()
            source = (
                destination / "job.py"
            ).read_text() + '\ndef unreviewed():\n return run(["echo", "fixture"])\n'
            with self.assertRaises(AssertionError):
                validate_inventory(root, {"job.py": source})
            source = (destination / "job.py").read_text() + "\nlaunch = run\n"
            with self.assertRaises(AssertionError):
                validate_inventory(root, {"job.py": source})


if __name__ == "__main__":
    unittest.main()
