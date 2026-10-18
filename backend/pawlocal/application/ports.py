from typing import Protocol
from uuid import UUID

from pawlocal.domain.contributions import ReportableContribution, SubmittedContribution
from pawlocal.domain.places import Place


class PlaceRepository(Protocol):
    def search(
        self,
        *,
        query: str | None,
        area: str | None,
        category: str | None,
        facilities: list[str],
        page: int,
        page_size: int,
    ) -> tuple[list[Place], int]: ...

    def get_published(self, place_id: UUID) -> Place | None: ...


class ContributionRepository(Protocol):
    def list_reportable(
        self, *, page: int, page_size: int
    ) -> tuple[list[ReportableContribution], int]: ...


class CommunityRepository(Protocol):
    def list_favourites(self, subject: str) -> list[Place]: ...

    def add_favourite(self, subject: str, place_id: UUID) -> bool: ...

    def remove_favourite(self, subject: str, place_id: UUID) -> None: ...

    def submit_contribution(
        self, subject: str, values: dict
    ) -> SubmittedContribution | None: ...

    def submit_report(self, subject: str, values: dict) -> bool: ...
