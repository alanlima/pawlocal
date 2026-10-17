from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pawlocal.application.errors import DuplicateReviewError
from pawlocal.domain.contributions import SubmittedContribution
from pawlocal.infrastructure.models import (
    ContributionRecord,
    FavouriteRecord,
    PlaceRecord,
    ReportRecord,
)
from pawlocal.infrastructure.places import SqlAlchemyPlaceRepository


class CommunityRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_favourites(self, subject: str):
        records = self.session.scalars(
            select(PlaceRecord)
            .join(FavouriteRecord, FavouriteRecord.place_id == PlaceRecord.id)
            .where(
                FavouriteRecord.user_subject == subject,
                PlaceRecord.is_published.is_(True),
            )
            .order_by(PlaceRecord.name, PlaceRecord.id)
        ).all()
        return [SqlAlchemyPlaceRepository._to_domain(record) for record in records]

    def add_favourite(self, subject: str, place_id) -> bool:
        if SqlAlchemyPlaceRepository(self.session).get_published(place_id) is None:
            return False
        self.session.add(FavouriteRecord(user_subject=subject, place_id=place_id))
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
        return True

    def remove_favourite(self, subject: str, place_id) -> None:
        self.session.execute(
            delete(FavouriteRecord).where(
                FavouriteRecord.user_subject == subject,
                FavouriteRecord.place_id == place_id,
            )
        )
        self.session.commit()

    def submit_contribution(self, subject: str, values: dict):
        place_id = values.get("place_id")
        if (
            place_id
            and SqlAlchemyPlaceRepository(self.session).get_published(place_id) is None
        ):
            return None
        record = ContributionRecord(
            kind=values["kind"],
            place_id=place_id,
            rating=values.get("rating"),
            body=values["body"],
            contributor_subject=subject,
            is_published=True,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if values["kind"] == "review" and place_id:
                raise DuplicateReviewError from exc
            raise
        self.session.refresh(record)
        return SubmittedContribution(
            id=record.id,
            kind=record.kind,
            body=record.body,
            place_id=record.place_id,
            rating=record.rating,
            created_at=record.created_at,
        )

    def submit_report(self, subject: str, values: dict) -> bool:
        target_type = values["target_type"]
        target_id = values["target_id"]
        if target_type == "place":
            exists = (
                SqlAlchemyPlaceRepository(self.session).get_published(target_id)
                is not None
            )
        else:
            exists = (
                self.session.scalar(
                    select(ContributionRecord.id).where(
                        ContributionRecord.id == target_id,
                        ContributionRecord.is_published.is_(True),
                    )
                )
                is not None
            )
        if not exists:
            return False
        self.session.add(
            ReportRecord(
                target_type=target_type,
                target_id=target_id,
                reporter_subject=subject,
                reason=values["reason"],
            )
        )
        self.session.commit()
        return True
