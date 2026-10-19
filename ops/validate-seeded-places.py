#!/usr/bin/env python3
"""Verify the two expected seed records through the public places API."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from api_smoke_url import places_query_url

EXPECTED_PLACES = {"Orleigh Park", "Whites Hill Reserve"}


def validate_page(page: object) -> list[str]:
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise ValueError("Public places API did not return a place-page response")
    names = [item.get("name") for item in page["items"] if isinstance(item, dict)]
    if any(not isinstance(name, str) for name in names):
        raise ValueError("Public places API returned an item without a valid name")
    missing = EXPECTED_PLACES - set(names)
    if missing:
        raise ValueError(f"Seeded places are missing from the public API: {', '.join(sorted(missing))}")
    if not isinstance(page.get("total"), int) or page["total"] < len(EXPECTED_PLACES):
        raise ValueError("Public places API total does not include both expected seed records")
    return sorted(EXPECTED_PLACES)


def seeded_places_url(api_health_url: str) -> str:
    parts = urlsplit(places_query_url(api_health_url))
    query = dict(parse_qsl(parts.query))
    query["page_size"] = "100"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: validate-seeded-places.py <api-health-url> <evidence-file>", file=sys.stderr)
        return 2
    api_health_url, evidence_path = sys.argv[1:]
    try:
        request = Request(seeded_places_url(api_health_url), headers={"Cache-Control": "no-cache"})
        with urlopen(request, timeout=30) as response:
            page = json.loads(response.read())
        verified_places = validate_page(page)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        print(f"Seeded place smoke check failed: {exc}", file=sys.stderr)
        return 1

    evidence = {
        "route": "/api/v1/places",
        "result": "expected_seeded_places_returned",
        "places": verified_places,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    output = Path(evidence_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Public API returned Orleigh Park and Whites Hill Reserve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
