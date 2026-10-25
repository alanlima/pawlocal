import os
from unittest.mock import patch
"""Required backend quality parity and restricted unprivileged execution."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ops/incident-response"))
import checks
import process_policy
from quota import Denied

DEPS = Path(process_policy.DEPENDENCIES)
INTEGRATIONS = (
    "test_postgres_repositories_constraints_and_records_survive_new_sessions",
    "test_0006_quarantines_legacy_rows_and_downgrade_restores_them",
    "test_0007_backfills_facilities_in_order_and_handles_empty_arrays",
)


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class BackendQualityTests(unittest.TestCase):
    def test_real_required_ci_commands_and_dependencies_have_explicit_parity(self):
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/backend-ci.yml").read_text()
        )
        commands = [
            step["run"]
            for step in workflow["jobs"]["backend"]["steps"]
            if "run" in step
        ]
        self.assertEqual(
            commands,
            [
                'python -m pip install -e ".[test,dsql-prototype]"',
                "ruff check .",
                "dsql-lint migrations/dsql/0001_initial/*.sql",
                'python scripts/render_dsql_search_query.py > "$RUNNER_TEMP/pawlocal-dsql-search.sql"\ndsql-lint "$RUNNER_TEMP/pawlocal-dsql-search.sql"\n',
                "alembic -c alembic.ini upgrade head",
                "pytest",
            ],
        )
        source = (ROOT / "ops/incident-response/checks.py").read_text()
        self.assertIn('".[test,dsql-prototype]"', source)
        self.assertNotIn('"not integration"', source)
        incident = yaml.safe_load(
            (ROOT / ".github/workflows/incident-responder.yml").read_text()
        )
        quality = yaml.safe_load(
            (ROOT / ".github/workflows/workflow-validation.yml").read_text()
        )
        for job in (
            incident["jobs"]["checks"],
            incident["jobs"]["reviewer"],
            quality["jobs"]["validate"],
        ):
            service = job["services"]["postgres"]
            self.assertEqual(service["image"], "postgres:17.6-alpine")
            self.assertEqual(service["ports"], ["127.0.0.1:5432:5432"])
        self.assertNotIn("services", incident["jobs"]["fixer"])

    def test_backend_cwd_and_disposable_database_are_projected_without_runner_secrets(
        self,
    ):
        cwd = Path("/tmp/pawlocal-oncall-check-work/candidate/backend")
        command = [(DEPS / "venv/bin/ruff").as_posix(), "check", "."]
        with patch.object(checks, "remaining"), patch.object(checks, "run") as run:
            run.return_value.returncode = 0
            checks.execute(command, cwd, {}, {"PATH": "/tools", "database": True})
        actual = run.call_args.args[0]
        self.assertIn("PYTHONPATH=" + str(cwd), actual)
        self.assertIn(
            "PAWLOCAL_DATABASE_URL=" + process_policy.TEST_DATABASE_URL, actual
        )
        self.assertIn(
            "PAWLOCAL_TEST_DATABASE_URL=" + process_policy.TEST_DATABASE_URL, actual
        )
        self.assertEqual(actual[-3:], command)
        self.assertEqual(run.call_args.kwargs["cwd"], cwd)

    def test_finite_commands_and_only_canonical_disposable_database_urls(self):
        accepted = [
            [(DEPS / "venv/bin/ruff").as_posix(), "check", "."],
            [
                (DEPS / "venv/bin/python").as_posix(),
                (DEPS / "render-check-sql.py").as_posix(),
            ],
            [
                (DEPS / "venv/bin/alembic").as_posix(),
                "-c",
                "alembic.ini",
                "upgrade",
                "head",
            ],
            [
                (DEPS / "venv/bin/python").as_posix(),
                "-m",
                "pytest",
                "--junitxml=../backend-quality.xml",
            ],
            [
                (DEPS / "venv/bin/dsql-lint").as_posix(),
                "migrations/dsql/0001_initial/0001_tables.sql",
            ],
            [
                (DEPS / "venv/bin/dsql-lint").as_posix(),
                (DEPS / "rendered-search.sql").as_posix(),
            ],
        ]
        for command in accepted:
            process_policy.validate(
                [
                    "sudo",
                    "-u",
                    "oncall",
                    "env",
                    "-i",
                    "PAWLOCAL_DATABASE_URL=" + process_policy.TEST_DATABASE_URL,
                    *command,
                ],
                None,
                {"cwd": "/tmp/pawlocal-oncall-check-work/candidate/backend"},
            )
        for command in (
            [(DEPS / "venv/bin/ruff").as_posix(), "check", "--fix", "."],
            [(DEPS / "venv/bin/ruff").as_posix(), "format", "."],
            [(DEPS / "venv/bin/python").as_posix(), "scripts/untrusted.py"],
            [(DEPS / "venv/bin/dsql-lint").as_posix(), "/tmp/arbitrary.sql"],
            [
                (DEPS / "venv/bin/dsql-lint").as_posix(),
                "migrations/dsql/0001_initial/../../escape.sql",
            ],
            [
                (DEPS / "venv/bin/alembic").as_posix(),
                "-c",
                "/tmp/arbitrary.ini",
                "upgrade",
                "head",
            ],
        ):
            with self.subTest(command=command), self.assertRaises(Denied):
                process_policy.validate(
                    ["sudo", "-u", "oncall", "env", "-i", *command],
                    None,
                    {"cwd": "/tmp/pawlocal-oncall-check-work/candidate/backend"},
                )
        for value in (
            process_policy.TEST_DATABASE_URL.replace("127.0.0.1", "localhost"),
            process_policy.TEST_DATABASE_URL.replace(
                "127.0.0.1", "database.example.com"
            ),
            process_policy.TEST_DATABASE_URL + "?host=database.example.com",
        ):
            for key in ("PAWLOCAL_DATABASE_URL", "PAWLOCAL_TEST_DATABASE_URL"):
                with self.subTest(value=value, key=key), self.assertRaises(Denied):
                    process_policy.validate(
                        [
                            "sudo",
                            "-u",
                            "oncall",
                            "env",
                            "-i",
                            key + "=" + value,
                            *accepted[0],
                        ],
                        None,
                        {"cwd": "/tmp/pawlocal-oncall-check-work/candidate/backend"},
                    )
        for cwd in (
            "/tmp/pawlocal-oncall-check-work/affected/backend",
            "/tmp/arbitrary",
            None,
        ):
            with (
                self.subTest(cwd=cwd),
                self.assertRaisesRegex(Denied, "fixed candidate"),
            ):
                process_policy.validate(
                    ["sudo", "-u", "oncall", "env", "-i", *accepted[0]],
                    None,
                    {"cwd": cwd},
                )

    def test_quality_sequence_quiesces_before_reads_and_rejects_skipped_integration(
        self,
    ):
        xml = (
            "<testsuites><testsuite>"
            + "".join('<testcase name="' + name + '"/>' for name in INTEGRATIONS)
            + "</testsuite></testsuites>"
        ).encode()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(os, "O_NOFOLLOW", getattr(os, "O_NOFOLLOW", 0), create=True),
        ):
            root = Path(directory)
            source = root / "candidate"
            baseline = source / "backend/migrations/dsql/0001_initial"
            baseline.mkdir(parents=True)
            (baseline / "0001_tables.sql").write_text("SELECT 1;")
            events = []

            def execute(command, cwd, metadata, environment):
                self.assertEqual(cwd, source / "backend")
                self.assertTrue(environment["database"])
                events.append(("command", command))
                return 0

            def read(source, name, maximum):
                self.assertEqual(events[-1][0], "reclaim")
                return b"SELECT 1;" if name.endswith(".sql") else xml

            with (
                patch.object(checks, "execute", side_effect=execute),
                patch.object(
                    checks, "quiesce", side_effect=lambda: events.append(("quiesce",))
                ),
                patch.object(
                    checks,
                    "reclaim_model_output",
                    side_effect=lambda p: events.append(("reclaim", p)),
                ),
                patch.object(checks, "safe_bytes", side_effect=read),
            ):
                result = checks.backend_quality(source, {}, root)
            self.assertEqual(result, {"tests": 3, "postgres_integration_tests": 3})
            commands = [event[1] for event in events if event[0] == "command"]
            self.assertEqual(
                [Path(command[0]).name for command in commands],
                ["ruff", "dsql-lint", "python", "dsql-lint", "alembic", "python"],
            )
            self.assertEqual(
                [command[1:] for command in commands],
                [
                    ["check", "."],
                    ["migrations/dsql/0001_initial/0001_tables.sql"],
                    [str(root / "render-check-sql.py")],
                    [str(root / "rendered-search.sql")],
                    ["-c", "alembic.ini", "upgrade", "head"],
                    ["-m", "pytest", "--junitxml=../backend-quality.xml"],
                ],
            )
            for i, event in enumerate(events):
                if event[0] == "command":
                    self.assertEqual(events[i + 1][0], "quiesce")
            (root / "rendered-search.sql").unlink()
            xml = xml.replace(
                b'<testcase name="' + INTEGRATIONS[0].encode() + b'"/>',
                b'<testcase name="'
                + INTEGRATIONS[0].encode()
                + b'"><skipped/></testcase>',
            )
            with (
                patch.object(checks, "execute", return_value=0),
                patch.object(checks, "quiesce"),
                patch.object(checks, "reclaim_model_output"),
                patch.object(checks, "safe_bytes", side_effect=[b"SELECT 1;", xml]),
                self.assertRaisesRegex(Denied, "without skips"),
            ):
                checks.backend_quality(source, {}, root)

    def test_first_lint_failure_stops_before_sql_database_or_receipt(self):
        with (
            patch.object(checks, "execute", return_value=1) as execute,
            patch.object(checks, "quiesce") as stop,
            patch.object(checks, "reclaim_model_output") as reclaim,
            self.assertRaisesRegex(Denied, "failed: ruff"),
        ):
            checks.backend_quality(
                Path("/tmp/pawlocal-oncall-check-work/candidate"), {}, DEPS
            )
        execute.assert_called_once()
        stop.assert_called_once()
        reclaim.assert_not_called()

    @unittest.skipUnless(
        sys.platform == "linux", "kernel file-size limits require Linux"
    )
    def test_renderer_kernel_limit_covers_print_os_write_and_descendants(self):
        helper = ROOT / "ops/incident-response/render-check-sql.py"
        for body in (
            "print('SELECT 1;')",
            "print('x' * (2*1024*1024))",
            "import os; os.write(1, b'x'*(2*1024*1024))",
            "import subprocess,sys; subprocess.run([sys.executable,'-c',\"import os;os.write(1,b'x'*(2*1024*1024))\"],check=True)",
        ):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                backend = root / "backend"
                (backend / "scripts").mkdir(parents=True)
                (backend / "scripts/render_dsql_search_query.py").write_text(body)
                launcher = (
                    "import importlib.util,pathlib; s=importlib.util.spec_from_file_location('renderer',"
                    + repr(str(helper))
                    + ");m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.DIRECTORY=pathlib.Path.cwd();m.main()"
                )
                result = subprocess.run(
                    [sys.executable, "-c", launcher],
                    cwd=backend,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                output = root / "backend-search.sql"
                self.assertLessEqual(output.stat().st_size, 1024 * 1024 + 1)
                self.assertEqual(len(result.stdout), 0)
                self.assertEqual(result.returncode == 0, body == "print('SELECT 1;')")


if __name__ == "__main__":
    unittest.main()
