"""Render representative application place-search SQL using the AWS DSQL dialect."""

from aurora_dsql_sqlalchemy.psycopg import AuroraDSQLDialect_psycopg
from sqlalchemy import func, select

from pawlocal.infrastructure.models import PlaceRecord
from pawlocal.infrastructure.places import build_search_statement

statement = build_search_statement(
    query="park%_",
    area="Brisbane City",
    category="dog_park",
    facilities=["Fenced", "Shade"],
)
dialect = AuroraDSQLDialect_psycopg()
print(
    statement.order_by(PlaceRecord.name, PlaceRecord.id)
    .offset(0)
    .limit(20)
    .compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    .string
    + ";"
)
print(
    select(func.count())
    .select_from(statement.subquery())
    .compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    .string
    + ";"
)
