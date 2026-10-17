from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


class ErrorResponse(BaseModel):
    code: str
    message: str
