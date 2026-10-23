import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / "ops/incident-response"
sys.path.insert(0, str(DIRECTORY))
SPEC = importlib.util.spec_from_file_location(
    "incident_gateway", DIRECTORY / "quota_gateway.py"
)
gateway = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gateway)
import test_incident_quota as quota_fixtures


class Response(io.BytesIO):
    status = 200


class GatewayTests(unittest.TestCase):
    def body(self, **changes):
        return {
            "model": "fixture-model",
            "reasoning": {"effort": "medium"},
            "service_tier": "default",
            "store": False,
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "fixture"}]}
            ],
            "tools": [
                {"type": "function", "name": "local", "parameters": {"type": "object"}}
            ],
            "stream": True,
        } | changes

    def fixture(self, count=1000):
        self.calls = []

        def upstream(suffix, body):
            self.calls.append((suffix, body))
            return Response(json.dumps({"input_tokens": count}).encode())

        now = time.time()
        return gateway.Gateway(
            quota_fixtures.QuotaTests().profile(),
            "upstream-secret",
            "x" * 32,
            now + 1200,
            upstream,
            clock=lambda: now,
        )

    def test_count_includes_full_input_and_tools_and_output_cap_is_enforced(self):
        process = self.fixture()
        admitted = process.admit(
            "Bearer " + "x" * 32,
            json.dumps(self.body(max_output_tokens=9999999)).encode(),
        )
        self.assertEqual(admitted["max_output_tokens"], 10000)
        self.assertEqual(self.calls[0][0], "/input_tokens")
        self.assertEqual(self.calls[0][1]["input"], self.body()["input"])
        self.assertEqual(self.calls[0][1]["tools"], self.body()["tools"])
        self.assertEqual(process.budget.outputs, 10000)

    def test_actual_pinned_cli_wire_shape_and_omitted_tier_are_supported(self):
        raw = (
            DIRECTORY.parents[1] / "tests/ci/fixtures/codex-0.163.0-request.json"
        ).read_bytes()
        process = self.fixture()
        admitted = process.admit("Bearer " + "x" * 32, raw)
        self.assertEqual(admitted["service_tier"], "default")
        self.assertEqual(admitted["max_output_tokens"], 10000)
        self.assertNotIn("client_metadata", admitted)
        self.assertNotIn("prompt_cache_key", admitted)

    def test_wrong_auth_deadline_and_count_failure_never_admit(self):
        for auth in ("Bearer upstream-secret", "", "Bearer " + "y" * 32):
            process = self.fixture()
            with self.subTest(auth=auth), self.assertRaises(gateway.Denied):
                process.admit(auth, json.dumps(self.body()).encode())
            self.assertEqual(self.calls, [])
        process = self.fixture()
        process.clock = lambda: process.deadline + 1
        with self.assertRaises(gateway.Denied):
            process.admit("Bearer " + "x" * 32, json.dumps(self.body()).encode())
        process = self.fixture(count=100001)
        with self.assertRaises(gateway.Denied):
            process.admit("Bearer " + "x" * 32, json.dumps(self.body()).encode())
        self.assertEqual(process.budget.requests, 0)

    def test_server_state_remote_tools_images_and_unapproved_profile_deny(self):
        cases = (
            {"previous_response_id": "resp_a"},
            {"store": True},
            {"model": "another"},
            {"service_tier": "priority"},
            {"reasoning": {"effort": "high"}},
            {"truncation": "auto"},
            {"tools": [{"type": "web_search"}]},
            {"tools": [{"type": "namespace", "tools": [{"type": "code_interpreter"}]}]},
            {"input": [{"type": "item_reference", "id": "stored"}]},
            {
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": "a",
                        "output": [{"type": "input_file", "file_id": "file_a"}],
                    }
                ]
            },
            {
                "input": [
                    {
                        "type": "custom_tool_call_output",
                        "call_id": "a",
                        "output": [
                            {"type": "input_image", "image_url": "https://untrusted"}
                        ],
                    }
                ]
            },
            {
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": "https://untrusted"}
                        ],
                    }
                ]
            },
        )
        for changed in cases:
            process = self.fixture()
            with self.subTest(changed=changed), self.assertRaises(gateway.Denied):
                process.admit(
                    "Bearer " + "x" * 32, json.dumps(self.body(**changed)).encode()
                )
            self.assertEqual(self.calls, [])

    def test_count_endpoint_failure_and_unknown_usage_are_not_retried(self):
        process = self.fixture()

        def uncertain(*_args):
            raise OSError("fixture timeout")

        process.upstream = uncertain
        with self.assertRaises(OSError):
            process.admit("Bearer " + "x" * 32, json.dumps(self.body()).encode())
        self.assertEqual(process.received, 1)
        self.assertEqual(process.budget.requests, 0)

    @unittest.skipUnless(
        os.name == "posix", "POSIX signal enforcement exercised in Ubuntu CI"
    )
    def test_absolute_alarm_terminates_blocked_http_header_read(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            profile.write_text(
                json.dumps(quota_fixtures.QuotaTests().profile().__dict__)
            )
            profile.chmod(0o600)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            deadline = int(time.time()) + 2
            started = time.monotonic()
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(DIRECTORY / "quota_gateway.py"),
                    "--profile",
                    str(profile),
                    "--deadline",
                    str(deadline),
                    "--port",
                    str(port),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                process.stdin.write(
                    json.dumps(
                        {"api_key": "fixture-key", "local_token": "x" * 32}
                    ).encode()
                    + b"\n"
                )
                process.stdin.flush()
                connection = None
                while time.monotonic() - started < 1:
                    try:
                        connection = socket.create_connection(
                            ("127.0.0.1", port), timeout=0.1
                        )
                        break
                    except OSError:
                        time.sleep(0.02)
                self.assertIsNotNone(connection)
                with connection:
                    connection.sendall(
                        b"POST /v1/responses HTTP/1.1\r\nAuthorization: Bearer "
                    )
                    self.assertEqual(process.wait(timeout=3), 124)
                self.assertLess(time.monotonic() - started, 3)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()


if __name__ == "__main__":
    unittest.main()
