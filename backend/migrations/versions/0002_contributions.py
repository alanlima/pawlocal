"""Persist published and private contribution data."""

import sqlalchemy as sa
from alembic import op

revision = "0002_contributions"
down_revision = "0001_places"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contributions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("place_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("contributor_subject", sa.String(length=255), nullable=False),
        sa.Column(
            "is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('review', 'location_suggestion', 'tip', 'correction')",
            name="ck_contributions_kind",
        ),
        sa.CheckConstraint(
            "length(body) BETWEEN 1 AND 5000", name="ck_contributions_body_length"
        ),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_contributions_rating",
        ),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contributions_published_created",
        "contributions",
        ["is_published", "created_at"],
    )
    op.create_index(
        "uq_contributions_review_author_place",
        "contributions",
        ["contributor_subject", "place_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'review' AND place_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_contributions_review_author_place", table_name="contributions")
    op.drop_index("ix_contributions_published_created", table_name="contributions")
    op.drop_table("contributions")
