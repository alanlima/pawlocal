from sqlalchemy import and_, any_, func, or_, select
from sqlalchemy.orm import Session

from pawlocal.domain.places import Place, validate_category
from pawlocal.infrastructure.models import PlaceRecord


class SqlAlchemyPlaceRepository:
    def __init__(self, session: Session):
        self.session = session

    def search(
        self,
        *,
        query: str | None,
        area: str | None,
        category: str | None,
        facilities: list[str],
        page: int,
        page_size: int,
    ) -> tuple[list[Place], int]:
        statement = select(PlaceRecord).where(PlaceRecord.is_published.is_(True))
        if query:
            escaped_query = (
                query.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped_query}%"
            statement = statement.where(
                or_(
                    PlaceRecord.name.ilike(pattern, escape="\\"),
                    PlaceRecord.area.ilike(pattern, escape="\\"),
                    PlaceRecord.category.ilike(pattern, escape="\\"),
                )
            )
        if area:
            statement = statement.where(PlaceRecord.area == area.strip())
        if category:
            validate_category(category)
            statement = statement.where(PlaceRecord.category == category)
        dialect_name = self.session.get_bind().dialect.name
        for index, facility in enumerate(facilities):
            if dialect_name == "postgresql":
                statement = statement.where(facility == any_(PlaceRecord.facilities))
            else:
                facility_values = (
                    func.json_each(PlaceRecord.facilities)
                    .table_valued("value")
                    .alias(f"facility_{index}")
                )
                statement = statement.where(
                    select(1)
                    .select_from(facility_values)
                    .where(facility_values.c.value == facility)
                    .correlate(PlaceRecord)
                    .exists()
                )

        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        records = self.session.scalars(
            statement.order_by(PlaceRecord.name, PlaceRecord.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return [self._to_domain(record) for record in records], total

    def get_published(self, place_id) -> Place | None:
        record = self.session.scalar(
            select(PlaceRecord).where(
                and_(PlaceRecord.id == place_id, PlaceRecord.is_published.is_(True))
            )
        )
        return self._to_domain(record) if record else None

    @staticmethod
    def _to_domain(record: PlaceRecord) -> Place:
        return Place(
            id=record.id,
            name=record.name,
            category=record.category,
            area=record.area,
            address=record.address,
            description=record.description,
            dog_access_rules=record.dog_access_rules,
            facilities=tuple(record.facilities or []),
            average_rating=record.average_rating,
            source_updated_at=record.source_updated_at,
        )
