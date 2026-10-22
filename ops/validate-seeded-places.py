#!/usr/bin/env python3
"""Verify every catalog record through the development places API."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from api_smoke_url import places_query_url


def load_catalog(path: str | Path) -> list[dict[str, str]]:
    try:
        catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Seed catalog could not be read") from exc
    if not isinstance(catalog, list):
        raise TypeError("Seed catalog must be a JSON array")
    if not catalog:
        raise ValueError("Seed catalog must be a non-empty JSON array")
    expected: list[dict[str, str]] = []
    ids: set[str] = set()
    for row in catalog:
        if not isinstance(row, dict):
            raise TypeError("Seed catalog contains a non-object row")
        place_id, name = row.get("id"), row.get("name")
        if not isinstance(place_id, str) or not isinstance(name, str):
            raise TypeError("Seed catalog rows require string ID and name fields")
        if not name:
            raise ValueError("Seed catalog row name must not be empty")
        if place_id in ids:
            raise ValueError("Seed catalog contains duplicate place IDs")
        ids.add(place_id)
        expected.append({"id": place_id, "name": name})
    return expected


def validate_page(
    page: object, expected_places: list[dict[str, str]]
) -> list[dict[str, str]]:
    if not isinstance(page, dict):
        raise TypeError("Development places API did not return an object")
    if not isinstance(page.get("items"), list):
        raise TypeError("Development places API did not return a place-page response")
    actual = {
        item.get("id"): item.get("name")
        for item in page["items"]
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("name"), str)
    }
    missing = [
        place for place in expected_places if actual.get(place["id"]) != place["name"]
    ]
    if missing:
        raise ValueError(
            "One or more catalog IDs or names are missing from the development API"
        )
    if not isinstance(page.get("total"), int) or page["total"] < len(expected_places):
        raise ValueError(
            "Development places API total does not include every catalog record"
        )
    return expected_places


def seeded_places_url(api_health_url: str) -> str:
    parts = urlsplit(places_query_url(api_health_url))
    query = dict(parse_qsl(parts.query))
    query["page"] = "1"
    query["page_size"] = "100"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def list_url(api_health_url: str, page: int) -> str:
    parts = urlsplit(seeded_places_url(api_health_url))
    query = dict(parse_qsl(parts.query))
    query["page"] = str(page)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def api_url(api_health_url: str, path: str) -> str:
    parts = urlsplit(places_query_url(api_health_url))
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def get_json(url: str) -> object:
    request = Request(url, headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def fetch_verified_list(
    api_health_url: str,
    expected_places: list[dict[str, str]],
) -> list[dict[str, str]]:
    first_page = get_json(list_url(api_health_url, 1))
    if not isinstance(first_page, dict) or not isinstance(
        first_page.get("items"), list
    ):
        raise TypeError("Development places API did not return a place-page response")
    total = first_page.get("total")
    page_size = first_page.get("page_size")
    if (
        not isinstance(total, int)
        or total < 0
        or not isinstance(page_size, int)
        or page_size < 1
    ):
        raise TypeError("Development places API returned invalid pagination metadata")

    items = list(first_page["items"])
    page_count = max(1, (total + page_size - 1) // page_size)
    for page_number in range(2, page_count + 1):
        page = get_json(list_url(api_health_url, page_number))
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("items"), list)
            or page.get("total") != total
            or page.get("page_size") != page_size
            or page.get("page") != page_number
        ):
            raise ValueError(
                "Development places API pagination changed during verification"
            )
        items.extend(page["items"])

    return validate_page({"items": items, "total": total}, expected_places)


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: validate-seeded-places.py <api-health-url> <catalog-json> <evidence-file>",
            file=sys.stderr,
        )
        return 2
    api_health_url, catalog_path, evidence_path = sys.argv[1:]
    try:
        expected_places = load_catalog(catalog_path)
        health = get_json(api_health_url)
        if not isinstance(health, dict):
            raise TypeError("API health response did not return an object")
        if health.get("environment") != "development":
            raise ValueError("API health response is not the development environment")
        verified_places = fetch_verified_list(api_health_url, expected_places)
        detail_results = []
        for place in expected_places:
            detail = get_json(api_url(api_health_url, f"/api/v1/places/{place['id']}"))
            if not isinstance(detail, dict):
                raise TypeError("A catalog detail endpoint did not return an object")
            if detail.get("id") != place["id"] or detail.get("name") != place["name"]:
                raise ValueError(
                    "A catalog detail endpoint did not return the expected ID and name"
                )
            detail_results.append(
                {"id": place["id"], "name": place["name"], "status": 200}
            )
    except (
        HTTPError,
        URLError,
        TimeoutError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(f"Seeded place smoke check failed: {message}", file=sys.stderr)
        return 1

    evidence = {
        "route": "/api/v1/places",
        "environment": "development",
        "result": "catalog_ids_verified_in_list_and_detail",
        "places": verified_places,
        "detail_results": detail_results,
        "verified_at": datetime.now(UTC).isoformat(),
    }
    output = Path(evidence_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        f"Development API returned {len(verified_places)} catalog records in list and detail routes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
