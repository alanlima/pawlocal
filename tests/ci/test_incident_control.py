import copy
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
from control import LiveControl
from quota import Denied


class LiveControlTests(unittest.TestCase):
    def fixture(self):
        metadata = {
            "quota_issue": 456,
            "issue": 789,
            "alert": {"incident_key": "a" * 64},
        }
        rows = {
            "/issues/456": {
                "state": "open",
                "user": {"login": "alanlima"},
                "body": "<!-- pawlocal-oncall-quota:v1 -->",
            },
            "/issues/789": {
                "state": "open",
                "user": {"login": "github-actions[bot]"},
                "body": "<!-- pawlocal-incident:v1:" + "a" * 64 + " -->",
            },
        }
        return metadata, rows

    def test_live_ledger_or_incident_closure_and_owner_marker_change_stop(self):
        metadata, rows = self.fixture()
        LiveControl(rows.__getitem__, metadata, time.time() + 30).check()
        for path in rows:
            for change in (
                {"state": "closed"},
                {"user": {"login": "untrusted"}},
                {"body": "changed"},
            ):
                bad = copy.deepcopy(rows)
                bad[path].update(change)
                with self.subTest(path=path, change=change), self.assertRaises(Denied):
                    LiveControl(bad.__getitem__, metadata, time.time() + 30).check()

    def test_unknown_control_read_or_expired_clock_does_not_continue(self):
        metadata, _ = self.fixture()
        calls = []

        def read(path):
            calls.append(path)
            raise OSError("fixture outage")

        with self.assertRaises(OSError):
            LiveControl(read, metadata, time.time() + 30).check()
        self.assertEqual(calls, ["/issues/456"])
        calls.clear()
        with self.assertRaises(Denied):
            LiveControl(read, metadata, time.time() - 1).check()
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
