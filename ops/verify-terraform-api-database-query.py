#!/usr/bin/env python3
"""Verify API health and a public database-backed places query."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from api_smoke_url import places_query_url


def get_json(url: str) -> object:
    request = Request(url, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def verify(api_health_url: str, environment: str, fetch=get_json) -> dict[str, object]:
    health = fetch(api_health_url)
    if not isinstance(health, dict) or health.get("environment") != environment:
        raise ValueError(f"API health response is not the {environment} environment")

    places_url = places_query_url(api_health_url)
    page = fetch(places_url)
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise ValueError("Places endpoint did not return a database-backed place page")
    total = page.get("total")
    page_number = page.get("page")
    page_size = page.get("page_size")
    if (
        not isinstance(total, int)
        or total < 0
        or page_number != 1
        or not isinstance(page_size, int)
        or page_size < 1
        or len(page["items"]) > page_size
    ):
        raise ValueError("Places endpoint returned invalid pagination metadata")
    for item in page["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Places endpoint returned an invalid database record")

    return {
        "environment": environment,
        "route": "/api/v1/places",
        "result": "database_query_verified",
        "total": total,
        "returned_items": len(page["items"]),
        "verified_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-health-url", required=True)
    parser.add_argument("--environment", required=True, choices=["development", "production"])
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            result = verify(args.api_health_url, args.environment)
            if args.evidence:
                args.evidence.parent.mkdir(parents=True, exist_ok=True)
                args.evidence.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(
                f"{args.environment} API database query succeeded: "
                f"{result['returned_items']} item(s) in page; {result['total']} total."
            )
            return 0
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt < 5:
                time.sleep(10)
    print(f"Terraform API database-query verification failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
