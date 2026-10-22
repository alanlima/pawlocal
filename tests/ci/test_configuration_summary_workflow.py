"""Execute the summary shell fallback independently of a successful checkout."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SummaryWorkflowTests(unittest.TestCase):
    def test_missing_or_unrunnable_checkout_helper_has_shell_fallback(self):
        import yaml

        if os.name == "nt":
            candidates = [
                Path("C:/Program Files/Git/bin/bash.exe"),
                Path.home() / "scoop/apps/git/current/bin/bash.exe",
            ]
            shell = next((str(path) for path in candidates if path.is_file()), None)
        else:
            shell = shutil.which("bash")
        if not shell:
            self.skipTest("Bash unavailable")
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/reconcile-environment.yml").read_text()
        )
        script = workflow["jobs"]["reconcile"]["steps"][-1]["run"]
        for helper in ("missing", "unrunnable"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "summary"
                if helper == "unrunnable":
                    source = Path(directory) / "ops/configuration/job_summary.py"
                    source.parent.mkdir(parents=True)
                    source.write_text("!invalid python")
                result = subprocess.run(
                    [shell, "--noprofile", "--norc", "-c", script],
                    cwd=directory,
                    env={**os.environ, "GITHUB_STEP_SUMMARY": str(path), "PATH": ""},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("**INCOMPLETE", path.read_text())
                self.assertIn("writes may have occurred", path.read_text())
