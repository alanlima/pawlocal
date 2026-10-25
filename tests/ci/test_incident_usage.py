import os
from unittest.mock import patch
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / 'ops/incident-response'
sys.path.insert(0, str(DIRECTORY))
from usage import Observation, UsageRecorder
from usage_summary import render, validated_report, validate_limits, LIMIT_FIELDS, PROFILE_FIELDS
import test_incident_quota as fixtures


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class UsageTests(unittest.TestCase):
    def response(self, **changes):
        return {'status': 'completed', 'usage': {'input_tokens': 100, 'output_tokens': 40, 'total_tokens': 140, 'input_tokens_details': {'cached_tokens': 50}, 'output_tokens_details': {'reasoning_tokens': 30}}, 'output': 'PRIVATE CONTENT', **changes}

    def test_json_and_sse_every_byte_boundary(self):
        raw = json.dumps(self.response()).encode()
        for streaming, payload in ((False, raw), (True, b'event: response.completed\r\ndata: ' + json.dumps({'type': 'response.completed', 'response': self.response()}).encode() + b'\r\n\r\n')):
            for size in (1, 2, 13, 16384):
                observer = Observation(streaming)
                for start in range(0, len(payload), size):
                    observer.feed(payload[start:start+size])
                self.assertEqual(observer.finish(), {'input_tokens':100, 'output_tokens':40, 'total_tokens':140, 'cached_tokens':50, 'reasoning_tokens':30, 'output_limit_reached':0})

    def test_missing_partial_malformed_and_duplicate_stay_unknown(self):
        values = (json.dumps({'status': {}, 'usage': {}}).encode(), b'{}', b'{"status":"completed","usage":', b'PRIVATE CONTENT', json.dumps(self.response(usage={'input_tokens': True})).encode(), json.dumps(self.response(usage={'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 4})).encode())
        for raw in values:
            observer = Observation(False)
            observer.feed(raw)
            self.assertIsNone(observer.finish())
        observer = Observation(True)
        observer.feed(b'data: {"type":"response.created","response":' + json.dumps(self.response()).encode() + b'}\n\n')
        self.assertIsNone(observer.finish())
        terminal = b'data: ' + json.dumps({'type':'response.completed', 'response':self.response()}).encode() + b'\n\n'
        observer.feed(terminal + terminal)
        self.assertIsNone(observer.finish())
        bounded = Observation(False)
        bounded.feed(b'x' * (16 * 1024 * 1024 + 1))
        self.assertEqual(len(bounded.buffer), 0)
        self.assertIsNone(bounded.finish())

    def test_optional_details_unknown_and_output_exhaustion(self):
        value = self.response(status='incomplete', incomplete_details={'reason':'max_output_tokens'})
        del value['usage']['input_tokens_details']
        observer = Observation(False)
        observer.feed(json.dumps(value).encode())
        self.assertIsNone(observer.finish()['cached_tokens'])
        self.assertEqual(observer.finish()['output_limit_reached'], 1)

    def test_atomic_numeric_snapshot_survives_unknown_failure_without_refund(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'gateway-usage.json'
            recorder = UsageRecorder(path)
            recorder.reserve(100, 5000)
            recorder.failure(True)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['requests'][0], {'counted_input':100, 'output_cap':5000, 'actual':None})
            self.assertEqual((saved['failures'], saved['exhaustions']), (1,1))
            self.assertIsNotNone(validated_report(saved))
            observer = Observation(False)
            observer.feed(json.dumps(self.response()).encode())
            recorder.observed(observer.finish())
            saved = json.loads(path.read_text())
            self.assertNotIn('PRIVATE', path.read_text())
            self.assertFalse(path.with_suffix('.tmp').exists())
            self.assertEqual(saved['requests'][0]['output_cap'], 5000)

    def test_aggregate_uses_full_two_role_limits_and_unknown_job_is_not_zero(self):
        limits = {key: getattr(fixtures.QuotaTests().profile(), key) for key in ('requests_per_role','input_per_request','output_per_request','input_per_role','output_per_role','input_rate','output_rate','monthly_runs','monthly_microdollars','model','effort','service_tier')}
        recorder = UsageRecorder()
        recorder.reserve(100, 5000)
        observer = Observation(False)
        observer.feed(json.dumps(self.response()).encode())
        recorder.observed(observer.finish())
        text = render({'fixer':recorder.snapshot(), 'reviewer':None}, limits, {'reviewer':'skipped'})
        self.assertIn('140 / 440,000', text)
        self.assertIn('partial; total unknown', text)
        self.assertIn('reviewer (skipped; report unavailable)', text)
        self.assertIn('5,100 / 440,000', text)
        self.assertIn('effective output allowance 5,000', text)
        self.assertIn('Remaining monthly balance requires the protected ledger', text)
        self.assertNotIn('PRIVATE', text)
        recorder.failure(True)
        recorder.reserve(100, 5000)
        text = render({'fixer':recorder.snapshot()}, limits)
        self.assertIn('1 quota denials', text)
        self.assertIn('total unknown', text)

    def test_unlimited_spending_roundtrips_and_renders_in_both_summaries(self):
        profile = fixtures.QuotaTests().profile(monthly_microdollars=None)
        limits = {name: getattr(profile, name) for name in LIMIT_FIELDS + PROFILE_FIELDS}
        self.assertEqual(validate_limits(limits), limits)
        for preview in (True, False):
            text = render({'fixer': None, 'reviewer': None}, limits, preview=preview)
            self.assertIn('Unlimited', text)
            self.assertIn('20', text)
            self.assertNotIn('unknown limit', text)
        for value in (False, -1, 0, 'unlimited', []):
            self.assertIsNone(validate_limits(limits | {'monthly_microdollars': value}))
        self.assertIsNone(validate_limits({key: value for key, value in limits.items() if key != 'monthly_microdollars'}))

    def test_reporting_cli_survives_missing_stats_and_expired_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trusted = root / 'oncall-trusted'
            trusted.mkdir()
            profile = fixtures.QuotaTests().profile().__dict__ | {'expires_at':'2000-01-01T00:00:00Z'}
            (trusted / 'profile.json').write_text(json.dumps(profile))
            summary = root / 'summary.md'
            outputs = root / 'outputs'
            environment = dict(os.environ, RUNNER_TEMP=str(root), GITHUB_STEP_SUMMARY=str(summary), GITHUB_OUTPUT=str(outputs), INCIDENT_DEADLINE='1')
            result = subprocess.run([sys.executable, str(DIRECTORY / 'usage_summary.py'), 'fixer'], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('total unknown',summary.read_text())
            self.assertIn('fixture-model',summary.read_text())
            self.assertIn('usage=null',outputs.read_text())
            self.assertNotIn('expires_at',outputs.read_text())

    def test_no_admission_and_untrusted_invalid_reports(self):
        text = render({'fixer':None,'reviewer':None},None,admitted=False)
        self.assertIn('No model admission recorded',text)
        preview = render({'fixer':None,'reviewer':None},None,admitted=False,preview=True)
        self.assertNotIn('0 /', preview)
        self.assertNotIn('Provider usage estimate', preview)
        self.assertNotIn('** 0 /', text)
        self.assertIn('admission preview', preview)
        self.assertIn('unknown limit',text)
        for value in ({'PRIVATE':'payload'}, {'version':1,'requests':[],'failures':False,'exhaustions':0}, {'version':1,'requests':[{'counted_input':1,'output_cap':3,'actual':{'content':'PRIVATE'}}],'failures':0,'exhaustions':0}):
            self.assertIsNone(validated_report(value))
            self.assertNotIn('PRIVATE',render({'fixer':value},None))


if __name__ == '__main__':
    unittest.main()
