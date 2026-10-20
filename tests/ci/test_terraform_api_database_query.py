import importlib.util
import sys
from pathlib import Path

import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops/verify-terraform-api-database-query.py"
SPEC = importlib.util.spec_from_file_location("terraform_api_database_query", SCRIPT)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


class TerraformApiDatabaseQueryTests(unittest.TestCase):
    def test_verify_checks_environment_and_database_backed_places_response(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url.endswith("/health"):
                return {"environment": "development"}
            return {"items": [{"id": "place-1"}], "page": 1, "page_size": 1, "total": 1}

        result = VERIFIER.verify("https://api-dev.example.test/health", "development", fetch)

        self.assertEqual(result["result"], "database_query_verified")
        self.assertEqual(result["total"], 1)
        self.assertEqual(calls, [
            "https://api-dev.example.test/health",
            "https://api-dev.example.test/api/v1/places?page=1&page_size=1",
        ])

    def test_verify_fails_when_database_query_is_invalid_or_unavailable(self):
        responses = iter([
            {"environment": "production"},
            {"environment": "development"},
            {"items": [], "page": 1, "page_size": 1},
        ])
        with self.assertRaisesRegex(ValueError, "not the development environment"):
            VERIFIER.verify("https://api-dev.example.test/health", "development", lambda _url: next(responses))
        with self.assertRaisesRegex(ValueError, "invalid pagination"):
            VERIFIER.verify("https://api-dev.example.test/health", "development", lambda _url: next(responses))


if __name__ == "__main__":
    unittest.main()
