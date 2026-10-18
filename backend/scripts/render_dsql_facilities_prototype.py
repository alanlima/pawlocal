"""Render offline DSQL prototype SQL; this script never opens a connection."""

import argparse

from sqlalchemy import create_mock_engine

from pawlocal.dsql_facilities_prototype import (
    build_place_search,
    metadata,
)


def render_schema_sql() -> str:
    statements: list[str] = []

    def capture(statement, *multiparams, **params):
        del multiparams, params
        statements.append(str(statement.compile(dialect=engine.dialect)).strip() + ";")

    engine = create_mock_engine("auroradsql://", capture)
    metadata.create_all(engine)
    return "\n\n".join(statements) + "\n"


def render_query_sql() -> str:
    engine = create_mock_engine("auroradsql://", lambda *_args, **_kwargs: None)
    page, count = build_place_search(
        facilities=["Fenced", "Shade"], page=1, page_size=20
    )
    return "\n\n".join(
        [
            "-- Parameterized facility search; facility_0=Fenced and facility_1=Shade.",
            str(page.compile(dialect=engine.dialect)).strip() + ";",
            "-- Exact total count for the same filters.",
            str(count.compile(dialect=engine.dialect)).strip() + ";",
        ]
    ) + "\n"


def render_sql() -> str:
    return render_schema_sql() + "\n" + render_query_sql()


def normalize_sql(sql: str) -> str:
    """Remove dialect formatter trailing spaces for clean checked-in artifacts."""
    return "\n".join(line.rstrip() for line in sql.splitlines()) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="emit table and index DDL without query statements",
    )
    parser.add_argument(
        "--query-only",
        action="store_true",
        help="emit parameterized example queries without schema DDL",
    )
    args = parser.parse_args()
    if args.schema_only and args.query_only:
        parser.error("--schema-only and --query-only are mutually exclusive")
    rendered = (
        render_schema_sql()
        if args.schema_only
        else render_query_sql()
        if args.query_only
        else render_sql()
    )
    print(normalize_sql(rendered), end="")
