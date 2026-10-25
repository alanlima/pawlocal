import os
from unittest.mock import patch
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parents[2] / "ops/incident-response"
sys.path.insert(0, str(DIRECTORY))
import diagnostics


class Response(io.BytesIO):
    status = 200


def frame(fields, values):
    return {
        "results": {
            "A": {
                "frames": [{"schema": {"fields": fields}, "data": {"values": values}}]
            }
        }
    }


@patch.dict(os.environ, {'PAWLOCAL_ONCALL_ENFORCE_GUARDS': 'true'})
class DiagnosticsTests(unittest.TestCase):
    def test_three_fixed_queries_bind_environment_release_and_remove_private_content(
        self,
    ):
        metric = frame(
            [
                {
                    "name": "value",
                    "type": "number",
                    "labels": {
                        "diagnostic": "api_requests",
                        "route": "/new-api/CUSTOMER_SENTINEL?search=private",
                        "outcome": "error",
                        "private": "CUSTOMER_SENTINEL",
                    },
                }
            ],
            [[3]],
        )
        logs = frame(
            [{"name": "Line", "type": "string"}],
            [
                [
                    "api.request.completed|query|error|500|42|"
                    + "a" * 32
                    + "|SELECT_CUSTOMER_SENTINEL"
                ]
            ],
        )
        traces = frame(
            [
                {"name": "traceID", "type": "string"},
                {"name": "rootTraceName", "type": "string"},
                {"name": "durationMs", "type": "number"},
            ],
            [["a" * 32], ["CUSTOMER_SENTINEL"], [42]],
        )
        requests = []

        class Opener:
            def open(self, request, timeout):
                requests.append((request, timeout))
                return Response(
                    json.dumps([metric, logs, traces][len(requests) - 1]).encode()
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "observability/grafana/cloud/bindings.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "environments": {
                            "development": {
                                "enabled": True,
                                "approval": "fixture-only",
                                "stack": {"url": "https://fixture.grafana.net"},
                                "datasources": {
                                    name: {"uid": name + "-fixture", "name": name}
                                    for name in ("metrics", "logs", "traces")
                                },
                            }
                        },
                    }
                )
            )
            result = diagnostics.gather(
                root,
                "https://fixture.grafana.net",
                "fixture-not-real-token",
                {"environment": "development", "service": "pawlocal-api"},
                {"image_digest": "sha256:" + "b" * 64},
                time.time() + 30,
                Opener(),
            )
        self.assertEqual(set(result["signals"]), {"metrics", "logs", "traces"})
        self.assertNotIn("CUSTOMER_SENTINEL", json.dumps(result))
        self.assertEqual(result["signals"]["logs"]["rows"][0]["error"], "other")
        for request, timeout in requests:
            payload = json.loads(request.data)
            self.assertEqual(
                request.full_url, "https://fixture.grafana.net/api/ds/query"
            )
            self.assertLessEqual(timeout, 15)
            self.assertEqual(int(payload["to"]) - int(payload["from"]), 600000)
            query = payload["queries"][0]
            expression = query.get("expr", query.get("query"))
            self.assertIn("development", expression)
            self.assertIn("sha256:" + "b" * 64, expression)
            self.assertEqual(query["maxDataPoints"], 20)

    def test_unknown_health_is_not_healthy_and_query_failure_denies(self):
        empty = diagnostics.summarize("logs", {"results": {"A": {"frames": []}}})
        self.assertEqual(empty, {"status": "no_samples_unknown_health", "rows": []})
        for value in (
            {"results": {"A": {"error": "private unavailable", "frames": []}}},
            frame([{"name": "Line"}], [["x"] * 21]),
        ):
            with self.assertRaises(diagnostics.Denied):
                diagnostics.summarize("logs", value)

    def test_unknown_log_projection_does_not_forward_raw_sql_or_search_text(self):
        with self.assertRaises(diagnostics.Denied):
            diagnostics.summarize(
                "logs", frame([{"name": "Line"}], [["raw customer search/SQL"]])
            )


if __name__ == "__main__":
    unittest.main()
