"""Quarantine invalid legacy content and enforce contribution/report checks."""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0006_contribution_validation"
down_revision: str | None = "0005_report_target_foreign_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Preserve legacy rows rejected by the new rules before moving them out of
    # the constrained tables. CTAS keeps every original field and its type;
    # the archive tables intentionally have no copied checks or foreign keys.
    op.execute(
        "CREATE TABLE contribution_quarantine AS "
        "SELECT c.*, NULL::text AS quarantine_reason, now() AS quarantined_at "
        "FROM contributions AS c WHERE false"
    )
    op.execute(
        "CREATE TABLE report_quarantine AS "
        "SELECT r.*, NULL::text AS quarantine_reason, now() AS quarantined_at "
        "FROM reports AS r WHERE false"
    )
    op.execute(
        "INSERT INTO contribution_quarantine "
        "SELECT c.*, CASE "
        "WHEN c.body !~ '[^[:space:]]' THEN 'body is blank or whitespace-only' "
        "WHEN c.kind = 'review' AND (c.place_id IS NULL OR c.rating IS NULL) "
        "THEN 'review is missing place_id or rating' "
        "WHEN c.kind <> 'review' AND c.rating IS NOT NULL "
        "THEN 'non-review contribution has a rating' END, now() "
        "FROM contributions AS c WHERE c.body !~ '[^[:space:]]' "
        "OR (c.kind = 'review' AND (c.place_id IS NULL OR c.rating IS NULL)) "
        "OR (c.kind <> 'review' AND c.rating IS NOT NULL)"
    )
    op.execute(
        "INSERT INTO report_quarantine "
        "SELECT r.*, CASE "
        "WHEN r.reason !~ '[^[:space:]]' THEN 'reason is blank or whitespace-only' "
        "ELSE 'report targets a quarantined contribution' END, now() "
        "FROM reports AS r WHERE r.reason !~ '[^[:space:]]' OR "
        "r.target_contribution_id IN ("
        "SELECT id FROM contribution_quarantine)"
    )
    op.execute(
        "DELETE FROM reports AS r WHERE r.reason !~ '[^[:space:]]' OR "
        "r.target_contribution_id IN ("
        "SELECT id FROM contribution_quarantine)"
    )
    op.execute(
        "DELETE FROM contributions AS c WHERE c.id IN "
        "(SELECT id FROM contribution_quarantine)"
    )
    _recompute_place_average_ratings()
    op.create_check_constraint(
        "ck_contributions_body_nonblank",
        "contributions",
        "body ~ '[^[:space:]]'",
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
        "reason ~ '[^[:space:]]'",
    )


def downgrade() -> None:
    # A newer review may have occupied the unique (author, place) key after
    # the legacy row was quarantined. Fail before DDL or data changes so the
    # operator can resolve the conflict and retry without losing either row.
    collision = op.get_bind().execute(
        text(
            "SELECT archived.id, archived.contributor_subject, archived.place_id "
            "FROM contribution_quarantine AS archived "
            "JOIN contributions AS active "
            "ON active.kind = 'review' "
            "AND active.contributor_subject = archived.contributor_subject "
            "AND active.place_id = archived.place_id "
            "WHERE archived.kind = 'review' AND archived.place_id IS NOT NULL "
            "LIMIT 1"
        )
    ).first()
    if collision is not None:
        raise RuntimeError(
            "Cannot downgrade 0006: quarantined review "
            f"{collision.id} conflicts with an active review for the same author/place "
            f"({collision.contributor_subject}, {collision.place_id}). Resolve the "
            "conflict before retrying the downgrade."
        )

    op.drop_constraint("ck_reports_reason_nonblank", "reports", type_="check")
    op.drop_constraint("ck_contributions_review_fields", "contributions", type_="check")
    op.drop_constraint("ck_contributions_body_nonblank", "contributions", type_="check")
    op.execute(
        "INSERT INTO contributions "
        "(id, kind, place_id, rating, body, contributor_subject, is_published, created_at) "
        "SELECT id, kind, place_id, rating, body, contributor_subject, is_published, created_at "
        "FROM contribution_quarantine ORDER BY quarantined_at, id"
    )
    op.execute(
        "INSERT INTO reports "
        "(id, target_type, target_place_id, target_contribution_id, reporter_subject, reason, status, created_at) "
        "SELECT id, target_type, target_place_id, target_contribution_id, reporter_subject, reason, status, created_at "
        "FROM report_quarantine ORDER BY quarantined_at, id"
    )
    _recompute_place_average_ratings()
    op.drop_table("report_quarantine")
    op.drop_table("contribution_quarantine")


def _recompute_place_average_ratings() -> None:
    """Treat place ratings as a projection of all currently published reviews."""
    op.execute(
        "UPDATE places AS p SET average_rating = ("
        "SELECT AVG(c.rating)::double precision FROM contributions AS c "
        "WHERE c.kind = 'review' AND c.is_published IS TRUE AND c.place_id = p.id)"
    )
