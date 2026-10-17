"""Use real foreign keys for polymorphic report targets.

Revision ID: 0005_report_target_foreign_keys
Revises: 0004_place_facilities_check
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_report_target_foreign_keys"
down_revision: str | None = "0004_place_facilities_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("target_place_id", sa.Uuid(), nullable=True))
    op.add_column(
        "reports", sa.Column("target_contribution_id", sa.Uuid(), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE reports SET target_place_id = target_id WHERE target_type = 'place'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE reports SET target_contribution_id = target_id "
            "WHERE target_type = 'contribution'"
        )
    )
    op.create_foreign_key(
        "fk_reports_target_place_id_places",
        "reports",
        "places",
        ["target_place_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_reports_target_contribution_id_contributions",
        "reports",
        "contributions",
        ["target_contribution_id"],
        ["id"],
    )
    op.drop_index("ix_reports_target", table_name="reports")
    op.drop_column("reports", "target_id")
    op.create_check_constraint(
        "ck_reports_target_reference",
        "reports",
        "(target_type = 'place' AND target_place_id IS NOT NULL "
        "AND target_contribution_id IS NULL) OR "
        "(target_type = 'contribution' AND target_contribution_id IS NOT NULL "
        "AND target_place_id IS NULL)",
    )
    op.create_index("ix_reports_target_place", "reports", ["target_place_id"])
    op.create_index(
        "ix_reports_target_contribution", "reports", ["target_contribution_id"]
    )


def downgrade() -> None:
    op.add_column("reports", sa.Column("target_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE reports SET target_id = COALESCE(target_place_id, "
            "target_contribution_id)"
        )
    )
    op.alter_column("reports", "target_id", nullable=False)
    op.drop_index("ix_reports_target_contribution", table_name="reports")
    op.drop_index("ix_reports_target_place", table_name="reports")
    op.drop_constraint("ck_reports_target_reference", "reports", type_="check")
    op.drop_constraint(
        "fk_reports_target_contribution_id_contributions",
        "reports",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_reports_target_place_id_places", "reports", type_="foreignkey"
    )
    op.drop_column("reports", "target_contribution_id")
    op.drop_column("reports", "target_place_id")
    op.create_index("ix_reports_target", "reports", ["target_type", "target_id"])
