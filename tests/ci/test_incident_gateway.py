import contextlib
import http.client
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
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
        self.assertEqual(admitted["max_output_tokens"], 5000)
        self.assertEqual(self.calls[0][0], "/input_tokens")
        self.assertEqual(self.calls[0][1]["input"], self.body()["input"])
        self.assertEqual(self.calls[0][1]["tools"], self.body()["tools"])
        self.assertEqual(process.budget.outputs, 5000)

    def test_actual_pinned_cli_wire_shape_and_omitted_tier_are_supported(self):
        raw = (
            DIRECTORY.parents[1] / "tests/ci/fixtures/codex-0.163.0-request.json"
        ).read_bytes()
        process = self.fixture()
        admitted = process.admit("Bearer " + "x" * 32, raw)
        self.assertEqual(admitted["service_tier"], "default")
        self.assertEqual(admitted["max_output_tokens"], 5000)
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

    def test_live_stop_prevents_token_count_or_inference(self):
        process = self.fixture()

        def stopped():
            raise gateway.Denied("fixture owner stop")

        process.control = stopped
        with self.assertRaises(gateway.Denied):
            process.admit("Bearer " + "x" * 32, json.dumps(self.body()).encode())
        self.assertEqual(self.calls, [])
        self.assertEqual(process.budget.requests, 0)

    @contextlib.contextmanager
    def http_gateway(self, upstream, profile=None):
        process = self.fixture()
        if profile is not None:
            process.profile = profile
            process.budget = gateway.RequestBudget(profile)
        process.clock = time.time
        process.upstream = upstream
        events = []
        process.diagnostic = events.append
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        thread = threading.Thread(
            target=gateway.serve, args=(process, port), daemon=True
        )
        thread.start()
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.01)
        try:
            yield process, events, port
        finally:
            process.deadline = 0
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def post(self, port, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "POST",
            "/v1/responses",
            json.dumps(body or self.body()),
            {"Authorization": "Bearer " + "x" * 32},
        )
        response = connection.getresponse()
        result = (response.status, response.read())
        connection.close()
        return result

    def test_http_local_quota_is_403_and_failed_inference_keeps_full_reservation(self):
        calls = []

        def upstream(suffix, body):
            calls.append(suffix)
            if suffix:
                return Response(b'{"input_tokens":1000}')
            raise OSError("fixture secret body must not be logged")

        profile = quota_fixtures.QuotaTests().profile(
            output_per_request=16000, output_per_role=32000
        )
        with self.http_gateway(upstream, profile) as (process, events, port):
            for _ in range(4):
                self.assertEqual(self.post(port)[0], 502)
            status, raw = self.post(port)
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(raw)["error"]["origin"], "local")
            self.assertEqual(process.budget.outputs, 32000)
            self.assertEqual(calls.count(""), 4)
            self.assertEqual(events[-1]["reason"], "request count quota exhausted")
            self.assertNotIn("fixture secret body", json.dumps(events))

    def test_http_upstream_status_and_id_are_distinct_from_local_and_transport(self):
        for stage in ("input_token_count", "inference"):
            for code in (400, 401, 429, 500):
                calls = []

                def upstream(suffix, body, calls=calls, stage=stage, code=code):
                    calls.append(suffix)
                    if suffix and stage == "inference":
                        return Response(b'{"input_tokens":1000}')
                    raise urllib.error.HTTPError(
                        "https://fixture",
                        code,
                        "secret response",
                        {"x-request-id": "req_fixture"},
                        io.BytesIO(
                            b'{"error":{"code":"insufficient_quota","type":"insufficient_quota","message":"secret response body"}}'
                        ),
                    )

                with (
                    self.subTest(stage=stage, code=code),
                    self.http_gateway(upstream) as (process, events, port),
                ):
                    status, raw = self.post(port)
                    event = json.loads(raw)["error"]
                    self.assertEqual(status, code)
                    self.assertEqual(
                        (
                            event["origin"],
                            event["stage"],
                            event["upstream_status"],
                            event["request_id"],
                        ),
                        ("openai", stage, code, "req_fixture"),
                    )
                    self.assertEqual(
                        len(calls), 1 if stage == "input_token_count" else 2
                    )
                    self.assertEqual(
                        process.budget.requests,
                        0 if stage == "input_token_count" else 1,
                    )
                    self.assertEqual(event["upstream_code"], "insufficient_quota")
                    self.assertEqual(event["upstream_type"], "insufficient_quota")
                    self.assertNotIn("secret", raw.decode())
                    self.assertEqual(events[-1], event)

    def test_http_schema_and_live_control_denial_prevent_upstream(self):
        def upstream(*_):
            self.fail("Denied request reached upstream")

        with self.http_gateway(upstream) as (process, events, port):
            status, _ = self.post(port, self.body(store=True))
            self.assertEqual(status, 403)
            self.assertEqual(events[-1]["stage"], "request_validation")

            def stopped():
                raise gateway.Denied("live incident lease closed or changed")

            process.control = stopped
            self.assertEqual(self.post(port)[0], 403)
            self.assertEqual(events[-1]["stage"], "live_control")
            self.assertEqual(process.budget.outputs, 0)

    def test_http_first_input_denial_preserves_exact_accounting_and_no_payloads(self):
        for counts, reason, reserved in (
            ([100001], "per-request input quota exhausted", 0),
            ([100000, 100000, 1], "cumulative input quota exhausted", 2),
        ):
            pending = iter(counts)
            inference = []

            def upstream(suffix, body, pending=pending, inference=inference):
                if suffix:
                    return Response(
                        json.dumps({"input_tokens": next(pending)}).encode()
                    )
                inference.append(body)
                response = Response(b"{}")
                response.headers = {"Content-Type": "application/json"}
                return response

            with (
                self.subTest(reason=reason),
                self.http_gateway(upstream) as (_process, events, port),
            ):
                sensitive = self.body(
                    input="private-model-text", instructions="private-instructions"
                )
                for _ in range(reserved):
                    self.assertEqual(self.post(port, sensitive)[0], 200)
                status, raw = self.post(port, sensitive)
                self.assertEqual(status, 403)
                event = json.loads(raw)["error"]
                self.assertEqual(event["reason"], reason)
                self.assertEqual(event["counted_input_tokens"], counts[-1])
                self.assertEqual(event["requests_received"], reserved + 1)
                self.assertEqual(event["requests_reserved"], reserved)
                self.assertEqual(event["input_tokens_reserved"], reserved * 100000)
                self.assertEqual(event["output_tokens_reserved"], reserved * 5000)
                self.assertEqual(event["limits"]["input_per_request"], 100000)
                self.assertEqual(event["limits"]["input_per_role"], 200000)
                self.assertEqual(event["limits"]["effective_output_per_request"], 5000)
                self.assertEqual(len(inference), reserved)
                self.assertEqual(len(events), reserved + 1)
                self.assertEqual(events[-1], event)
                for count, success in enumerate(events[:-1], 1):
                    self.assertEqual(success["event"], "oncall_quota_reserved")
                    self.assertEqual(success["counted_input_tokens"], 100000)
                    self.assertEqual(success["requests_reserved"], count)
                    self.assertEqual(success["input_tokens_reserved"], count * 100000)
                    self.assertEqual(success["output_tokens_reserved"], count * 5000)
                serialized = json.dumps(events)
                for secret in (
                    "private-model-text",
                    "private-instructions",
                    "upstream-secret",
                    "x" * 32,
                    "Authorization",
                ):
                    self.assertNotIn(secret, serialized)

    def test_first_refusal_remains_visible_with_64_maximum_accounting_records(self):
        profile = quota_fixtures.QuotaTests().profile(
            model="x" * 160,
            requests_per_role=64,
            input_per_request=250000,
            input_per_role=16000000,
            output_per_request=64000,
            output_per_role=4096000,
            input_rate=10**12,
            output_rate=10**12,
        )

        def upstream(suffix, body):
            if suffix:
                return Response(b'{"input_tokens":250000}')
            response = Response(b"{}")
            response.headers = {"Content-Type": "application/json"}
            return response

        with self.http_gateway(upstream, profile) as (_process, events, port):
            for _ in range(64):
                self.assertEqual(
                    self.post(port, self.body(model=profile.model))[0], 200
                )
            self.assertEqual(self.post(port, self.body(model=profile.model))[0], 403)
            self.assertEqual(len(events), 65)
            # Worst-case printable body-counter width, without 256 MiB of test payloads.
            records = [
                event | {"request_body_bytes": gateway.MAX_BODY} for event in events
            ]
            raw = "".join(json.dumps(event) + "\n" for event in records).encode()
            self.assertLessEqual(len(raw), 65536)
            self.assertEqual(events[-1]["reason"], "request count quota exhausted")
            self.assertEqual(events[-1]["requests_reserved"], 64)
            self.assertEqual(events[-1]["output_tokens_reserved"], 4096000)

    def test_http_body_limit_and_reset_count_never_reuse_previous_request_input(self):
        def upstream(suffix, body):
            if suffix:
                return Response(b'{"input_tokens":1000}')
            response = Response(b"{}")
            response.headers = {"Content-Type": "application/json"}
            return response

        with self.http_gateway(upstream) as (_process, events, port):
            self.assertEqual(self.post(port)[0], 200)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.putrequest("POST", "/v1/responses")
            connection.putheader("Authorization", "Bearer " + "x" * 32)
            connection.putheader("Content-Length", str(gateway.MAX_BODY + 1))
            connection.endheaders()
            response = connection.getresponse()
            event = json.loads(response.read())["error"]
            self.assertEqual(response.status, 403)
            connection.close()
            self.assertEqual(event["reason"], "request body bound exceeded")
            self.assertIsNone(event["counted_input_tokens"])
            self.assertEqual(event["request_body_bytes"], gateway.MAX_BODY + 1)
            self.assertEqual(event["limits"]["request_body_bytes"], gateway.MAX_BODY)
            self.assertEqual(
                (event["requests_received"], event["requests_reserved"]), (1, 1)
            )
            self.assertEqual(event["input_tokens_reserved"], 1000)
            self.assertEqual(events[-1], event)

    def test_live_control_http_error_identifies_github_not_openai(self):
        def upstream(*_):
            self.fail("Control denial must not reach OpenAI")

        with self.http_gateway(upstream) as (process, events, port):

            def stopped():
                raise urllib.error.HTTPError(
                    "https://api.github.com/fixture",
                    403,
                    "secret",
                    {},
                    io.BytesIO(b"{}"),
                )

            process.control = stopped
            status, _ = self.post(port)
            self.assertEqual(status, 403)
            self.assertEqual(
                (events[0]["origin"], events[0]["stage"]), ("github", "live_control")
            )

    def test_stream_failure_has_no_second_http_status_and_retains_charge(self):
        class BrokenResponse(Response):
            def __init__(self, raw):
                super().__init__(raw)
                self.headers = {"Content-Type": "text/event-stream"}

            def read(self, size=-1):
                if self.tell():
                    raise OSError("secret transport details")
                return super().read(size)

        def upstream(suffix, body):
            return (
                Response(b'{"input_tokens":1000}')
                if suffix
                else BrokenResponse(b"data: fixture\n\n")
            )

        with self.http_gateway(upstream) as (process, events, port):
            status, raw = self.post(port)
            self.assertEqual(status, 200)
            self.assertEqual(raw, b"data: fixture\n\n")
            self.assertTrue(events[-1]["response_started"])
            self.assertEqual(events[-1]["origin"], "transport")
            self.assertEqual(process.budget.outputs, 5000)

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
                        {
                            "api_key": "fixture-key",
                            "local_token": "x" * 32,
                            "github_token": "fixture-only-no-actual-key",
                            "metadata": {
                                "quota_issue": 456,
                                "issue": 789,
                                "alert": {"incident_key": "a" * 64},
                            },
                        }
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
