from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from pawlocal.domain.places import Place, validate_category
from pawlocal.infrastructure.models import PlaceFacilityRecord, PlaceRecord


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
        statement = build_search_statement(
            query=query, area=area, category=category, facilities=facilities
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

    def get_published(self, place_id) -> Place | None:
        record = self.session.scalar(
            select(PlaceRecord).where(
                and_(PlaceRecord.id == place_id, PlaceRecord.is_published.is_(True))
            )
        )
        return self._to_domain(record) if record else None


def build_search_statement(
    *, query: str | None, area: str | None, category: str | None, facilities: list[str]
):
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
    for facility in dict.fromkeys(facilities):
        matching_facility = (
            select(1)
            .select_from(PlaceFacilityRecord)
            .where(
                PlaceFacilityRecord.place_id == PlaceRecord.id,
                PlaceFacilityRecord.facility == facility,
            )
            .correlate(PlaceRecord)
            .exists()
        )
        statement = statement.where(matching_facility)
    return statement
