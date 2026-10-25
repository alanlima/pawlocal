#!/usr/bin/env python3
"""Build the public database-backed API query URL from the API health URL."""

from __future__ import annotations

import sys
from urllib.parse import urlsplit, urlunsplit

API_PREFIX = "/api/v1"


def places_query_url(health_url: str, api_prefix: str = API_PREFIX) -> str:
    parsed = urlsplit(health_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API health URL must be an absolute HTTP(S) URL")
    if parsed.path != "/api/health" or parsed.query or parsed.fragment:
        raise ValueError("API health URL must have the exact /api/health path")
    if not api_prefix.startswith("/") or api_prefix.endswith("/"):
        raise ValueError("API prefix must start with / and have no trailing slash")
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"{api_prefix}/places", "page=1&page_size=1", "")
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: api_smoke_url.py <api-health-url>")
    try:
        print(places_query_url(sys.argv[1]))
    except ValueError as error:
        raise SystemExit(str(error)) from error
