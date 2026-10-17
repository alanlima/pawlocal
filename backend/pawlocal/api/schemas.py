from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pawlocal.domain.places import Facility


class PlaceSummary(BaseModel):
    id: UUID
    name: str
    category: Literal["dog_park", "beach", "walk", "hiking_area", "cafe"]
    area: str
    average_rating: float | None = Field(default=None, ge=1, le=5)


class PlaceResponse(PlaceSummary):
    address: str | None = None
    description: str | None = None
    dog_access_rules: str | None = Field(
        default=None, description="Unknown when unverified; never infer rules."
    )
    facilities: list[Facility] = Field(default_factory=list)
    source_updated_at: datetime | None = None


class PlacePage(BaseModel):
    items: list[PlaceSummary]
    page: int
    page_size: int
    total: int


class ReportableContribution(BaseModel):
    id: UUID
    kind: Literal["review", "location_suggestion", "tip", "correction"]
    body: str
    place_id: UUID | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    created_at: datetime


class ReportableContributionPage(BaseModel):
    items: list[ReportableContribution]
    page: int
    page_size: int
    total: int


class PlaceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_id: UUID


class ContributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["review", "location_suggestion", "tip", "correction"]
    place_id: UUID | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    body: str = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def validate_kind_fields(self):
        if not self.body.strip():
            raise ValueError("body must contain non-whitespace characters")
        if self.kind == "review":
            if self.place_id is None:
                raise ValueError("reviews require a place_id")
            if self.rating is None:
                raise ValueError("reviews require a rating")
        elif self.rating is not None:
            raise ValueError("only reviews may include a rating")
        return self


class ContributionResponse(BaseModel):
    id: UUID
    kind: Literal["review", "location_suggestion", "tip", "correction"]
    place_id: UUID | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    body: str
    created_at: datetime


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: Literal["place", "contribution"]
    target_id: UUID
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_reason(self):
        if not self.reason.strip():
            raise ValueError("reason must contain non-whitespace characters")
        return self


class ErrorResponse(BaseModel):
    code: str
    message: str
