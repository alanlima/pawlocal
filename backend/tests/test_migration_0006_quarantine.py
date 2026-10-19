import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.integration
def test_0006_quarantines_legacy_rows_and_downgrade_restores_them():
    database_url = os.getenv("PAWLOCAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set PAWLOCAL_TEST_DATABASE_URL for migration integration checks")

    engine = create_engine(database_url, pool_pre_ping=True)
    schema = f"pawlocal_migration_{uuid4().hex}"
    place_id, empty_place_id = uuid4(), uuid4()
    valid_id, blank_body_id, missing_place_id, missing_rating_id, stray_rating_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    unpublished_id, post_upgrade_review_id = uuid4(), uuid4()
    blank_report_id, linked_report_id, valid_report_id = uuid4(), uuid4(), uuid4()
    contribution_columns = (
        "id, kind, place_id, rating, body, contributor_subject, is_published, created_at"
    )
    report_columns = (
        "id, target_type, reporter_subject, reason, status, created_at, "
        "target_place_id, target_contribution_id"
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "0005_report_target_foreign_keys")
            connection.execute(
                text(
                    "INSERT INTO places "
                    "(id, name, category, area, facilities, average_rating) "
                    "VALUES (:id, 'Migration fixture', 'dog_park', 'Brisbane City', "
                    "ARRAY['Shade']::varchar(80)[], 3.0), "
                    "(:empty_id, 'Empty review fixture', 'dog_park', 'Brisbane City', "
                    "ARRAY['Shade']::varchar(80)[], 4.25)"
                ),
                {"id": place_id, "empty_id": empty_place_id},
            )
            contributions = [
                (valid_id, "review", place_id, 5, "valid legacy review", True),
                (blank_body_id, "review", place_id, 1, " \t\n ", True),
                (missing_place_id, "review", None, 4, "review without place", False),
                (missing_rating_id, "review", place_id, None, "review without rating", True),
                (stray_rating_id, "tip", None, 3, "tip with rating", False),
                (unpublished_id, "review", place_id, 1, "unpublished review", False),
            ]
            for index, contribution in enumerate(contributions):
                connection.execute(
                    text(
                        "INSERT INTO contributions "
                        "(id, kind, place_id, rating, body, contributor_subject, "
                        "is_published, created_at) "
                        "VALUES (:id, :kind, :place_id, :rating, :body, :subject, "
                        ":is_published, :created_at)"
                    ),
                    {
                        **dict(
                            zip(
                                ("id", "kind", "place_id", "rating", "body", "is_published"),
                                contribution,
                                strict=True,
                            )
                        ),
                        "subject": f"legacy-user-{index}",
                        "created_at": f"2026-10-18 12:00:0{index}+00:00",
                    },
                )
            reports = [
                (blank_report_id, "place", place_id, None, " \t\n ", "closed"),
                (linked_report_id, "contribution", None, blank_body_id, "legacy report", "pending"),
                (valid_report_id, "place", place_id, None, "valid report", "reviewed"),
            ]
            for index, report in enumerate(reports):
                connection.execute(
                    text(
                        "INSERT INTO reports "
                        "(id, target_type, reporter_subject, reason, target_place_id, "
                        "target_contribution_id, status, created_at) "
                        "VALUES (:id, :target_type, 'legacy-reporter', :reason, "
                        ":target_place_id, :target_contribution_id, :status, :created_at)"
                    ),
                    {
                        **dict(
                            zip(
                                ("id", "target_type", "target_place_id", "target_contribution_id", "reason", "status"),
                                report,
                                strict=True,
                            )
                        ),
                        "created_at": f"2026-10-18 13:00:0{index}+00:00",
                    },
                )
            original_contributions = connection.execute(
                text(f"SELECT {contribution_columns} FROM contributions ORDER BY id")
            ).all()
            original_reports = connection.execute(
                text(f"SELECT {report_columns} FROM reports ORDER BY id")
            ).all()
            connection.commit()

            # This test asserts revision 0006's quarantine/downgrade behavior.
            # Keep it pinned to that revision as later migrations are added;
            # the current Alembic head (0007) is covered by the CI head upgrade.
            command.upgrade(config, "0006_contribution_validation")
            active_contributions = connection.execute(
                text(f"SELECT {contribution_columns} FROM contributions ORDER BY id")
            ).all()
            assert active_contributions == [
                row
                for row in original_contributions
                if row.id in {valid_id, unpublished_id}
            ]
            quarantined = connection.execute(
                text(
                    f"SELECT {contribution_columns}, quarantine_reason "
                    "FROM contribution_quarantine ORDER BY id"
                )
            ).all()
            assert {row.id for row in quarantined} == {
                blank_body_id,
                missing_place_id,
                missing_rating_id,
                stray_rating_id,
            }
            assert [tuple(row[:8]) for row in quarantined] == [
                tuple(row)
                for row in original_contributions
                if row.id not in {valid_id, unpublished_id}
            ]
            reasons = {row.id: row.quarantine_reason for row in quarantined}
            assert reasons[blank_body_id] == "body is blank or whitespace-only"
            assert reasons[missing_place_id] == "review is missing place_id or rating"
            assert reasons[missing_rating_id] == "review is missing place_id or rating"
            assert reasons[stray_rating_id] == "non-review contribution has a rating"
            assert connection.execute(
                text("SELECT average_rating FROM places WHERE id = :id"),
                {"id": place_id},
            ).scalar_one() == 5.0
            assert connection.execute(
                text("SELECT average_rating FROM places WHERE id = :id"),
                {"id": empty_place_id},
            ).scalar_one() is None
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO contributions "
                        "(id, kind, body, contributor_subject) "
                        "VALUES (:id, 'tip', ' \t\n ', 'whitespace-check')"
                    ),
                    {"id": uuid4()},
                )
            connection.rollback()
            with pytest.raises(IntegrityError):
                connection.execute(
                    text(
                        "INSERT INTO reports "
                        "(id, target_type, target_place_id, reporter_subject, reason) "
                        "VALUES (:id, 'place', :place_id, 'whitespace-check', ' \t\n ')"
                    ),
                    {"id": uuid4(), "place_id": place_id},
                )
            connection.rollback()
            assert connection.execute(
                text(f"SELECT {report_columns} FROM reports ORDER BY id")
            ).all() == [row for row in original_reports if row.id == valid_report_id]
            quarantined_reports = connection.execute(
                text(
                    f"SELECT {report_columns}, quarantine_reason "
                    "FROM report_quarantine ORDER BY id"
                )
            ).all()
            assert {row.id for row in quarantined_reports} == {
                blank_report_id,
                linked_report_id,
            }
            assert [tuple(row[:8]) for row in quarantined_reports] == [
                tuple(row)
                for row in original_reports
                if row.id != valid_report_id
            ]
            report_reasons = {row.id: row.quarantine_reason for row in quarantined_reports}
            assert report_reasons[blank_report_id] == "reason is blank or whitespace-only"
            assert report_reasons[linked_report_id] == "report targets a quarantined contribution"

            connection.execute(
                text(
                    "INSERT INTO contributions "
                    "(id, kind, place_id, rating, body, contributor_subject) "
                    "VALUES (:id, 'review', :place_id, 4, 'new review', 'legacy-user-1')"
                ),
                {"id": post_upgrade_review_id, "place_id": place_id},
            )
            connection.commit()
            with pytest.raises(RuntimeError, match="same author/place"):
                command.downgrade(config, "0005_report_target_foreign_keys")
            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "0006_contribution_validation"
            assert connection.execute(
                text("SELECT COUNT(*) FROM contribution_quarantine")
            ).scalar_one() == 4
            failed_quarantine = connection.execute(
                text(
                    f"SELECT {contribution_columns}, quarantine_reason "
                    "FROM contribution_quarantine ORDER BY id"
                )
            ).all()
            assert [tuple(row[:8]) for row in failed_quarantine] == [
                tuple(row)
                for row in original_contributions
                if row.id not in {valid_id, unpublished_id}
            ]
            assert {row.id for row in failed_quarantine} == {
                blank_body_id,
                missing_place_id,
                missing_rating_id,
                stray_rating_id,
            }
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM pg_constraint "
                    "WHERE conrelid = 'contributions'::regclass "
                    "AND conname = 'ck_contributions_review_fields'"
                )
            ).scalar_one() == 1
            assert connection.execute(
                text(f"SELECT {report_columns} FROM reports ORDER BY id")
            ).all() == [row for row in original_reports if row.id == valid_report_id]
            assert connection.execute(
                text(
                    "SELECT id FROM contributions WHERE id = :id"
                ),
                {"id": post_upgrade_review_id},
            ).scalar_one() == post_upgrade_review_id
            assert set(
                connection.execute(
                    text("SELECT id FROM contributions")
                ).scalars()
            ) == {valid_id, unpublished_id, post_upgrade_review_id}
            assert [tuple(row[:8]) for row in connection.execute(
                text(
                    f"SELECT {report_columns}, quarantine_reason "
                    "FROM report_quarantine ORDER BY id"
                )
            ).all()] == [
                tuple(row)
                for row in original_reports
                if row.id != valid_report_id
            ]
            connection.execute(
                text("DELETE FROM contributions WHERE id = :id"),
                {"id": post_upgrade_review_id},
            )
            connection.commit()

            command.downgrade(config, "0005_report_target_foreign_keys")
            restored_contributions = connection.execute(
                text(f"SELECT {contribution_columns} FROM contributions ORDER BY id")
            ).all()
            assert restored_contributions == original_contributions
            restored_reports = connection.execute(
                text(f"SELECT {report_columns} FROM reports ORDER BY id")
            ).all()
            assert restored_reports == original_reports
            assert connection.execute(
                text("SELECT average_rating FROM places WHERE id = :id"),
                {"id": place_id},
            ).scalar_one() == 3.0
            assert connection.execute(
                text("SELECT average_rating FROM places WHERE id = :id"),
                {"id": empty_place_id},
            ).scalar_one() is None
            connection.commit()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
