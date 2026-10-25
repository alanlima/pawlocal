import os
from unittest.mock import patch
import io
import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops/incident-response"))
import protection


class File:
    def __init__(self, permissions=None):
        self.value = {
            "token": "fixture-not-real-token-00000000",
            "repository_id": 1423024931,
            "permissions": permissions or {"administration": "read"},
        }

    def is_symlink(self):
        return False

    def stat(self):
        return SimpleNamespace(st_mode=0o600, st_uid=7)

    def read_bytes(self):
        return json.dumps(self.value).encode()


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, repo_status=200, branch_status=404):
        self.repo_status, self.branch_status = repo_status, branch_status
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        status = (
            self.repo_status
            if request.full_url == protection.ORIGIN
            else self.branch_status
        )
        if status != 200:
            raise urllib.error.HTTPError(
                request.full_url, status, "fixture", None, None
            )
        return Response(
            json.dumps({"id": 1423024931, "full_name": "alanlima/pawlocal"}).encode()
        )


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class ProtectionTests(unittest.TestCase):
    def check(self, opener, path=None):
        with patch.object(protection.os, "getuid", return_value=7, create=True):
            protection.classic_absent(
                time.time() + 30, path=path or File(), opener=opener
            )

    def test_absence_requires_exact_admin_read_capability_and_proved_repo(self):
        opener = Opener()
        self.check(opener)
        self.assertEqual(
            opener.calls,
            [protection.ORIGIN, protection.ORIGIN + "/branches/main/protection"],
        )

    def test_permission_hidden_repo_404_is_never_absence(self):
        opener = Opener(repo_status=404)
        with self.assertRaises(protection.Denied):
            self.check(opener)
        self.assertEqual(opener.calls, [protection.ORIGIN])

    def test_missing_or_write_capability_rejected_without_network(self):
        for permissions in (
            {"contents": "read"},
            {"administration": "write"},
            {"administration": "read", "contents": "write"},
        ):
            opener = Opener()
            with (
                self.subTest(permissions=permissions),
                self.assertRaises(protection.Denied),
            ):
                self.check(opener, File(permissions))
            self.assertEqual(opener.calls, [])

    def test_existing_classic_policy_or_branch_permission_failure_denies(self):
        for status in (200, 403, 429, 500):
            with self.subTest(status=status), self.assertRaises(protection.Denied):
                self.check(Opener(branch_status=status))


if __name__ == "__main__":
    unittest.main()
