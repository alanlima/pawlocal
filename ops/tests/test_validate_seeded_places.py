from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

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
        if url.endswith("/health"):
            return {"environment": "development"}
        if "/places?page=1" in url:
            return {"items": catalog_rows, "total": 2}
        place_id = url.rsplit("/", 1)[-1]
        return next(row for row in catalog_rows if row["id"] == place_id)

    monkeypatch.setattr(validator, "get_json", get_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "https://api-dev.example.test/health",
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
    assert "https://api-dev.example.test/api/v1/places/place-1" in calls
    assert "https://api-dev.example.test/api/v1/places/place-2" in calls


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
            "https://api.example.test/health",
            str(catalog),
            str(tmp_path / "evidence.json"),
        ],
    )

    assert validator.main() == 1
