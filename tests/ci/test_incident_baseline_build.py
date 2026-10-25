import os
from unittest.mock import patch
"""Offline actual pip/PEP 517 fixture for trusted source-build side effects."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops/incident-response"))
import candidate
import deadline
import job
import process_policy


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class BaselineBuildTests(unittest.TestCase):
    def metadata(self):
        return {"base_sha": "a" * 40, "alert": {"incident_key": "b" * 64}}

    def test_actual_pip_build_changes_only_disposable_source_and_two_edits_seal(self):
        # A dependency-free PEP 517 backend deliberately emits normal source-tree
        # build metadata. pip executes it for real, offline, without credentials.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, work, dependencies = (
                root / name for name in ("base", "work", "deps")
            )
            source = baseline / "backend"
            source.mkdir(parents=True)
            dependencies.mkdir()
            (source / "pyproject.toml").write_text(
                '[build-system]\nrequires=[]\nbuild-backend="fixture_build"\nbackend-path=["."]\n',
                encoding="utf-8",
            )
            (source / "fixture_build.py").write_text(
                """from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    Path("build/lib").mkdir(parents=True, exist_ok=True)
    Path("build/lib/fixture.py").write_text("# generated build copy")
    Path("fixture.egg-info").mkdir(exist_ok=True)
    Path("fixture.egg-info/PKG-INFO").write_text("generated metadata")
    name = "fixture-0.0.0-py3-none-any.whl"
    with ZipFile(Path(wheel_directory) / name, "w") as wheel:
        wheel.writestr("fixture.py", "# fixture")
        wheel.writestr("fixture-0.0.0.dist-info/METADATA", "Metadata-Version: 2.1\\nName: fixture\\nVersion: 0.0.0\\n")
        wheel.writestr("fixture-0.0.0.dist-info/WHEEL", "Wheel-Version: 1.0\\nGenerator: fixture\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n")
        wheel.writestr("fixture-0.0.0.dist-info/RECORD", "")
    return name
""",
                encoding="utf-8",
            )
            before = candidate.files(baseline)
            shutil.copytree(baseline, work)
            build_source = job.backend_dependency_source(baseline, dependencies)
            command = [
                process_policy.DEPENDENCIES + "/venv/bin/pip",
                "install",
                "--disable-pip-version-check",
                ".[test,dsql-prototype]",
            ]
            fixed_source = process_policy.DEPENDENCIES + "/backend-source"
            popen = subprocess.Popen

            def offline_build_after_validation(argv, **options):
                # deadline.run validates the real runtime argv/cwd first. Only
                # its final process launch is relocated into this offline fixture.
                self.assertEqual(argv, command)
                self.assertEqual(str(options["cwd"]), fixed_source)
                options["cwd"] = build_source
                return popen(
                    [
                        sys.executable,
                        "-m",
                        "pip",
                        "install",
                        "--no-index",
                        "--no-deps",
                        "--no-build-isolation",
                        "--target",
                        str(root / "installed"),
                        ".[test,dsql-prototype]",
                    ],
                    **options,
                )

            with (
                patch.dict(os.environ, {"RUNNER_TEMP": str(root)}),
                patch.object(deadline, "DEADLINE", None),
                patch.object(
                    deadline.subprocess,
                    "Popen",
                    side_effect=offline_build_after_validation,
                ) as launch,
            ):
                result = deadline.run(
                    command, cwd=fixed_source, stdout=subprocess.PIPE, timeout=45
                )
            self.assertEqual(result.returncode, 0, result.stdout.decode())
            launch.assert_called_once()
            self.assertTrue((build_source / "build/lib/fixture.py").is_file())
            self.assertTrue((build_source / "fixture.egg-info/PKG-INFO").is_file())
            self.assertEqual(candidate.files(baseline), before)
            edits = {
                "backend/pawlocal/application/places.py": b"# approved application edit\n",
                "backend/tests/test_incident_regression.py": b"def test_regression(): pass\n",
            }
            candidate.materialize(edits, work)
            self.assertEqual(
                candidate.load(
                    candidate.export(baseline, work, self.metadata()), self.metadata()
                ),
                edits,
            )
            # The old build location creates false baseline-only differences;
            # they remain rejected rather than ignored or allowlisted.
            shutil.copytree(build_source / "build", source / "build")
            shutil.copytree(
                build_source / "fixture.egg-info", source / "fixture.egg-info"
            )
            with self.assertRaisesRegex(candidate.Denied, "outside_approved_paths"):
                candidate.export(baseline, work, self.metadata())

    def test_trusted_wrapper_denies_baseline_candidate_and_other_build_paths(self):
        command = [
            process_policy.DEPENDENCIES + "/venv/bin/pip",
            "install",
            "--disable-pip-version-check",
            ".[test,dsql-prototype]",
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"RUNNER_TEMP": directory}),
        ):
            with patch.object(deadline.subprocess, "Popen") as launch:
                for cwd in (
                    Path(directory) / "oncall-trusted/baseline/backend",
                    "/tmp/pawlocal-oncall-candidate/backend",
                    process_policy.DEPENDENCIES + "/backend-source-other",
                    process_policy.DEPENDENCIES + "/backend-source/../candidate",
                ):
                    with (
                        self.subTest(cwd=cwd),
                        self.assertRaisesRegex(
                            candidate.Denied, "trusted build source"
                        ),
                    ):
                        deadline.run(command, cwd=cwd)
                launch.assert_not_called()
            # Independent trusted checks retain their own separate archive.
            with patch.object(deadline.subprocess, "Popen") as launch:
                launch.return_value.communicate.return_value = (None, None)
                launch.return_value.returncode = 0
                deadline.run(
                    command,
                    cwd=Path(directory) / "oncall-checks/dependency-source/backend",
                )
                launch.assert_called_once()

    def test_refusal_diagnostics_are_bounded_escaped_and_content_free(self):
        with tempfile.TemporaryDirectory() as directory:
            base, edited = (Path(directory) / name for name in ("base", "edited"))
            base.mkdir()
            edited.mkdir()
            for index in range(25):
                (edited / f"outside-{index:02d}.txt").write_text(
                    "SECRET_PAYLOAD", encoding="utf-8"
                )
            with self.assertRaises(candidate.Denied) as error:
                candidate.export(base, edited, self.metadata())
            raw = str(error.exception)
            report = json.loads(raw.split(": ", 1)[1])
            self.assertEqual(
                (report["reason"], report["changed_count"], report["outside_count"]),
                ("excessive_files", 25, 25),
            )
            self.assertEqual(len(report["paths"]), 20)
            self.assertTrue(report["paths_truncated"])
            self.assertNotIn("SECRET_PAYLOAD", raw)
            self.assertLess(len(raw), 30000)
            # Newline/Unicode names are JSON escaped, not extra log lines.
            with (
                patch.object(
                    candidate, "files", side_effect=[{}, {"bad\n\u00e9.txt": "digest"}]
                ),
                self.assertRaises(candidate.Denied) as escaped,
            ):
                candidate.export(base, edited, self.metadata())
            self.assertNotIn("\n", str(escaped.exception))
            self.assertIn(r"\n\u00e9", str(escaped.exception))

    def test_maximum_diagnostic_path_encoding_is_bounded(self):
        names = {f"{index:02d}" + "\u00e9" * 1000: "digest" for index in range(25)}
        with (
            patch.object(candidate, "files", side_effect=[{}, names]),
            self.assertRaises(candidate.Denied) as error,
        ):
            candidate.export(Path("base"), Path("edited"), self.metadata())
        raw = str(error.exception)
        report = json.loads(raw.split(": ", 1)[1])
        self.assertEqual(len(report["paths"]), 20)
        self.assertTrue(all(len(name) == 240 for name in report["paths"]))
        self.assertTrue(report["paths_truncated"])
        self.assertLess(len(raw), 30000)

    def test_source_deletion_and_empty_still_fail_with_precise_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            base, edited = (Path(directory) / name for name in ("base", "edited"))
            base.mkdir()
            edited.mkdir()
            with self.assertRaisesRegex(candidate.Denied, '"reason":"empty"'):
                candidate.export(base, edited, self.metadata())
            candidate.materialize({"backend/pawlocal/main.py": b"# original"}, base)
            with self.assertRaisesRegex(candidate.Denied, '"reason":"source_deletion"'):
                candidate.export(base, edited, self.metadata())


if __name__ == "__main__":
    unittest.main()
