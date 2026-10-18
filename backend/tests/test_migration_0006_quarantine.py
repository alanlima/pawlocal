import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.mark.integration
def test_0006_quarantines_legacy_rows_and_downgrade_restores_them():
    database_url = os.getenv("PAWLOCAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set PAWLOCAL_TEST_DATABASE_URL for migration integration checks")

    engine = create_engine(database_url, pool_pre_ping=True)
    schema = f"pawlocal_migration_{uuid4().hex}"
    place_id = uuid4()
    valid_id, blank_body_id, missing_place_id, missing_rating_id, stray_rating_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    blank_report_id, linked_report_id, valid_report_id = uuid4(), uuid4(), uuid4()
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
                    "INSERT INTO places (id, name, category, area, facilities) "
                    "VALUES (:id, 'Migration fixture', 'dog_park', 'Brisbane City', "
                    "ARRAY['Shade']::varchar(80)[])"
                ),
                {"id": place_id},
            )
            contributions = [
                (valid_id, "review", place_id, 5, "valid legacy review"),
                (blank_body_id, "tip", None, None, " \t\n "),
                (missing_place_id, "review", None, 4, "review without place"),
                (missing_rating_id, "review", place_id, None, "review without rating"),
                (stray_rating_id, "tip", None, 3, "tip with rating"),
            ]
            for contribution in contributions:
                connection.execute(
                    text(
                        "INSERT INTO contributions "
                        "(id, kind, place_id, rating, body, contributor_subject) "
                        "VALUES (:id, :kind, :place_id, :rating, :body, 'legacy-user')"
                    ),
                    dict(
                        zip(
                            ("id", "kind", "place_id", "rating", "body"),
                            contribution,
                            strict=True,
                        )
                    ),
                )
            reports = [
                (blank_report_id, "place", place_id, None, " \t\n "),
                (linked_report_id, "contribution", None, blank_body_id, "legacy report"),
                (valid_report_id, "place", place_id, None, "valid report"),
            ]
            for report in reports:
                connection.execute(
                    text(
                        "INSERT INTO reports "
                        "(id, target_type, reporter_subject, reason, target_place_id, "
                        "target_contribution_id) "
                        "VALUES (:id, :target_type, 'legacy-reporter', :reason, "
                        ":target_place_id, :target_contribution_id)"
                    ),
                    dict(
                        zip(
                            (
                                "id",
                                "target_type",
                                "target_place_id",
                                "target_contribution_id",
                                "reason",
                            ),
                            report,
                            strict=True,
                        )
                    ),
                )
            connection.commit()

            command.upgrade(config, "head")
            active_contributions = connection.execute(
                text("SELECT id, body FROM contributions ORDER BY id")
            ).all()
            assert active_contributions == [(valid_id, "valid legacy review")]
            quarantined = connection.execute(
                text(
                    "SELECT id, kind, place_id, rating, body, contributor_subject, "
                    "is_published, quarantine_reason FROM contribution_quarantine "
                    "ORDER BY id"
                )
            ).all()
            assert {row.id for row in quarantined} == {
                blank_body_id,
                missing_place_id,
                missing_rating_id,
                stray_rating_id,
            }
            assert all(row.contributor_subject == "legacy-user" for row in quarantined)
            assert next(row for row in quarantined if row.id == blank_body_id).body == " \t\n "
            assert connection.execute(
                text("SELECT id FROM reports ORDER BY id")
            ).scalars().all() == [valid_report_id]
            quarantined_reports = connection.execute(
                text(
                    "SELECT id, reason, target_contribution_id, reporter_subject, "
                    "quarantine_reason FROM report_quarantine ORDER BY id"
                )
            ).all()
            assert {row.id for row in quarantined_reports} == {
                blank_report_id,
                linked_report_id,
            }
            linked = next(row for row in quarantined_reports if row.id == linked_report_id)
            assert linked.target_contribution_id == blank_body_id
            assert linked.reporter_subject == "legacy-reporter"

            command.downgrade(config, "0005_report_target_foreign_keys")
            restored_contributions = connection.execute(
                text("SELECT id, body FROM contributions ORDER BY id")
            ).all()
            assert {row.id for row in restored_contributions} == {
                valid_id,
                blank_body_id,
                missing_place_id,
                missing_rating_id,
                stray_rating_id,
            }
            restored_reports = connection.execute(
                text("SELECT id FROM reports ORDER BY id")
            ).scalars().all()
            assert set(restored_reports) == {
                blank_report_id,
                linked_report_id,
                valid_report_id,
            }
            connection.commit()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
