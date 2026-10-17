"""Enforce review fields and reject blank contribution/report text."""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_contribution_validation"
down_revision: str | None = "0005_report_target_foreign_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_contributions_body_nonblank",
        "contributions",
        "length(trim(body)) >= 1",
    )
    op.create_check_constraint(
        "ck_contributions_review_fields",
        "contributions",
        "(kind = 'review' AND place_id IS NOT NULL AND rating IS NOT NULL) OR "
        "(kind <> 'review' AND rating IS NULL)",
    )
    op.create_check_constraint(
        "ck_reports_reason_nonblank",
        "reports",
        "length(trim(reason)) >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_reports_reason_nonblank", "reports", type_="check")
    op.drop_constraint("ck_contributions_review_fields", "contributions", type_="check")
    op.drop_constraint("ck_contributions_body_nonblank", "contributions", type_="check")
