from pawlocal.application.ports import ContributionRepository, PlaceRepository
from pawlocal.domain.places import Place
from pawlocal.observability import application_span


class PlaceQueries:
    def __init__(self, repository: PlaceRepository):
        self.repository = repository

    def search(self, **filters) -> tuple[list[Place], int]:
        with application_span("places.search", {"pawlocal.operation": "search"}) as span:
            places, total = self.repository.search(**filters)
            span.set_attribute("pawlocal.outcome", "success" if places else "empty")
            if len(places) > 1:
                # Rank search results by community average rating
                places = sorted(
                    places,
                    key=lambda place: place.average_rating if place.average_rating is not None else -1.0,
                    reverse=True,
                )
            return places, total

    def get(self, place_id) -> Place | None:
        with application_span("places.get", {"pawlocal.operation": "detail"}) as span:
            place = self.repository.get_published(place_id)
            span.set_attribute("pawlocal.outcome", "success" if place else "not_found")
            return place


class ReportableContributionQueries:
    def __init__(self, repository: ContributionRepository):
        self.repository = repository

    def list(self, *, page: int, page_size: int):
        with application_span(
            "contributions.reportable",
            {"pawlocal.operation": "reportable_list"},
        ):
            return self.repository.list_reportable(page=page, page_size=page_size)
