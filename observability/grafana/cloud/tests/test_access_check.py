import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY))
try:
    spec = importlib.util.spec_from_file_location(
        "grafana_access", DIRECTORY / "access_check.py"
    )
    access = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(access)
finally:
    sys.path.pop(0)

STACK = "https://teststack.grafana.net"
SM = "https://synthetic-monitoring-api-test-region.grafana.net"
CREDENTIALS = {
    name: "private-sentinel-" + kind for kind, name in access.SECRETS.items()
}


class Fake:
    def __init__(self):
        self.allowed = set()
        self.calls = []
        self.fail = False
        self.otlp = "https://otlp-gateway-test-region.grafana.net/otlp"

    def request(self, method, url, token, **kwargs):
        self.calls.append((method, url, token, kwargs))
        if self.fail:
            raise RuntimeError("private-response-sentinel " + token)
        if url == "https://grafana.com/api/instances/teststack":
            return {
                "id": 42,
                "slug": "teststack",
                "url": STACK,
                "regionSlug": "test-region",
            }
        if url.endswith("/connections"):
            return {"otlpHttpUrl": self.otlp}
        if url.endswith("/permissions"):
            return {"datasources:query": ["datasources:*"]}
        return []


class AccessCheckTests(unittest.TestCase):
    def test_all_metadata_reads_use_only_fixed_gets_and_exact_credential_domains(self):
        fake = Fake()
        result = access.check(STACK, "test-region", SM, CREDENTIALS, fake)
        self.assertEqual(set(result.values()), {"PASS"})
        self.assertEqual(len(fake.calls), 8)
        for method, url, token, kwargs in fake.calls:
            self.assertEqual(method, "GET")
            self.assertNotIn("payload", kwargs)
            kind = (
                "cloud"
                if url.startswith(("https://grafana.com/", "https://faro-api-"))
                else "sm"
                if url.startswith(SM)
                else "query"
                if url.endswith("/permissions")
                else "stack"
            )
            self.assertEqual(token, CREDENTIALS[access.SECRETS[kind]])
            self.assertNotIn("/api/ds/query", url)
            self.assertNotIn("/alerts", url)
        report = access.summary(result)
        for private in [*CREDENTIALS.values(), STACK, SM, "42", "datasources:*"]:
            self.assertNotIn(private, report)
        self.assertIn("PASS: 8", report)

    def test_cloud_connection_accepts_origin_and_exact_otlp_endpoint_without_forwarding_token(
        self,
    ):
        for suffix in ("", "/", "/otlp", "/otlp/"):
            fake = Fake()
            fake.otlp = "https://otlp-gateway-test-region.grafana.net" + suffix
            result = access.check(STACK, "test-region", "", CREDENTIALS, fake)
            self.assertEqual(result[access.CHECKS[1]], "PASS")
            self.assertFalse(
                any(
                    url.startswith("https://otlp-gateway-")
                    for _, url, _, _ in fake.calls
                )
            )
        for endpoint in (
            "https://otlp-gateway-test-region.grafana.net/otlp/v1/traces",
            "https://user:private@otlp-gateway-test-region.grafana.net/otlp",
            "https://otlp-gateway-test-region.grafana.net/otlp?token=private",
            "https://otlp-gateway-test-region.grafana.net:444/otlp",
        ):
            fake = Fake()
            fake.otlp = endpoint
            result = access.check(STACK, "test-region", "", CREDENTIALS, fake)
            self.assertEqual(result[access.CHECKS[1]], "FAIL")

    def test_unknown_sm_backend_is_pending_without_network_or_invented_endpoint(self):
        fake = Fake()
        result = access.check(STACK, "test-region", "", CREDENTIALS, fake)
        self.assertEqual(result[access.CHECKS[6]], "PENDING")
        self.assertEqual(result[access.CHECKS[7]], "PENDING")
        self.assertEqual(len(fake.calls), 6)

    def test_missing_secrets_and_server_failures_never_leak_values_or_bodies(self):
        fake = Fake()
        fake.fail = True
        result = access.check(STACK, "test-region", SM, CREDENTIALS, fake)
        report = access.summary(result)
        self.assertIn("FAIL", report)
        self.assertNotIn("private", report)
        fake = Fake()
        result = access.check(STACK, "test-region", SM, {}, fake)
        self.assertEqual(set(result.values()), {"PENDING"})
        self.assertFalse(fake.calls)

    def test_foreign_origins_ports_paths_and_credentials_reject_before_any_request(
        self,
    ):
        for stack, sm in [
            ("https://teststack.grafana.net:444", SM),
            ("https://user:private@teststack.grafana.net", SM),
            ("https://evil.invalid", SM),
            (STACK, "https://synthetic-monitoring-grpc-test.grafana.net:443"),
            (STACK, "https://evil.grafana.net"),
            (STACK, SM + "/foreign"),
        ]:
            fake = Fake()
            with (
                self.subTest(stack=stack, sm=sm),
                self.assertRaises(access.ProvisionError),
            ):
                access.check(stack, "test-region", sm, CREDENTIALS, fake)
            self.assertFalse(fake.calls)

    def test_transport_rejects_mutation_or_unregistered_destination(self):
        client = access.ReadOnlyTransport()
        client.allowed.add(STACK + "/api/datasources")
        with patch.object(client.opener, "open") as send:
            for method, url, payload in [
                ("POST", STACK + "/api/datasources", None),
                ("GET", "https://evil.invalid", None),
                ("GET", STACK + "/api/datasources", {}),
            ]:
                with self.assertRaises(access.ProvisionError):
                    client.request(method, url, "private", payload)
            send.assert_not_called()

    def test_redirect_never_forwards_authorization_and_transport_bounds_response(self):
        client = access.ReadOnlyTransport()
        url = STACK + "/api/datasources"
        client.allowed.add(url)
        redirect = next(
            handler
            for handler in client.opener.handlers
            if hasattr(handler, "redirect_request")
        )
        calls = []

        def send(request, timeout):
            calls.append(request)
            self.assertEqual(timeout, 30)
            self.assertEqual(request.get_header("Authorization"), "Bearer private")
            return redirect.redirect_request(
                request, None, 302, "redirect", {}, "https://evil.invalid"
            )

        with (
            patch.object(client.opener, "open", side_effect=send),
            self.assertRaises(access.ProvisionError),
        ):
            client.request("GET", url, "private")
        self.assertEqual(len(calls), 1)
        with patch.object(
            client.opener,
            "open",
            side_effect=HTTPError(
                url, 403, "private body", {}, io.BytesIO(b"private body")
            ),
        ):
            with self.assertRaises(access.ProvisionError) as error:
                client.request("GET", url, "private")
            self.assertNotIn("private", str(error.exception))

    def test_main_rejects_non_main_before_network_and_outputs_only_fixed_summary(self):
        with (
            patch.dict(
                access.os.environ,
                {
                    "GITHUB_EVENT_NAME": "workflow_dispatch",
                    "GITHUB_REF": "refs/heads/feature",
                },
                clear=True,
            ),
            patch.object(access, "check") as run,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            self.assertEqual(access.main(), 1)
            run.assert_not_called()
            self.assertNotIn("feature", output.getvalue())

    def test_oversized_or_invalid_json_is_rejected_without_body_in_diagnostics(self):
        client = access.ReadOnlyTransport()
        url = STACK + "/api/datasources"
        client.allowed.add(url)

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, bound):
                self.bound = bound
                return self.body[:bound]

        for body in [b"x" * (2 * 1024 * 1024 + 1), b"private-body-invalid-json"]:
            response = Response(body)
            with patch.object(client.opener, "open", return_value=response):
                with self.assertRaises(access.ProvisionError) as error:
                    client.request("GET", url, "private")
                self.assertEqual(response.bound, 2 * 1024 * 1024 + 1)
                self.assertNotIn("private", str(error.exception))

    def test_cloud_identity_mismatch_does_not_forward_stack_or_query_tokens(self):
        fake = Fake()
        result = access.check(STACK, "wrong-region", "", CREDENTIALS, fake)
        self.assertEqual(result[access.CHECKS[0]], "FAIL")
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][2], CREDENTIALS[access.SECRETS["cloud"]])
        self.assertEqual(result[access.CHECKS[5]], "PENDING")
