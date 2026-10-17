"""Create published places table."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_places"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("area", sa.String(length=160), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dog_access_rules", sa.Text(), nullable=True),
        sa.Column("facilities", postgresql.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("average_rating", sa.Float(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_published",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('dog_park', 'beach', 'walk', 'hiking_area', 'cafe')",
            name="ck_places_category",
        ),
        sa.CheckConstraint(
            "average_rating IS NULL OR (average_rating >= 1 AND average_rating <= 5)",
            name="ck_places_average_rating",
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_places_name_nonempty"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_places_area_category", "places", ["area", "category"])
    op.create_index("ix_places_published_name", "places", ["is_published", "name"])


def downgrade() -> None:
    op.drop_index("ix_places_published_name", table_name="places")
    op.drop_index("ix_places_area_category", table_name="places")
    op.drop_table("places")
