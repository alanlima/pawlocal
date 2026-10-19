from random import uniform
from time import sleep

from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, selectinload

from pawlocal.application.errors import DuplicateReviewError
from pawlocal.domain.contributions import SubmittedContribution
from pawlocal.infrastructure.models import (
    ContributionRecord,
    FavouriteRecord,
    PlaceRecord,
    ReportRecord,
)
from pawlocal.infrastructure.places import SqlAlchemyPlaceRepository

_DSQL_RETRYABLE_SQLSTATES = {"40001", "OC000", "OC001"}
_MAX_DSQL_REVIEW_ATTEMPTS = 3


class _RetryableDSQLOCCError(Exception):
    def __init__(self, error: DBAPIError):
        super().__init__("Retryable Aurora DSQL optimistic concurrency conflict")
        self.error = error


def _dsql_conflict_code(error: DBAPIError) -> str | None:
    """Return a database conflict code without formatting sensitive DB errors."""
    original = error.orig
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if code is None:
        diagnostic = getattr(original, "diag", None)
        code = getattr(diagnostic, "sqlstate", None)
    return code


class CommunityRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_favourites(self, subject: str):
        records = self.session.scalars(
            select(PlaceRecord)
            .options(selectinload(PlaceRecord.facility_records))
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
        if values["kind"] == "review":
            return self._submit_review_with_retry(subject, values)
        return self._submit_contribution_once(subject, values)

    def _submit_review_with_retry(self, subject: str, values: dict):
        is_dsql = self.session.get_bind().dialect.name == "auroradsql"
        attempts = _MAX_DSQL_REVIEW_ATTEMPTS if is_dsql else 1
        for attempt in range(attempts):
            try:
                return self._submit_review_once(subject, values)
            except _RetryableDSQLOCCError as exc:
                self.session.rollback()
                if attempt + 1 == attempts:
                    raise exc.error from exc
                # Bounded exponential jitter reduces repeated collisions between
                # requests that failed together without growing latency much.
                sleep(uniform(0, 0.01 * (2**attempt)))

    def _submit_review_once(self, subject: str, values: dict):
        return self._submit_contribution_once(
            subject,
            values,
            retry_dsql_occ=(
                self.session.get_bind().dialect.name == "auroradsql"
            ),
        )

    def _submit_contribution_once(
        self, subject: str, values: dict, *, retry_dsql_occ: bool = False
    ):
        place_id = values.get("place_id")
        place_record = None
        try:
            if place_id and values["kind"] == "review":
                place_record = self.session.scalar(
                    select(PlaceRecord)
                    .where(
                        PlaceRecord.id == place_id,
                        PlaceRecord.is_published.is_(True),
                    )
                    .with_for_update()
                )
                if place_record is None:
                    return None
            elif (
                place_id
                and SqlAlchemyPlaceRepository(self.session).get_published(place_id)
                is None
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
            self.session.flush()
            if values["kind"] == "review" and place_record is not None:
                average_rating = self.session.scalar(
                    select(func.avg(ContributionRecord.rating)).where(
                        ContributionRecord.kind == "review",
                        ContributionRecord.place_id == place_id,
                        ContributionRecord.is_published.is_(True),
                    )
                )
                place_record.average_rating = float(average_rating)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            if values["kind"] == "review" and place_id:
                raise DuplicateReviewError from exc
            raise
        except DBAPIError as exc:
            if (
                retry_dsql_occ
                and _dsql_conflict_code(exc) in _DSQL_RETRYABLE_SQLSTATES
            ):
                raise _RetryableDSQLOCCError(exc) from exc
            self.session.rollback()
            raise
        # Refresh is intentionally outside the retryable transaction block. A
        # transient error here may happen after commit, and replaying the review
        # could submit a duplicate or a second contribution.
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
                target_place_id=target_id if target_type == "place" else None,
                target_contribution_id=(
                    target_id if target_type == "contribution" else None
                ),
                reporter_subject=subject,
                reason=values["reason"],
            )
        )
        self.session.commit()
        return True
