"""Enforce review fields and reject blank contribution/report text."""

from collections.abc import Sequence

from alembic import op

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
    op.execute(
        "UPDATE places AS p SET average_rating = ("
        "SELECT AVG(c.rating)::double precision FROM contributions AS c "
        "WHERE c.kind = 'review' AND c.is_published IS TRUE AND c.place_id = p.id) "
        "WHERE p.id IN (SELECT place_id FROM contribution_quarantine "
        "WHERE kind = 'review' AND place_id IS NOT NULL)"
    )
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
    op.execute(
        "UPDATE places AS p SET average_rating = ("
        "SELECT AVG(c.rating)::double precision FROM contributions AS c "
        "WHERE c.kind = 'review' AND c.is_published IS TRUE AND c.place_id = p.id) "
        "WHERE p.id IN (SELECT place_id FROM contribution_quarantine "
        "WHERE kind = 'review' AND place_id IS NOT NULL)"
    )
    op.drop_table("report_quarantine")
    op.drop_table("contribution_quarantine")
