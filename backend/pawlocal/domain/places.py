from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

PLACE_CATEGORIES = {"dog_park", "beach", "walk", "hiking_area", "cafe"}
PLACE_FACILITIES = {
    "Fenced",
    "Off-leash area",
    "Drinking water",
    "Shade",
    "Picnic tables",
    "Accessible paths",
}
PlaceCategory = Literal["dog_park", "beach", "walk", "hiking_area", "cafe"]
Facility = Literal[
    "Fenced",
    "Off-leash area",
    "Drinking water",
    "Shade",
    "Picnic tables",
    "Accessible paths",
]


@dataclass(frozen=True)
class Place:
    id: UUID
    name: str
    category: PlaceCategory
    area: str
    address: str | None
    description: str | None
    dog_access_rules: str | None
    facilities: tuple[str, ...]
    average_rating: float | None
    source_updated_at: datetime | None


def validate_category(category: str) -> None:
    if category not in PLACE_CATEGORIES:
        raise ValueError("Unsupported place category")
