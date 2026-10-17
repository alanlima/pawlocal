from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

ContributionKind = Literal["review", "location_suggestion", "tip", "correction"]


@dataclass(frozen=True)
class ReportableContribution:
    id: UUID
    kind: ContributionKind
    body: str
    place_id: UUID | None
    rating: int | None
    created_at: datetime


@dataclass(frozen=True)
class SubmittedContribution:
    id: UUID
    kind: ContributionKind
    body: str
    place_id: UUID | None
    rating: int | None
    created_at: datetime
