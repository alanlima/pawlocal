from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "validate-seeded-places.py"
SPEC = importlib.util.spec_from_file_location("validate_seeded_places", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def test_load_catalog_uses_ids_and_names(tmp_path):
    catalog = tmp_path / "places.json"
    catalog.write_text(
        json.dumps([{"id": "place-1", "name": "Orleigh Park"}]), encoding="utf-8"
    )

    assert validator.load_catalog(catalog) == [
        {"id": "place-1", "name": "Orleigh Park"}
    ]


def test_validate_page_requires_each_catalog_id_and_name():
    expected = [{"id": "place-1", "name": "Orleigh Park"}]

    assert (
        validator.validate_page(
            {
                "items": [{"id": "place-1", "name": "Orleigh Park"}],
                "total": 1,
            },
            expected,
        )
        == expected
    )

    with pytest.raises(ValueError, match="catalog IDs or names"):
        validator.validate_page(
            {"items": [{"id": "place-2", "name": "Orleigh Park"}], "total": 1},
            expected,
        )


def test_main_verifies_catalog_ids_in_list_and_detail(monkeypatch, tmp_path):
    catalog_rows = [
        {"id": "place-1", "name": "Orleigh Park"},
        {"id": "place-2", "name": "Whites Hill Reserve"},
    ]
    catalog = tmp_path / "places.json"
    catalog.write_text(json.dumps(catalog_rows), encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    calls: list[str] = []

    def get_json(url: str):
        calls.append(url)
        if url.endswith("/api/health"):
            return {"environment": "development"}
        if "/places?page=1" in url:
            return {"items": catalog_rows, "page": 1, "page_size": 100, "total": 2}
        place_id = url.rsplit("/", 1)[-1]
        return next(row for row in catalog_rows if row["id"] == place_id)

    monkeypatch.setattr(validator, "get_json", get_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "https://pawlocal-dev.example.test/api/health",
            str(catalog),
            str(evidence),
        ],
    )

    assert validator.main() == 0
    result = json.loads(evidence.read_text(encoding="utf-8"))
    assert result["environment"] == "development"
    assert [place["id"] for place in result["places"]] == ["place-1", "place-2"]
    assert [detail["id"] for detail in result["detail_results"]] == [
        "place-1",
        "place-2",
    ]
    assert any("/api/v1/places?page=1&page_size=100" in url for url in calls)
    assert "https://pawlocal-dev.example.test/api/v1/places/place-1" in calls
    assert "https://pawlocal-dev.example.test/api/v1/places/place-2" in calls


def test_main_verifies_catalog_record_on_second_list_page(monkeypatch, tmp_path):
    catalog_rows = [
        {"id": "place-1", "name": "Orleigh Park"},
        {"id": "place-2", "name": "Whites Hill Reserve"},
    ]
    catalog = tmp_path / "places.json"
    catalog.write_text(json.dumps(catalog_rows), encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    first_page_items = [
        {"id": f"other-{number}", "name": f"Other Place {number}"}
        for number in range(1, 101)
    ]
    calls: list[str] = []

    def get_json(url: str):
        calls.append(url)
        if url.endswith("/api/health"):
            return {"environment": "development"}
        if "/places?page=1" in url:
            return {
                "items": first_page_items,
                "page": 1,
                "page_size": 100,
                "total": 102,
            }
        if "/places?page=2" in url:
            return {
                "items": catalog_rows,
                "page": 2,
                "page_size": 100,
                "total": 102,
            }
        place_id = url.rsplit("/", 1)[-1]
        return next(row for row in catalog_rows if row["id"] == place_id)

    monkeypatch.setattr(validator, "get_json", get_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "https://pawlocal-dev.example.test/api/health",
            str(catalog),
            str(evidence),
        ],
    )

    assert validator.main() == 0
    result = json.loads(evidence.read_text(encoding="utf-8"))
    assert [place["id"] for place in result["places"]] == ["place-1", "place-2"]
    assert "https://pawlocal-dev.example.test/api/v1/places?page=2&page_size=100" in calls


def test_main_refuses_non_development_health_response(monkeypatch, tmp_path):
    catalog = tmp_path / "places.json"
    catalog.write_text(
        json.dumps([{"id": "place-1", "name": "Orleigh Park"}]), encoding="utf-8"
    )
    monkeypatch.setattr(
        validator, "get_json", lambda _url: {"environment": "production"}
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "https://pawlocal.example.test/api/health",
            str(catalog),
            str(tmp_path / "evidence.json"),
        ],
    )

    assert validator.main() == 1


@pytest.mark.parametrize("failure,expected", [
    (HTTPError("https://pawlocal.example.test/api/health", 503, "Service Unavailable", {}, None),
     "HTTPError: HTTP Error 503: Service Unavailable"),
    (URLError("connection refused"), "URLError: <urlopen error connection refused>"),
])
def test_main_retains_http_status_and_transport_reason(monkeypatch, tmp_path, capsys, failure, expected):
    catalog = tmp_path / "places.json"
    catalog.write_text(json.dumps([{"id": "place-1", "name": "Orleigh Park"}]), encoding="utf-8")

    def fail(_url):
        raise failure

    monkeypatch.setattr(validator, "get_json", fail)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "https://pawlocal.example.test/api/health", str(catalog), str(tmp_path / "evidence.json")])
    assert validator.main() == 1
    assert expected in capsys.readouterr().err
    assert not (tmp_path / "evidence.json").exists()
