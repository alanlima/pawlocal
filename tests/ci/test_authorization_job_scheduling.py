"""Regression for GitHub job skip propagation, including transitive ancestors.

GitHub implicitly adds success() unless an if expression contains a status
function. Model that rule explicitly rather than evaluating route predicates
alone: https://docs.github.com/actions/reference/workflows-and-actions/expressions#status-check-functions
This is a scheduling contract test, not a substitute for a hosted workflow run.
"""

import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def dependencies(job):
    value = job.get("needs", [])
    return [value] if isinstance(value, str) else value


def schedule(jobs, route="ordinary", outcomes=None, cancel_before=None):
    outcomes = outcomes or {}
    results = {}

    def ancestors(name):
        return {parent for direct in dependencies(jobs[name])
                for parent in ({direct} | ancestors(direct))}

    for name, job in jobs.items():
        expression = job.get("if", "true").removeprefix("${{ ").removesuffix(" }}")
        # needs contains direct dependencies only; implicit success also observes
        # skipped transitive dependencies, even if an intermediate always job ran.
        cancelled = cancel_before is not None and list(jobs).index(name) >= list(jobs).index(cancel_before)
        success = not cancelled and all(results[parent] == "success" for parent in ancestors(name))
        has_status = re.search(r"\b(always|success|failure|cancelled)\s*\(", expression)
        expression = re.sub(
            r"needs\.([\w-]+)\.(result|outputs\.route|outputs\.environment)",
            lambda match: repr(results[match[1]] if match[2] == "result" else
                               route if match[2] == "outputs.route" else
                               "development" if route == "incident" else ""),
            expression,
        )
        expression = expression.replace("inputs.incident_environment", repr("development" if route == "incident" else ""))
        expression = expression.replace("&&", " and ").replace("||", " or ")
        expression = re.sub(r"!(?!=)", "not ", expression)
        allowed = eval(expression, {"__builtins__": {}}, {
            "always": lambda: True, "success": lambda: success, "true": True,
            "cancelled": lambda: cancelled,
        })
        results[name] = outcomes.get(name, "success") if allowed and (has_status or success) else "skipped"
    return results


class AuthorizationSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load((ROOT / ".github/workflows/change-authorization.yml").read_text())["jobs"]

    def test_ordinary_route_survives_skipped_incident_resolver(self):
        result = schedule(self.jobs)
        self.assertEqual(result["incident-enforcement"], "skipped")
        for name in ("classify", "reset-status", "ordinary-approval"):
            self.assertEqual(result[name], "success", name)
        self.assertEqual(result["incident-authorize"], "skipped")
        self.assertEqual(self.jobs["ordinary-approval"]["environment"], "ordinary-change-approval")
        self.assertEqual(self.jobs["ordinary-approval"]["env"]["PAWLOCAL_ONCALL_ENFORCE_GUARDS"], "true")

    def test_old_implicit_success_conditions_reproduce_original_skip(self):
        self.jobs["reset-status"].pop("if")
        self.jobs["ordinary-approval"]["if"] = "needs.classify.outputs.route == 'ordinary'"
        result = schedule(self.jobs)
        self.assertEqual(result["classify"], "success")
        self.assertEqual(result["reset-status"], "skipped")
        self.assertEqual(result["ordinary-approval"], "skipped")

    def test_incident_route_runs_only_its_authorizer(self):
        result = schedule(self.jobs, "incident")
        self.assertEqual(result["incident-enforcement"], "success")
        self.assertEqual(result["incident-authorize"], "success")
        self.assertEqual(result["ordinary-approval"], "skipped")

    def test_global_cancellation_stops_credential_jobs_after_successful_prerequisites(self):
        for route in ("ordinary", "incident"):
            for target in ("reset-status", "incident-authorize", "ordinary-approval"):
                with self.subTest(route=route, target=target):
                    result = schedule(self.jobs, route, cancel_before=target)
                    for dependency in dependencies(self.jobs[target]):
                        self.assertEqual(result[dependency], "success")
                    self.assertEqual(result[target], "skipped")

    def test_failed_or_cancelled_prerequisites_never_reach_authorization_writes(self):
        for route in ("ordinary", "incident"):
            for failed in ("incident-origin", "incident-enforcement", "classify", "reset-status"):
                if failed == "incident-enforcement" and route == "ordinary":
                    continue
                for outcome in (("failure", "cancelled") if failed == "incident-enforcement" else ("failure", "cancelled", "skipped")):
                    with self.subTest(route=route, failed=failed, outcome=outcome):
                        result = schedule(self.jobs, route, {failed: outcome})
                        self.assertEqual(result["incident-authorize"], "skipped")
                        self.assertEqual(result["ordinary-approval"], "skipped")
                        if failed != "reset-status":
                            self.assertEqual(result["reset-status"], "skipped")


class ProductionSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.jobs = yaml.safe_load((ROOT / ".github/workflows/deploy-production.yml").read_text())["jobs"]

    def test_ordinary_and_incident_release_reach_real_verification(self):
        for route in ("ordinary", "incident"):
            with self.subTest(route=route):
                result = schedule(self.jobs, route)
                self.assertEqual(result["incident-enforcement"], "skipped" if route == "ordinary" else "success")
                for name in ("workflow-binding", "terraform-production", "verify-production"):
                    self.assertEqual(result[name], "success", name)
        self.assertEqual(self.jobs["verify-production"]["environment"], "production")
        self.assertTrue(self.jobs["terraform-production"]["uses"].endswith("/terraform-environment.yml"))

    def test_old_default_conditions_reproduce_ordinary_release_skip(self):
        for name in ("terraform-production", "verify-production"):
            self.jobs[name].pop("if")
        result = schedule(self.jobs)
        self.assertEqual(result["workflow-binding"], "success")
        self.assertEqual(result["terraform-production"], "skipped")
        self.assertEqual(result["verify-production"], "skipped")

    def test_global_cancellation_stops_release_jobs_after_successful_prerequisites(self):
        for route in ("ordinary", "incident"):
            for target in ("terraform-production", "verify-production"):
                with self.subTest(route=route, target=target):
                    result = schedule(self.jobs, route, cancel_before=target)
                    for dependency in dependencies(self.jobs[target]):
                        self.assertEqual(result[dependency], "success")
                    self.assertEqual(result[target], "skipped")

    def test_failed_cancelled_or_skipped_required_results_stop_later_release_jobs(self):
        for route in ("ordinary", "incident"):
            for failed in ("incident-enforcement", "workflow-binding", "terraform-production"):
                if failed == "incident-enforcement" and route == "ordinary":
                    continue
                for outcome in (("failure", "cancelled") if failed == "incident-enforcement" else ("failure", "cancelled", "skipped")):
                    with self.subTest(route=route, failed=failed, outcome=outcome):
                        result = schedule(self.jobs, route, {failed: outcome})
                        self.assertEqual(result["verify-production"], "skipped")
                        if failed != "terraform-production":
                            self.assertEqual(result["terraform-production"], "skipped")
