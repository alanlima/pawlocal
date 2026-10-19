"""Normalize facilities into rows for cross-dialect filtering.

Revision ID: 0007_normalize_place_facilities
Revises: 0006_contribution_validation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_normalize_place_facilities"
down_revision: str | None = "0006_contribution_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "auroradsql":
        raise RuntimeError(
            "Aurora DSQL requires its own clean-install and legacy-data migration "
            "sequence; this PostgreSQL array-to-row migration must not be run on DSQL."
        )

    op.create_table(
        "place_facilities",
        sa.Column("place_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("facility", sa.String(length=80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "facility IN ('Fenced', 'Off-leash area', 'Drinking water', 'Shade', "
            "'Picnic tables', 'Accessible paths')",
            name="ck_place_facilities_value",
        ),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("place_id", "facility"),
    )
    op.create_index(
        "ix_place_facilities_facility_place",
        "place_facilities",
        ["facility", "place_id"],
    )
    op.execute(
        sa.text(
            "INSERT INTO place_facilities (place_id, facility, ordinal) "
            "SELECT p.id, f.facility, MIN(f.ordinality)::integer - 1 "
            "FROM places AS p "
            "CROSS JOIN LATERAL unnest(p.facilities) WITH ORDINALITY "
            "AS f(facility, ordinality) "
            "GROUP BY p.id, f.facility"
        )
    )
    op.drop_constraint("ck_places_facilities", "places", type_="check")
    op.drop_column("places", "facilities")


def downgrade() -> None:
    if op.get_bind().dialect.name == "auroradsql":
        raise RuntimeError("The PostgreSQL downgrade is not supported on Aurora DSQL.")

    op.add_column(
        "places",
        sa.Column("facilities", sa.ARRAY(sa.String(length=80)), nullable=False, server_default="{}"),
    )
    op.execute(
        sa.text(
            "UPDATE places AS p SET facilities = COALESCE(("
            "SELECT array_agg(pf.facility ORDER BY pf.ordinal) "
            "FROM place_facilities AS pf WHERE pf.place_id = p.id), "
            "'{}'::varchar(80)[])"
        )
    )
    op.create_check_constraint(
        "ck_places_facilities",
        "places",
        "facilities <@ ARRAY['Fenced', 'Off-leash area', 'Drinking water', "
        "'Shade', 'Picnic tables', 'Accessible paths']::varchar(80)[]",
    )
    op.drop_index("ix_place_facilities_facility_place", table_name="place_facilities")
    op.drop_table("place_facilities")
