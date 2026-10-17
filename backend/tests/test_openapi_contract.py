from pathlib import Path

import yaml

from pawlocal.config import settings
from pawlocal.main import app


def test_runtime_openapi_documents_runtime_validation_and_auth_responses():
    contract = app.openapi()
    paths = contract["paths"]
    prefix = settings.api_prefix

    assert "400" in paths[f"{prefix}/places/{{place_id}}"]["get"]["responses"]
    for method in ("put", "delete"):
        operation = paths[
            f"{prefix}/me/favourites"
            if method == "put"
            else f"{prefix}/me/favourites/{{place_id}}"
        ][method]
        assert {"400", "429", "503"} <= operation["responses"].keys()
    for path, method in (
        (f"{prefix}/me/favourites", "get"),
        (f"{prefix}/contributions", "post"),
        (f"{prefix}/reports", "post"),
    ):
        assert "503" in paths[path][method]["responses"]


def test_runtime_openapi_matches_query_and_extra_field_validation():
    contract = app.openapi()
    specification = yaml.safe_load(
        (Path(__file__).parents[2] / "openapi.yaml").read_text(encoding="utf-8")
    )
    area = next(
        parameter
        for parameter in specification["paths"]["/places"]["get"]["parameters"]
        if parameter["name"] == "area"
    )
    assert area["schema"]["maxLength"] == 160

    schemas = contract["components"]["schemas"]
    for name in ("PlaceReference", "ContributionInput", "ReportInput"):
        assert schemas[name]["additionalProperties"] is False

    response = specification["paths"]["/contributions"]["post"]["responses"]["409"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Error"
    }


def test_openapi_documents_review_rating_and_nonblank_content_rules():
    specification = yaml.safe_load(
        (Path(__file__).parents[2] / "openapi.yaml").read_text(encoding="utf-8")
    )
    schemas = specification["components"]["schemas"]
    contribution = schemas["ContributionInput"]
    assert contribution["properties"]["body"]["pattern"] == r"\S"
    assert contribution["allOf"][0]["then"]["required"] == ["place_id", "rating"]
    assert contribution["allOf"][1]["then"]["properties"]["rating"] == {"type": "null"}
    assert schemas["ReportInput"]["properties"]["reason"]["pattern"] == r"\S"
