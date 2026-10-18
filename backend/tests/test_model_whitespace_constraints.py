from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from pawlocal.infrastructure.models import PlaceRecord


def test_sqlite_metadata_rejects_whitespace_only_contribution_and_report(session_factory):
    with session_factory() as session:
        place_id = uuid4()
        session.add(
            PlaceRecord(
                id=place_id,
                name="Whitespace constraint fixture",
                category="dog_park",
                area="Brisbane City",
                facilities=[],
                is_published=True,
            )
        )
        session.commit()

        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO contributions "
                    "(id, kind, body, contributor_subject) "
                    "VALUES (:id, 'tip', :body, 'whitespace-test')"
                ),
                {"id": uuid4().hex, "body": " \t\n "},
            )
        session.rollback()

        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO reports "
                    "(id, target_type, target_place_id, reporter_subject, reason) "
                    "VALUES (:id, 'place', :place_id, 'whitespace-test', :reason)"
                ),
                {
                    "id": uuid4().hex,
                    "place_id": place_id.hex,
                    "reason": " \t\n ",
                },
            )
        session.rollback()
