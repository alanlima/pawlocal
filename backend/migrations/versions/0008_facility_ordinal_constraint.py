"""Require non-negative normalized facility ordinals.

Revision ID: 0008_facility_ordinal_constraint
Revises: 0007_normalize_place_facilities
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_facility_ordinal_constraint"
down_revision: str | None = "0007_normalize_place_facilities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_place_facilities_ordinal", "place_facilities", "ordinal >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_place_facilities_ordinal", "place_facilities", type_="check"
    )
