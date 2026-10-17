"""Add private favourites and moderation reports."""

import sqlalchemy as sa
from alembic import op

revision = "0003_favourites_reports"
down_revision = "0002_contributions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favourites",
        sa.Column("user_subject", sa.String(length=255), nullable=False),
        sa.Column("place_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_subject", "place_id"),
    )
    op.create_index("ix_favourites_place", "favourites", ["place_id"])
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reporter_subject", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_type IN ('place', 'contribution')", name="ck_reports_target_type"
        ),
        sa.CheckConstraint(
            "length(reason) BETWEEN 1 AND 2000", name="ck_reports_reason_length"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_target", "reports", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_target", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_favourites_place", table_name="favourites")
    op.drop_table("favourites")
