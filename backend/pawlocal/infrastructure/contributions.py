from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pawlocal.domain.contributions import ReportableContribution
from pawlocal.infrastructure.models import ContributionRecord


class SqlAlchemyContributionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_reportable(
        self, *, page: int, page_size: int
    ) -> tuple[list[ReportableContribution], int]:
        statement = select(ContributionRecord).where(
            ContributionRecord.is_published.is_(True)
        )
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        records = self.session.scalars(
            statement.order_by(
                ContributionRecord.created_at.desc(), ContributionRecord.id
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [
            ReportableContribution(
                id=record.id,
                kind=record.kind,
                body=record.body,
                place_id=record.place_id,
                rating=record.rating,
                created_at=record.created_at,
            )
            for record in records
        ], total
