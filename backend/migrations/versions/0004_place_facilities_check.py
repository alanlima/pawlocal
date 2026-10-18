"""Constrain persisted place facility values.

Revision ID: 0004_place_facilities_check
Revises: 0003_favourites_reports
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_place_facilities_check"
down_revision: str | None = "0003_favourites_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FACILITIES_CHECK = (
    "facilities <@ ARRAY['Fenced', 'Off-leash area', 'Drinking water', "
    "'Shade', 'Picnic tables', 'Accessible paths']::varchar(80)[]"
)


def upgrade() -> None:
    op.create_check_constraint("ck_places_facilities", "places", FACILITIES_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_places_facilities", "places", type_="check")
