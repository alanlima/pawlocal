from pawlocal.application.ports import ContributionRepository, PlaceRepository
from pawlocal.domain.places import Place


class PlaceQueries:
    def __init__(self, repository: PlaceRepository):
        self.repository = repository

    def search(self, **filters) -> tuple[list[Place], int]:
        return self.repository.search(**filters)

    def get(self, place_id) -> Place | None:
        return self.repository.get_published(place_id)


class ReportableContributionQueries:
    def __init__(self, repository: ContributionRepository):
        self.repository = repository

    def list(self, *, page: int, page_size: int):
        return self.repository.list_reportable(page=page, page_size=page_size)
