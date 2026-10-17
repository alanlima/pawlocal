from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, validates

from pawlocal.domain.places import PLACE_FACILITIES
from pawlocal.infrastructure.database import Base


class PlaceRecord(Base):
    __tablename__ = "places"
    __table_args__ = (
        CheckConstraint(
            "category IN ('dog_park', 'beach', 'walk', 'hiking_area', 'cafe')",
            name="ck_places_category",
        ),
        CheckConstraint(
            "average_rating IS NULL OR (average_rating >= 1 AND average_rating <= 5)",
            name="ck_places_average_rating",
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_places_name_nonempty"),
        CheckConstraint(
            "facilities <@ ARRAY['Fenced', 'Off-leash area', 'Drinking water', "
            "'Shade', 'Picnic tables', 'Accessible paths']::varchar(80)[]",
            name="ck_places_facilities",
        ).ddl_if(dialect="postgresql"),
        Index("ix_places_area_category", "area", "category"),
        Index("ix_places_published_name", "is_published", "name"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    area: Mapped[str] = mapped_column(String(160), nullable=False)
    address: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    dog_access_rules: Mapped[str | None] = mapped_column(Text)
    facilities: Mapped[list[str]] = mapped_column(
        JSON().with_variant(ARRAY(String(80)), "postgresql"),
        nullable=False,
        default=list,
    )
    average_rating: Mapped[float | None] = mapped_column(Float)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @validates("facilities")
    def validate_facilities(self, _: str, facilities: list[str]) -> list[str]:
        unsupported = set(facilities) - set(PLACE_FACILITIES)
        if unsupported:
            raise ValueError(f"Unsupported place facilities: {sorted(unsupported)}")
        return facilities


class ContributionRecord(Base):
    __tablename__ = "contributions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('review', 'location_suggestion', 'tip', 'correction')",
            name="ck_contributions_kind",
        ),
        CheckConstraint(
            "length(body) BETWEEN 1 AND 5000", name="ck_contributions_body_length"
        ),
        CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)",
            name="ck_contributions_rating",
        ),
        Index("ix_contributions_published_created", "is_published", "created_at"),
        Index(
            "uq_contributions_review_author_place",
            "contributor_subject",
            "place_id",
            unique=True,
            postgresql_where=text("kind = 'review' AND place_id IS NOT NULL"),
            sqlite_where=text("kind = 'review' AND place_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    place_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("places.id"), nullable=True
    )
    rating: Mapped[int | None] = mapped_column()
    body: Mapped[str] = mapped_column(Text, nullable=False)
    contributor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FavouriteRecord(Base):
    __tablename__ = "favourites"
    __table_args__ = (Index("ix_favourites_place", "place_id"),)

    user_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    place_id: Mapped[UUID] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReportRecord(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('place', 'contribution')", name="ck_reports_target_type"
        ),
        CheckConstraint(
            "length(reason) BETWEEN 1 AND 2000", name="ck_reports_reason_length"
        ),
        CheckConstraint(
            "(target_type = 'place' AND target_place_id IS NOT NULL "
            "AND target_contribution_id IS NULL) OR "
            "(target_type = 'contribution' AND target_contribution_id IS NOT NULL "
            "AND target_place_id IS NULL)",
            name="ck_reports_target_reference",
        ),
        Index("ix_reports_target_place", "target_place_id"),
        Index("ix_reports_target_contribution", "target_contribution_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_place_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("places.id"), nullable=True
    )
    target_contribution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contributions.id"), nullable=True
    )
    reporter_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
