from opentelemetry import trace

from pawlocal.application.ports import ContributionRepository, PlaceRepository
from pawlocal.domain.places import Place


class PlaceQueries:
    def __init__(self, repository: PlaceRepository):
        self.repository = repository

    def search(self, **filters) -> tuple[list[Place], int]:
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "places.search", attributes={"pawlocal.operation": "search"},
            record_exception=False, set_status_on_exception=False,
        ) as span:
            places, total = self.repository.search(**filters)
            span.set_attribute("pawlocal.outcome", "success" if places else "empty")
            return places, total

    def get(self, place_id) -> Place | None:
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "places.get", attributes={"pawlocal.operation": "detail"},
            record_exception=False, set_status_on_exception=False,
        ) as span:
            place = self.repository.get_published(place_id)
            span.set_attribute("pawlocal.outcome", "success" if place else "not_found")
            return place


class ReportableContributionQueries:
    def __init__(self, repository: ContributionRepository):
        self.repository = repository

    def list(self, *, page: int, page_size: int):
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "contributions.reportable",
            attributes={"pawlocal.operation": "reportable_list"},
            record_exception=False, set_status_on_exception=False,
        ):
            return self.repository.list_reportable(page=page, page_size=page_size)
