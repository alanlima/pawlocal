"""Exercise reporting through actual reconciliation, cleanup and publish entrypoints."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from test_integration import CleanupAPI, cleanup, mappings, store_for, values
from test_reconcile import ROOT, SENTINEL, FakeAPI, FakeSSM, module

job_summary = sys.modules[module.Report.__module__]


class SummaryTests(unittest.TestCase):
    def report(
        self,
        selected,
        environment="development",
        mode="audit",
        selection="all",
        operation="reconcile",
    ):
        result = job_summary.Report(environment, mode, selection, operation)
        result.inventory_for(mappings("development") + mappings("production"), selected)
        return result

    def execute(
        self,
        environment="development",
        selection="all",
        mode="enforce",
        api=None,
        data=None,
        output_failure=False,
    ):
        api = api or FakeAPI()
        data = values(environment) if data is None else data
        selected = mappings(environment)
        ssm = store_for(selected, data).client
        github = module.GitHub("alanlima/pawlocal", SENTINEL, api)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            env = {
                "GITHUB_REPOSITORY": "alanlima/pawlocal",
                "PAWLOCAL_CONFIG_GITHUB_TOKEN": SENTINEL,
                "CONFIG_SUMMARY_PATH": str(path),
                "GITHUB_OUTPUT": str(
                    Path(directory) if output_failure else Path(directory) / "outputs"
                ),
            }
            with (
                patch.dict(os.environ, env),
                patch.object(module, "GitHub", return_value=github),
                patch.object(
                    module, "parameter_store", return_value=module.ParameterStore(ssm)
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                status = module.main(
                    [
                        "--environment",
                        environment,
                        "--selection",
                        selection,
                        "--mode",
                        mode,
                    ]
                )
            content = path.read_text(encoding="utf-8")
            self.assertNotIn(SENTINEL, content)
            for value in data.values():
                # Names and public paths can coincide with static words; actual fixture values must not appear.
                if len(value) > 12:
                    self.assertNotIn(value, content)
            return status, content, api

    def test_both_environments_all_preflight_and_noop(self):
        for environment in ("development", "production"):
            for selection in ("all", "preflight"):
                with self.subTest(environment=environment, selection=selection):
                    api = FakeAPI()
                    selected = module.select_mappings(mappings(environment), selection)
                    status, content, api = self.execute(environment, selection, api=api)
                    self.assertEqual(status, 0)
                    self.assertEqual(content.count("| /pawlocal/"), 54)
                    self.assertEqual(
                        sum(
                            row.status == "Not selected"
                            for row in self.report(
                                selected, environment, selection=selection
                            ).rows.values()
                        ),
                        54 - len(selected),
                    )
                    self.assertEqual(
                        len(
                            [
                                r
                                for r in content.splitlines()
                                if "| Created |" in r and r.startswith("| /pawlocal/")
                            ]
                        ),
                        len(selected),
                    )
                    status, retried, _ = self.execute(environment, selection, api=api)
                    self.assertEqual(status, 0)
                    self.assertEqual(
                        len(
                            [
                                r
                                for r in retried.splitlines()
                                if "| Unchanged |" in r and r.startswith("| /pawlocal/")
                            ]
                        ),
                        len(selected),
                    )
                    self.assertIn("None. No destination mutations", retried)
                    if selection == "preflight":
                        self.assertEqual(len(selected), 13)
                        self.assertIn("publication still requires", content)

    def test_mixed_changes_and_rollup(self):
        api = FakeAPI()
        data = values("development")
        for mapping in mappings("development")[:4]:
            api.variables[(mapping.github_environment, mapping.env_name)] = data[
                mapping.env_name
            ]
        # One prior value differs; the remaining destinations do not exist.
        mapping = mappings("development")[4]
        api.variables[(mapping.github_environment, mapping.env_name)] = SENTINEL
        status, content, _ = self.execute(api=api)
        self.assertEqual(status, 0)
        rows = [r for r in content.splitlines() if r.startswith("| /pawlocal/")]
        self.assertEqual(sum("| Created |" in r for r in rows), 19)
        self.assertEqual(sum("| Updated |" in r for r in rows), 1)
        self.assertEqual(sum("| Unchanged |" in r for r in rows), 4)
        self.assertIn("| development-apply | 4 | 1 | 5 | 0 | 0 | 0 |", content)

    def test_missing_and_invalid_source_before_any_writes(self):
        for environment in ("development", "production"):
            data = values(environment)
            data.pop("VITE_COGNITO_SCOPES")
            status, content, api = self.execute(environment, data=data)
            self.assertEqual(status, 1)
            self.assertFalse(any(r.method != "GET" for r in api.calls))
            self.assertIn("Missing required source", content)
            selected = [
                r
                for r in content.splitlines()
                if r.startswith(f"| /pawlocal/{environment}/")
            ]
            self.assertTrue(all("| Not attempted |" in r for r in selected))
            self.assertIn(
                "Source diagnostics (not additional destination outcomes)", content
            )
            status, content, _ = self.execute(environment, data=data, mode="audit")
            self.assertEqual(status, 0)
            self.assertIn("SUCCESS WITH WARNINGS", content)
            self.assertIn("does not establish release readiness", content)
            data = values(environment)
            data["VITE_COGNITO_DOMAIN"] = SENTINEL
            status, content, api = self.execute(environment, data=data)
            self.assertEqual(status, 1)
            self.assertFalse(any(r.method != "GET" for r in api.calls))

    def test_optional_missing_audit_and_enforce(self):
        m = module.Mapping(
            "/pawlocal/development/config/custom/optional",
            "development",
            "OPTIONAL",
            False,
            (),
        )
        for mode in ("audit", "enforce"):
            report = self.report([m], mode=mode)
            report.inventory_for([m], [m])
            module.reconcile(
                [m],
                module.ParameterStore(FakeSSM()),
                module.GitHub("alanlima/pawlocal", SENTINEL, FakeAPI()),
                lambda _: None,
                mode=mode,
                summary=report,
            )
            self.assertEqual(report.row(m).status, "Missing optional source")

    def test_partial_rejection_timeout_server_error_and_readback(self):
        for outcome in ("reject", "timeout", "server", "readback", "unexpected"):
            api = FakeAPI()
            target = mappings("development")[2]
            original = api.__call__
            written = set()

            def transport(
                request,
                timeout,
                target=target,
                outcome=outcome,
                original=original,
                written=written,
            ):
                if (
                    request.method in {"POST", "PATCH"}
                    and target.env_name.encode() in request.data
                ):
                    if outcome == "reject":
                        raise HTTPError(request.full_url, 403, SENTINEL, {}, None)
                    if outcome == "server":
                        raise HTTPError(request.full_url, 503, SENTINEL, {}, None)
                    if outcome == "timeout":
                        original(request, timeout)
                        raise URLError(SENTINEL)
                    if outcome == "unexpected":
                        raise RuntimeError(SENTINEL)
                    result = original(request, timeout)
                    written.add(target.env_name)
                    return result
                if (
                    request.method == "GET"
                    and request.full_url.endswith(target.env_name)
                    and written
                ):
                    raise HTTPError(request.full_url, 403, SENTINEL, {}, None)
                return original(request, timeout)

            status, content, _ = self.execute(api=transport)
            self.assertEqual(status, 1)
            rows = [
                r
                for r in content.splitlines()
                if r.startswith("| /pawlocal/development/")
            ]
            self.assertEqual(sum("| Created |" in r for r in rows), 2)
            self.assertEqual(sum("| Failed |" in r for r in rows), 1)
            self.assertEqual(sum("| Not attempted |" in r for r in rows), 21)
            if outcome == "readback":
                self.assertIn("Write accepted; verification incomplete", content)
            elif outcome in {"timeout", "server", "unexpected"}:
                self.assertIn("Write acceptance unknown", content)
            else:
                self.assertNotIn("Write acceptance unknown", content)
                retry_status, retry, _ = self.execute(api=api)
                self.assertEqual(retry_status, 0)
                retry_rows = [
                    line
                    for line in retry.splitlines()
                    if line.startswith("| /pawlocal/development/")
                ]
                self.assertEqual(sum("| Unchanged |" in row for row in retry_rows), 2)
                self.assertEqual(sum("| Created |" in row for row in retry_rows), 22)

    def test_secret_acceptance_never_unchanged_or_verified(self):
        m = module.Mapping(
            "/pawlocal/development/secrets/custom/token",
            "development",
            "TEST_TOKEN",
            True,
            ("required",),
        )
        report = self.report([m])
        report.inventory_for([m], [m])
        github = module.GitHub("alanlima/pawlocal", SENTINEL, FakeAPI())
        for _ in range(2):
            module.reconcile(
                [m],
                module.ParameterStore(
                    FakeSSM({m.store_key: {"Type": "SecureString", "Value": SENTINEL}})
                ),
                github,
                lambda _: None,
                summary=report,
            )
            content = report.render()
            self.assertNotIn(SENTINEL, content)
            self.assertEqual(report.row(m).status, "Secret write accepted")
            self.assertEqual(report.row(m).mutation, "secret-accepted")
            self.assertIn(job_summary.DISCLAIMER, content)
            self.assertNotIn("None. No destination mutations", content)

    def test_schema_auth_target_and_output_failures_publish_available_report(self):
        status, content, _ = self.execute(output_failure=True)
        self.assertEqual(status, 1)
        self.assertIn("**FAILED**", content)
        self.assertIn("Workflow output writing failed", content)
        self.assertEqual(content.count("| Created | Variable comparison"), 24)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary"
            with (
                patch.dict(
                    os.environ,
                    {
                        "CONFIG_SUMMARY_PATH": str(path),
                        "PAWLOCAL_CONFIG_GITHUB_TOKEN": "",
                        "GITHUB_REPOSITORY": "alanlima/pawlocal",
                    },
                ),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(module.main(["--environment", "development"]), 1)
            self.assertEqual(path.read_text().count("| /pawlocal/"), 54)
            path.unlink()
            with (
                patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(path)}),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(
                    module.main(
                        [
                            "--environment",
                            "development",
                            "--mapping",
                            str(Path(directory) / "absent"),
                        ]
                    ),
                    1,
                )
            self.assertIn("inventory unavailable", path.read_text())

        def denied(request, timeout):
            raise HTTPError(request.full_url, 403, SENTINEL, {}, None)

        status, content, _ = self.execute(api=denied)
        self.assertEqual(status, 1)
        self.assertIn("Target Environment validation failed", content)
        self.assertNotIn(
            "| Created |",
            "\n".join(r for r in content.splitlines() if r.startswith("| /pawlocal/")),
        )

    def test_summary_write_failure_fails_entrypoint_with_operational_reason(self):
        with (
            patch.object(job_summary.Report, "write", side_effect=OSError("disk quota exceeded")),
            patch.dict(os.environ, {"PAWLOCAL_CONFIG_GITHUB_TOKEN": ""}),
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(module.main(["--environment", "development"]), 1)
        self.assertNotIn(SENTINEL, error.getvalue())
        self.assertIn("Cannot write configuration summary: disk quota exceeded", error.getvalue())

    def test_secret_write_rejection_and_unknown_acceptance(self):
        mapping = module.Mapping(
            "/pawlocal/development/secrets/custom/token",
            "development",
            "TEST_TOKEN",
            True,
            (),
        )
        for code in (403, 503):
            api = FakeAPI()

            def transport(request, timeout, code=code, api=api):
                if request.method == "PUT":
                    raise HTTPError(request.full_url, code, SENTINEL, {}, None)
                return api.__call__(request, timeout)

            report = self.report([mapping])
            report.inventory_for([mapping], [mapping])
            with self.assertRaises(module.ReconciliationError):
                module.reconcile(
                    [mapping],
                    module.ParameterStore(
                        FakeSSM(
                            {
                                mapping.store_key: {
                                    "Type": "SecureString",
                                    "Value": SENTINEL,
                                }
                            }
                        )
                    ),
                    module.GitHub("alanlima/pawlocal", SENTINEL, transport),
                    lambda _: None,
                    summary=report,
                )
            self.assertEqual(report.row(mapping).status, "Failed")
            self.assertEqual(
                report.row(mapping).mutation, "none" if code == 403 else "possible"
            )
            self.assertNotIn(SENTINEL, report.render())

    def test_cleanup_entrypoint_retains_standard_failure_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(Path(directory) / "summary.md")}),
                patch.object(cleanup, "GitHub", return_value=object()),
                patch.object(cleanup, "cleanup", side_effect=RuntimeError("GitHub HTTP 403: permission denied")),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                status = cleanup.main(["--environment", "development", "--operation", "legacy-cleanup",
                                       "--confirmation", "CLEAN legacy development"])
            self.assertEqual(status, 1)
            self.assertIn("RuntimeError: GitHub HTTP 403: permission denied", errors.getvalue())
            self.assertNotIn(SENTINEL, errors.getvalue())

    def test_cleanup_invalid_confirmation_never_reports_deletion(self):
        api = CleanupAPI()
        github = module.GitHub("alanlima/pawlocal", SENTINEL, api)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(cleanup, "GitHub", return_value=github),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            path = Path(directory) / "summary"
            with patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(path)}):
                self.assertEqual(
                    cleanup.main(
                        [
                            "--environment",
                            "production",
                            "--operation",
                            "legacy-cleanup",
                            "--confirmation",
                            "wrong",
                        ]
                    ),
                    1,
                )
            text = path.read_text()
            self.assertIn("**FAILED**", text)
            self.assertEqual(
                sum(
                    "| Not attempted |" in line
                    for line in text.splitlines()
                    if line.startswith("| production |")
                ),
                16,
            )
            self.assertEqual(api.calls, [])

    def test_markdown_escaping_and_run_url(self):
        report = self.report([])
        report.rows = {
            ("hostile", "name"): job_summary.Row(
                "/pawlocal/development/config/x/y|[click](bad)\n<script>",
                "<target>",
                "NAME`*_[x]",
                False,
            )
        }
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "1)\n<script>"}):
            content = report.render()
        self.assertNotIn("<script>", content)
        self.assertNotIn("[click]", content)
        self.assertNotIn("NAME`", content)
        self.assertIn("&#124;", content)
        self.assertIn("Unavailable outside GitHub", content)

    def test_publisher_distinct_step_paths_complete_fallback_and_cancelled(self):
        args = [
            "summary",
            "--environment",
            "development",
            "--mode",
            "enforce",
            "--selection",
            "preflight",
            "--operation",
            "reconcile",
        ]
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "private.md"
            destination = Path(directory) / "publisher-step.md"
            first_step = Path(directory) / "cli-step.md"
            env = {
                "CONFIG_SUMMARY_PATH": str(private),
                "GITHUB_STEP_SUMMARY": str(first_step),
            }
            report = self.report(
                module.select_mappings(mappings("development"), "preflight"),
                selection="preflight",
            )
            report.succeeded()
            with patch.dict(os.environ, env):
                report.write()
            self.assertFalse(first_step.exists())
            for outcome in (
                "complete",
                "cancelled",
                "skipped",
                "interrupted",
                "partial-file",
            ):
                if outcome in {"skipped", "interrupted", "partial-file"}:
                    private.write_text("partial" if outcome == "partial-file" else "")
                with (
                    patch.dict(
                        os.environ,
                        {
                            **env,
                            "GITHUB_STEP_SUMMARY": str(destination),
                            "JOB_STATUS": "cancelled"
                            if outcome == "cancelled"
                            else "failure",
                            "SYNC_OUTCOME": "success"
                            if outcome in {"complete", "cancelled"}
                            else "skipped"
                            if outcome == "skipped"
                            else "failure",
                            "REPORT_WRITTEN": "true"
                            if outcome in {"complete", "cancelled"}
                            else "",
                        },
                    ),
                    patch("sys.argv", args),
                ):
                    self.assertEqual(job_summary.publish(), 0)
                text = destination.read_text()
                self.assertEqual(text.count("# Configuration reconciliation"), 1)
                self.assertEqual(text.count("| /pawlocal/"), 54)
                if outcome != "complete":
                    self.assertIn("**INCOMPLETE**", text)
                if outcome in {"interrupted", "partial-file"}:
                    self.assertIn("Not recorded", text)
                    self.assertIn("acceptance unknown", text)
                    self.assertNotIn("None. No destination mutations", text)
                destination.unlink()

    def test_cleanup_exact_entrypoint_and_unknown_delete_outcomes(self):
        for environment in ("development", "production"):
            api = CleanupAPI()
            for name in cleanup.LEGACY_VARIABLES:
                api.variables[(environment, name)] = SENTINEL
            for name in cleanup.LEGACY_SECRETS:
                api.secrets[(environment, name)] = SENTINEL
            api.variables[(environment, "PAWLOCAL_DEPLOY_ADAPTER_PATH")] = (
                "ops/deployment-adapters/lightsail-dsql.sh"
            )
            github = module.GitHub("alanlima/pawlocal", SENTINEL, api)
            with (
                tempfile.TemporaryDirectory() as directory,
                patch.object(cleanup, "GitHub", return_value=github),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                path = Path(directory) / "summary"
                with patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(path)}):
                    self.assertEqual(
                        cleanup.main(
                            [
                                "--environment",
                                environment,
                                "--operation",
                                "legacy-cleanup",
                                "--confirmation",
                                f"CLEAN legacy {environment}",
                            ]
                        ),
                        0,
                    )
                text = path.read_text()
                self.assertEqual(
                    sum(
                        "| Deleted |" in line
                        for line in text.splitlines()
                        if line.startswith(f"| {environment} |")
                        and len(line.split("|")) == 7
                    ),
                    16,
                )
                self.assertNotIn("| /pawlocal/", text)
                self.assertNotIn(SENTINEL, text)
                self.assertIn("Exact cleanup targets", text)
        for failure in ("timeout", "readback"):
            api = CleanupAPI()
            target = cleanup.LEGACY_VARIABLES[0]
            api.variables[("development", target)] = SENTINEL
            api.variables[("development", "PAWLOCAL_DEPLOY_ADAPTER_PATH")] = (
                "ops/deployment-adapters/lightsail-dsql.sh"
            )

            def transport(request, timeout, failure=failure, api=api):
                if request.method == "DELETE":
                    if failure == "timeout":
                        raise URLError(SENTINEL)
                    from test_reconcile import Response

                    return Response(None)  # accepted but absence cannot be verified
                return api.__call__(request, timeout)

            selected = mappings("development")
            report = job_summary.Report("development", "audit", "all", "legacy-cleanup")
            report.cleanup_inventory(
                cleanup.cleanup_targets(selected, "development", "legacy-cleanup")
            )
            with self.assertRaises(module.ReconciliationError):
                cleanup.cleanup(
                    selected,
                    module.GitHub("alanlima/pawlocal", SENTINEL, transport),
                    "development",
                    "legacy-cleanup",
                    "CLEAN legacy development",
                    ROOT,
                    summary=report,
                )
            text = report.render()
            self.assertEqual(sum(r.status == "Failed" for r in report.rows.values()), 1)
            self.assertEqual(
                sum(r.status == "Not attempted" for r in report.rows.values()), 12
            )
            self.assertEqual(
                sum(r.status == "Already absent" for r in report.rows.values()), 3
            )
            self.assertIn(
                "acceptance unknown"
                if failure == "timeout"
                else "verification incomplete",
                text,
            )
            self.assertNotIn(SENTINEL, text)

    def test_workflow_always_publishes_without_credentials(self):
        import yaml

        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/reconcile-environment.yml").read_text()
        )
        job = workflow["jobs"]["reconcile"]
        publisher = job["steps"][-1]
        self.assertEqual(publisher["if"], "always()")
        self.assertNotIn("PAWLOCAL_CONFIG_GITHUB_TOKEN", publisher["env"])
        for step in job["steps"]:
            if step.get("id") in {"sync", "cleanup"}:
                self.assertEqual(
                    step["env"]["CONFIG_SUMMARY_PATH"],
                    publisher["env"]["CONFIG_SUMMARY_PATH"],
                )
        self.assertEqual(
            workflow["jobs"]["validate"]["steps"][-1]["if"], "failure() || cancelled()"
        )

    def test_fresh_atomic_replacement_and_failed_replacement_clears_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            report = self.report(mappings("development"))
            report.succeeded()
            with patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(path)}):
                report.write()
                report.result = "FAILED"
                report.write()
                text = path.read_text()
                self.assertEqual(text.count("# Configuration reconciliation"), 1)
                self.assertNotIn("**SUCCESS**", text)
                with (
                    patch.object(Path, "replace", side_effect=OSError(SENTINEL)),
                    self.assertRaises(OSError),
                ):
                    report.write()
                self.assertFalse(path.exists())
                self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_stale_complete_frame_after_failed_clear_is_not_current_evidence(self):
        for operation in ("reconcile", "legacy-cleanup"):
            with tempfile.TemporaryDirectory() as directory:
                report_path = Path(directory) / "private.md"
                published = Path(directory) / "published.md"
                env = {
                    "CONFIG_SUMMARY_PATH": str(report_path),
                    "GITHUB_STEP_SUMMARY": str(published),
                    "REPORT_WRITTEN": "",
                    "SYNC_OUTCOME": "failure",
                    "CLEANUP_OUTCOME": "failure",
                    "JOB_STATUS": "failure",
                }
                old = job_summary.Report("development", "audit", "all", operation)
                if operation == "reconcile":
                    old.inventory_for(
                        mappings("development") + mappings("production"),
                        mappings("development"),
                    )
                else:
                    old.cleanup_inventory(
                        cleanup.cleanup_targets(
                            mappings("development"), "development", operation
                        )
                    )
                for row in old.rows.values():
                    if row.status != "Not selected":
                        row.status = (
                            "Created" if operation == "reconcile" else "Deleted"
                        )
                        row.mutation = "verified"
                old.succeeded()
                with patch.dict(os.environ, env):
                    old.write()
                    with (
                        patch.object(
                            job_summary.Report, "clear", side_effect=OSError(SENTINEL)
                        ),
                        contextlib.redirect_stderr(io.StringIO()),
                    ):
                        result = (
                            module.main(["--environment", "development"])
                            if operation == "reconcile"
                            else cleanup.main(
                                [
                                    "--environment",
                                    "development",
                                    "--operation",
                                    operation,
                                    "--confirmation",
                                    "CLEAN legacy development",
                                ]
                            )
                        )
                    self.assertEqual(result, 1)
                    args = [
                        "summary",
                        "--environment",
                        "development",
                        "--mode",
                        "audit",
                        "--selection",
                        "all",
                        "--operation",
                        operation,
                    ]
                    with patch("sys.argv", args):
                        self.assertEqual(job_summary.publish(), 0)
                text = published.read_text()
                self.assertIn("**INCOMPLETE**", text)
                self.assertNotIn("**SUCCESS**", text)
                self.assertIn("Not recorded", text)
                self.assertNotIn("| Created | Variable comparison", text)
                self.assertNotIn(SENTINEL, text)

    def test_current_failed_report_is_published_without_losing_completed_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            private = Path(directory) / "report"
            published = Path(directory) / "published"
            output = Path(directory) / "step-outputs"
            report = self.report(mappings("development"))
            first = next(iter(report.rows.values()))
            first.status, first.mutation = "Created", "verified"
            env = {
                "CONFIG_SUMMARY_PATH": str(private),
                "GITHUB_STEP_SUMMARY": str(published),
                "GITHUB_OUTPUT": str(output),
                "SYNC_OUTCOME": "failure",
                "REPORT_WRITTEN": "true",
            }
            with patch.dict(os.environ, env):
                report.write()
                self.assertIn("summary_written=true", output.read_text())
                with patch(
                    "sys.argv",
                    [
                        "summary",
                        "--environment",
                        "development",
                        "--mode",
                        "enforce",
                        "--selection",
                        "all",
                        "--operation",
                        "reconcile",
                    ],
                ):
                    self.assertEqual(job_summary.publish(), 0)
            text = published.read_text()
            self.assertIn("**FAILED**", text)
            self.assertIn("| Created |", text)
            self.assertNotIn("**INCOMPLETE**", text)

    def test_publisher_preserves_inventory_and_destination_failure_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "published.md"
            args = ["summary", "--environment", "development", "--mode", "audit",
                    "--selection", "all", "--operation", "reconcile"]
            with (
                patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(Path(directory) / "absent"),
                                        "GITHUB_STEP_SUMMARY": str(destination)}),
                patch("sys.argv", args),
                patch.object(module, "load_mappings", side_effect=ValueError("configuration mapping schema invalid")),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                self.assertEqual(job_summary.publish(), 0)
            self.assertIn("ValueError: configuration mapping schema invalid", errors.getvalue())
            self.assertIn("**INCOMPLETE**", destination.read_text())
            self.assertNotIn("configuration mapping schema invalid", destination.read_text())
            with (
                patch.dict(os.environ, {"CONFIG_SUMMARY_PATH": str(Path(directory) / "absent"),
                                        "GITHUB_STEP_SUMMARY": str(destination)}),
                patch("sys.argv", args),
                patch("builtins.open", side_effect=PermissionError("summary destination permission denied")),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                self.assertEqual(job_summary.publish(), 1)
            self.assertIn("PermissionError: summary destination permission denied", errors.getvalue())

    def test_interrupted_cleanup_fallback_has_exact_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "published.md"
            args = [
                "summary",
                "--environment",
                "production",
                "--mode",
                "audit",
                "--selection",
                "all",
                "--operation",
                "destroy-cleanup",
            ]
            with (
                patch.dict(
                    os.environ,
                    {
                        "CONFIG_SUMMARY_PATH": str(Path(directory) / "absent"),
                        "GITHUB_STEP_SUMMARY": str(path),
                        "CLEANUP_OUTCOME": "cancelled",
                        "JOB_STATUS": "cancelled",
                    },
                ),
                patch("sys.argv", args),
            ):
                self.assertEqual(job_summary.publish(), 0)
            text = path.read_text()
            self.assertIn("Exact cleanup targets", text)
            self.assertNotIn("| /pawlocal/", text)
            self.assertIn("Not recorded", text)
            self.assertNotIn("None. No destination mutations", text)
            self.assertEqual(
                sum(
                    line.startswith("| production") and "| Not recorded |" in line
                    for line in text.splitlines()
                ),
                16,
            )


if __name__ == "__main__":
    unittest.main()
