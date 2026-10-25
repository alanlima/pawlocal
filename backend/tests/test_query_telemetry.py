import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql, sqlite

from pawlocal.infrastructure.models import PlaceRecord
from pawlocal.infrastructure.places import build_search_statement
from pawlocal.infrastructure.query_telemetry import safe_query_template


@pytest.mark.parametrize(
    "dialect", [sqlite.dialect(), postgresql.dialect(paramstyle="pyformat")]
)
def test_actual_search_count_and_pagination_templates_never_contain_bound_values(
    dialect,
):
    statement = build_search_statement(
        query="private-password-sentinel ' -- 123456",
        area="private-address-sentinel",
        category="cafe",
        facilities=["Shade"],
    )
    for query in (
        statement.order_by(PlaceRecord.name).offset(123456).limit(765432),
        select(func.count()).select_from(statement.subquery()),
    ):
        compiled = query.compile(dialect=dialect)
        template = safe_query_template(str(compiled))
        assert template is not None
        assert template.startswith("SELECT ")
        assert "places" in template and "place_facilities" in template
        assert "?" in template
        assert safe_query_template(template) == template
        assert "sentinel" not in template
        assert "123456" not in template and "765432" not in template
        assert "cafe" not in template and "Shade" not in template


@pytest.mark.parametrize(
    "value",
    [
        "'private-token-sentinel'",
        "'private''token-sentinel'",
        "E'private\\'token-sentinel'",
        "123456.789e-12",
        ":private_bind_sentinel",
        "%(private_bind_sentinel)s",
        "%s",
        "$123456",
        "__[POSTCOMPILE_private_bind_sentinel]",
        "?",
    ],
)
def test_literal_and_driver_placeholder_forms_are_removed(value):
    assert (
        safe_query_template("SELECT places.id FROM places WHERE places.name = " + value)
        == "SELECT places . id FROM places WHERE places . name = ?"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT private_password_sentinel FROM places",
        'SELECT "private-password-sentinel" FROM places',
        'SELECT "places""name" FROM places',
        "SELECT places.id FROM private_table_sentinel",
        "SELECT places.id FROM places -- private-password-sentinel",
        "SELECT /* private-password-sentinel */ places.id FROM places",
        "SELECT places.id FROM places; SELECT places.name FROM places",
        "SELECT places.id FROM places WHERE name = 'unterminated",
        'SELECT "unterminated FROM places',
        "SELECT $$private-password-sentinel$$ FROM places",
        "SELECT $tag$private-password-sentinel$tag$ FROM places",
        "SELECT places.id FROM places WHERE name = X'private-sentinel'",
        "SELECT places.id FROM places WHERE name = 'private'\x00",
        "SELECT private_function_sentinel(places.id) FROM places",
        "SELECT places.id AS private_alias_sentinel FROM places",
        "SELECT places.id FROM places WHERE (places.id = ?",
        "DELETE FROM places WHERE id = ?",
        "INSERT INTO places(name) VALUES (?)",
        "UPDATE places SET name = ?",
        "SET LOCAL search_path TO pawlocal",
        "SELECT " + "places.id," * 5000,
        "SELECT " + ", ".join(["places.id"] * 500),
        None,
    ],
    ids=lambda sql: str(sql)[:70],
)
def test_unsupported_or_sensitive_query_shapes_are_omitted(sql):
    assert safe_query_template(sql) is None


def test_generated_alias_numbers_are_canonicalized_without_user_identifiers():
    template = safe_query_template(
        "SELECT count(*) AS count_1 FROM (SELECT places.id FROM places) AS anon_1"
    )
    assert (
        template
        == "SELECT COUNT ( * ) AS count_alias FROM ( SELECT places . id FROM places ) AS subquery_alias"
    )
