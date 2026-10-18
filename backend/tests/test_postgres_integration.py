import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pawlocal.infrastructure.community import CommunityRepository, DuplicateReviewError
from pawlocal.infrastructure.contributions import SqlAlchemyContributionRepository
from pawlocal.infrastructure.models import (
    ContributionRecord,
    FavouriteRecord,
    PlaceRecord,
    ReportRecord,
)
from pawlocal.infrastructure.places import SqlAlchemyPlaceRepository


@pytest.mark.integration
def test_postgres_repositories_constraints_and_records_survive_new_sessions():
    database_url = os.getenv("PAWLOCAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip(
            "set PAWLOCAL_TEST_DATABASE_URL to run PostgreSQL integration checks"
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    place_id = uuid4()
    subject = f"stage3-test-{uuid4()}"
    contribution_id = None
    try:
        with Session(engine) as session:
            session.add(
                PlaceRecord(
                    id=place_id,
                    name="Synthetic Stage 3 Integration Park",
                    category="dog_park",
                    area="Brisbane City",
                    facilities=["Fenced", "Shade"],
                    is_published=True,
                )
            )
            session.commit()

            with pytest.raises(IntegrityError):
                session.execute(
                    text(
                        "INSERT INTO places (id, name, category, area, facilities) "
                        "VALUES (:id, 'Invalid facility integration fixture', "
                        "'dog_park', 'Brisbane City', "
                        "ARRAY['Unsupported facility']::varchar(80)[])"
                    ),
                    {"id": uuid4()},
                )
            session.rollback()

            place_repository = SqlAlchemyPlaceRepository(session)
            places, total = place_repository.search(
                query="Synthetic Stage 3",
                area="Brisbane City",
                category="dog_park",
                facilities=["Fenced", "Shade"],
                page=1,
                page_size=10,
            )
            assert total == 1
            assert places[0].id == place_id
            assert place_repository.get_published(place_id).facilities == (
                "Fenced",
                "Shade",
            )

            community = CommunityRepository(session)
            assert community.add_favourite(subject, place_id)
            assert community.add_favourite(subject, place_id)
            assert [item.id for item in community.list_favourites(subject)] == [
                place_id
            ]

            contribution = community.submit_contribution(
                subject,
                {
                    "kind": "review",
                    "place_id": place_id,
                    "rating": 5,
                    "body": "Synthetic integration review",
                },
            )
            contribution_id = contribution.id
            with pytest.raises(DuplicateReviewError):
                community.submit_contribution(
                    subject,
                    {
                        "kind": "review",
                        "place_id": place_id,
                        "rating": 4,
                        "body": "Duplicate synthetic review",
                    },
                )
            assert community.submit_report(
                subject,
                {
                    "target_type": "contribution",
                    "target_id": contribution_id,
                    "reason": "Synthetic integration report",
                },
            )
            session.add(
                ReportRecord(
                    target_type="place",
                    target_place_id=uuid4(),
                    reporter_subject=subject,
                    reason="Synthetic orphan target check",
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

        with Session(engine) as session:
            reportable, total = SqlAlchemyContributionRepository(
                session
            ).list_reportable(page=1, page_size=10)
            assert total >= 1
            assert any(item.id == contribution_id for item in reportable)
            assert session.get(PlaceRecord, place_id) is not None
            session.execute(
                delete(ReportRecord).where(
                    ReportRecord.target_contribution_id == contribution_id
                )
            )
            session.execute(
                delete(FavouriteRecord).where(FavouriteRecord.user_subject == subject)
            )
            session.execute(
                delete(ContributionRecord).where(
                    ContributionRecord.id == contribution_id
                )
            )
            session.execute(delete(PlaceRecord).where(PlaceRecord.id == place_id))
            session.commit()
    finally:
        engine.dispose()
