"""Neutral evidence boundaries, read-only transport, and incident adapter parity."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import test_incident_admission as fixtures
import admission
import quota
from test_production_rollback import History

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))
import release_evidence as evidence

ROOT = Path(__file__).resolve().parents[2]


class ReleaseBoundaryTests(unittest.TestCase):
    def test_trusted_incident_consumers_import_from_checkout_outside_working_directory(self):
        script = f'''
import pathlib, sys
sys.path.insert(0, {str(ROOT / 'ops/incident-response')!r})
import admission, publisher, promotion, job, finalize, quota
assert admission.Denied is quota.Denied
assert pathlib.Path(admission.release_evidence.__file__).resolve() == pathlib.Path({str(ROOT / 'ops/release_evidence.py')!r}).resolve()
print('Trusted incident checkout imports passed')
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-I", "-c", script], cwd=directory,
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rollback_imports_without_any_incident_module_and_keeps_environment(self):
        script = r'''
import importlib.abc, importlib.util, os, pathlib, sys
blocked = {'admission','quota','enforcement','control','deadline','diagnostics','protection','quota_gateway','settings'}
class RejectIncidentImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(part in blocked for part in fullname.split('.')):
            raise AssertionError('Incident dependency imported: ' + fullname)
sys.meta_path.insert(0, RejectIncidentImports())
before = dict(os.environ)
spec = importlib.util.spec_from_file_location('rollback', pathlib.Path('ops/rollback-production.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert dict(os.environ) == before
assert not blocked.intersection(sys.modules)
assert module.GitHub.__module__ == 'release_evidence'
assert module.verified_record.__module__ == 'release_evidence'
print('Independent release evidence import passed')
'''
        result = subprocess.run([sys.executable, "-I", "-c", script], cwd=ROOT, capture_output=True, text=True,
                                env=os.environ | {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "false"}, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_verifier_is_strict_independent_of_incident_switch(self):
        for mode in ("true", "false", "invalid"):
            fake = History()
            fake.records[0]["payload"]["evidence_validated"] = False
            with patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": mode}), self.assertRaises(evidence.ReleaseEvidenceError):
                evidence.deployed_release(fake, "production", require_telemetry=False)

    @patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "true"})
    def test_incident_adapter_preserves_results_errors_and_telemetry_policy(self):
        fake = History()
        self.assertEqual(admission.deployed_release(fake, "production"), evidence.deployed_release(fake, "production"))
        fake.records[0]["payload"]["telemetry_enabled"] = False
        with self.assertRaises(quota.Denied) as caught:
            admission.deployed_release(fake, "production")
        self.assertIs(type(caught.exception), quota.Denied)
        self.assertIsInstance(caught.exception.__cause__, evidence.ReleaseEvidenceError)
        self.assertIsNotNone(evidence.deployed_release(fake, "production", require_telemetry=False))

    @patch.dict(os.environ, {"PAWLOCAL_ONCALL_ENFORCE_GUARDS": "false"})
    def test_incident_disabled_mode_retains_minimal_decode_and_no_release_api_calls(self):
        fake = fixtures.FakeGitHub()
        minimal = {"id": 4, "sha": "a" * 40, "payload": {
            "release_commit": "a" * 40, "backend_image_digest": "sha256:" + "b" * 64, "workflow_run_id": 7,
        }}
        with patch.object(fake, "request", side_effect=AssertionError("unexpected strict policy read")):
            result = admission.verified_record(fake, minimal, "production")
        self.assertEqual(result, {"affected_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64,
                                  "deployment_id": 4, "deployment_run": 7})
        with self.assertRaises(evidence.ReleaseEvidenceError):
            evidence.verified_record(fake, minimal, "production", require_telemetry=False)
        minimal["payload"]["release_commit"] = "bad"
        with self.assertRaises(quota.Denied):
            admission.verified_record(fake, minimal, "production")


class ReadOnlyClientTests(unittest.TestCase):
    def client(self, body=b"[]", status=200, deadline=None):
        response = Mock(status=status)
        response.read.return_value = body
        opener = Mock()
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        return evidence.GitHub("test-token", deadline or time.time() + 60, opener), opener

    def test_only_fixed_release_get_paths_accepted(self):
        client, opener = self.client()
        for path in ("/deployments?environment=production", "/deployments/12/statuses?per_page=100",
                     "/actions/runs/12", "/actions/runs/12/attempts/2"):
            self.assertEqual(client.request("GET", path), [])
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, evidence.GITHUB + path)
            self.assertEqual(request.method, "GET")
        for method, path, data in (("POST", "/deployments", None), ("PATCH", "/issues/1", None),
                                   ("GET", "/issues/1", None), ("GET", "https://example.test", None),
                                   ("GET", "/deployments/1/../issues", None), ("GET", "/deployments", {})):
            with self.subTest(method=method, path=path), self.assertRaises(evidence.ReleaseEvidenceError):
                client.request(method, path, data)

    def test_response_status_size_json_redirect_and_deadline_fail_closed(self):
        for body, status in ((b"[]", 201), (b"x" * (2 * 1024 * 1024 + 1), 200),
                             (b'{"duplicate":1,"duplicate":2}', 200), (b"[NaN]", 200), (b"broken-json", 200)):
            client, _opener = self.client(body, status)
            with self.subTest(status=status, size=len(body)), self.assertRaises(evidence.ReleaseEvidenceError):
                client.request("GET", "/deployments")
        client, opener = self.client(deadline=time.time() - 1)
        with self.assertRaises(evidence.ReleaseEvidenceError):
            client.request("GET", "/deployments")
        opener.open.assert_not_called()
        with self.assertRaises(evidence.ReleaseEvidenceError):
            evidence.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.test")

    def test_pagination_is_bounded_and_lists_required(self):
        for body, maximum in ((b"{}", 1), (json.dumps([{}] * 100).encode(), 2)):
            client, opener = self.client(body)
            with self.assertRaises(evidence.ReleaseEvidenceError):
                client.pages("/deployments", maximum=maximum)
            self.assertLessEqual(opener.open.call_count, maximum)
        for maximum in (0, 11, True, "10"):
            client, opener = self.client()
            with self.assertRaises(evidence.ReleaseEvidenceError):
                client.pages("/deployments", maximum=maximum)
            opener.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
