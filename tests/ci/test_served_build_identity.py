"""Exercise release footer verification, including disabled-telemetry releases."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ServedBuildIdentityTests(unittest.TestCase):
    def test_expected_footer_required_and_local_or_stale_footer_rejected(self):
        script = r"""
import assert from 'node:assert/strict';
import { verifyServedBuildIdentity } from MODULE;
const commit = 'a'.repeat(40), time = '2026-10-26T01:23:45Z';
const expected = 'BUILD aaaaaaa \u00b7 2026-10-26 01:23 UTC';
function page(text) {
  return {getByRole: role => {
    assert.equal(role, 'contentinfo');
    return {getByText: (expected, options) => {
      assert.equal(options.exact, true);
      return {waitFor: async ({state}) => {
        assert.equal(state, 'visible');
        if (text !== expected) throw new Error('Expected footer not visible');
      }};
    }};
  }};
}
await verifyServedBuildIdentity(page(expected), commit, time);
for (const footer of ['BUILD local', 'BUILD bbbbbbb \u00b7 2026-10-26 01:23 UTC', 'BUILD aaaaaaa \u00b7 2026-10-25 01:23 UTC']) {
  await assert.rejects(verifyServedBuildIdentity(page(footer), commit, time));
}
for (const [sha, timestamp] of [[undefined,time],['local',time],[commit,undefined],[commit,'bad'],[commit,'2026-10-26T01:23:45+10:00']]) {
  await assert.rejects(verifyServedBuildIdentity(page(expected), sha, timestamp));
}
""".replace('MODULE', json.dumps((ROOT / 'ops/configuration/verify-served-build-identity.mjs').as_uri()))
        result = subprocess.run(['node', '--input-type=module', '-e', script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_served_verification_enforces_footer_before_sign_in(self):
        source = (ROOT / 'ops/configuration/verify-served-auth.mjs').read_text(encoding='utf-8')
        self.assertIn('await verifyServedBuildIdentity(page, process.env.SERVED_RELEASE_COMMIT, process.env.VITE_APP_BUILD_TIME)', source)
        self.assertLess(source.index('await verifyServedBuildIdentity('), source.index('const [authorization]'))
